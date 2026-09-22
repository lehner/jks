#
#    JKS - Measurement database system
#    Copyright (C) 2026  Christoph Lehner (christoph.lehner@ur.de, https://github.com/lehner/jks)
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
from __future__ import annotations

from itertools import combinations

import numpy as np
from scipy.optimize import nnls as _nnls

__all__ = [
    "min_chi_exact",
    "positivity_bounds",
    "band_center",
    "solver",
]


# --------------------------------------------------------------------------- #
# exact positivity bounds by column generation.
#
# For each target weight k(omega) the admissible range
#     [ lo_k, hi_k ] = range of  k.z   over
#     { z >= 0 : || A z - a || <= chi },     A = Lc^-1 E_S,  a = Lc^-1 C_s
# (Lc: Sigma_s = Lc Lc^T) is computed EXACTLY on the grid.
#
# If the optimal spectrum of  max s*k.z  (s = +1 for hi, -1 for lo) is
# supported on the grid nodes T (|T| <= m, A_T of full rank -- an optimum of
# this form always exists), it is closed form: with A_T = QR, z0 = R^-1 Q^T a
# the least-squares fit and rho^2 = chi^2 - |a - Q Q^T a|^2,
#
#     z_T   = z0 + rho R^-1 y / |y|,   y = R^-T (s k_T),
#     value = s k_T.z0 + rho |y|,
#     w     = (|y| / rho) (A_T z_T - a)            (whitened dual)
#
# and it is the optimum iff z_T >= 0 and A^T w >= s k on EVERY node (KKT;
# w is feasible for the dual  min a.w + chi |w|  s.t.  A^T w >= s k, with the
# same objective).  _colgen solves exactly on a small node set S (all faces
# of S, largest first), adds the most violated node and repeats.  It starts
# from the NNLS support (always feasible and of full rank) plus the support
# of the previous solve of the same (output, side), so a new data vector (a
# jackknife resample) typically costs one closed form and one pricing pass.
#
# This replaces a Kelley cutting-plane solve of the dual on HiGHS.  On the
# two examples it is 25x (lqcd) and 20x (fake) faster, exact to ~1e-12 of the
# band width where Kelley stopped on stall up to 9e-3 of the width outside,
# and it fixes two failure modes of the LP version: warm-started models
# returning a spurious kUnbounded (reported as an empty admissible set on up
# to half of the outputs at data vectors ~1 sigma apart), and the kernel
# thresholding  k[|k| <= 1e-9 max|k|] = 0, which dropped real contributions
# at grid nodes the data barely see and made the "rigorous" upper bound
# undershoot an admissible k.z.  No kernel thresholding is done here.
#
# For GENERAL data weights E_S (sign-changing, zero columns) the admissible
# set can be unbounded: its recession cone is { d >= 0 : E_S d = 0 }.  A
# target weight k is then bounded on the set iff k.d = 0 for every cone
# direction d -- checked by one small LP per side (_cone_unbounded).  The cone
# is {0} iff some combination of the data rows is strictly positive on the
# grid (Gordan), which holds trivially if one row is of one strict sign (e.g.
# any Laplace weight exp(-t omega)); the LPs are then skipped.  Unbounded
# outputs are reported as one-sided infinite bands.

def _cone_unbounded(E_eq, k, tol):
    """(hi_unbounded, lo_unbounded) for  max/min k.z over { z >= 0 : E z = 0 }.
    E_eq is column-equilibrated; the test LP is  max (k*rs).d'  s.t.
    E_eq d' = 0,  d' in the simplex  (d = rs o d' maps back to original units,
    so the optimum is in k-units).  infeasible <=> cone = {0} <=> bounded."""
    import highspy

    m, K = E_eq.shape
    I32 = np.arange(K, dtype=np.int32)

    def probe(kd):
        h = highspy.Highs()
        h.silent()
        h.setOptionValue("threads", 1)
        for j in range(K):
            h.addVariable(0.0, 1.0, 0.0)
        for i in range(m):
            h.addRow(0.0, 0.0, K, I32, np.ascontiguousarray(E_eq[i], np.float64))
        h.addRow(1.0, 1.0, K, I32, np.ascontiguousarray(np.ones(K), np.float64))
        h.changeColsCost(K, I32, np.ascontiguousarray(-kd, np.float64))
        h.run()
        st = h.getModelStatus()
        if st == highspy.HighsModelStatus.kInfeasible:
            return False
        if st != highspy.HighsModelStatus.kOptimal:
            return None
        d = np.asarray(h.getSolution().col_value, np.float64)
        return float(kd @ d) > tol

    return probe(k), probe(-k)
# --------------------------------------------------------------------------- #


def _face(A, a, aa, chi, ks, T):
    """Closed-form optimum of  max ks.z  s.t. ||A z - a|| <= chi  with z
    supported on T (sign of z_T not imposed).  Returns (value, z_T, w) or
    None if the face is rank deficient or cannot reach the chi ball."""
    if not T:                                      # z = 0, if admissible
        return (0.0, np.zeros(0), np.zeros(A.shape[0])) if aa <= chi * chi else None
    AT = A[:, T]
    cn = np.linalg.norm(AT, axis=0)                # equilibrate the columns
    Q, R = np.linalg.qr(AT / cn)
    dR = np.abs(np.diag(R))
    if dR.min() < 1e-11 * dR.max():
        return None
    qa = Q.T @ a
    rho2 = chi * chi - (aa - qa @ qa)
    if rho2 <= 0.0:
        return None
    rho = np.sqrt(rho2)
    y = np.linalg.solve(R.T, ks[T] / cn)
    ny = np.linalg.norm(y)
    if ny == 0.0:
        return None
    x0 = np.linalg.solve(R, qa)
    zT = (x0 + np.linalg.solve(R, y) * (rho / ny)) / cn
    return (ks[T] / cn) @ x0 + rho * ny, zT, (ny / rho) * (AT @ zT - a)


def _restricted(A, a, aa, chi, ks, S, vtol):
    """Exact optimum of the problem restricted to z_S >= 0: the first face T
    of S (largest first) that satisfies the KKT conditions on S."""
    m = A.shape[0]
    AS = A[:, S]
    for size in range(min(len(S), m), -1, -1):
        for T in combinations(range(len(S)), size):
            r = _face(A, a, aa, chi, ks, [S[i] for i in T])
            if r is None or (size and r[1].min() < 0.0):
                continue
            viol = ks[S] - AS.T @ r[2]
            viol[list(T)] = 0.0
            if viol.max() <= vtol:
                return r[0], [S[i] for i in T], r[1], r[2]
    return None


def _colgen(A, a, chi, ks, S0, vtol, dead, maxit=200):
    """Column generation for  max ks.z  s.t. z >= 0, ||A z - a|| <= chi.
    `dead` are the grid nodes no data weight sees (zero columns of A): they
    are never priced in -- the recession-cone test has already decided that
    the kernel vanishes there to its tolerance.
    Returns (value, T, z_T, w, iterations) or None."""
    aa = float(a @ a)
    S = list(dict.fromkeys(int(i) for i in S0))
    for it in range(maxit):
        r = _restricted(A, a, aa, chi, ks, S, vtol)
        if r is None:
            return None
        val, T, zT, w = r
        viol = ks - A.T @ w
        viol[T] = 0.0
        viol[dead] = 0.0
        jn = int(np.argmax(viol))
        if viol[jn] <= vtol:                       # dual feasible: optimal
            return val, T, zT, w, it + 1
        S = T + [jn]
    return None


def min_chi_exact(E_s, C_s, Sigma_s, omega_grid, floor=None) -> float:
    """Exact  min_{z >= 0} || Sigma_s^{-1/2} (E_s z - C_s) ||  (nonnegative
    least squares; the admissible set is empty for chi below this value)."""
    E_S = np.asarray(E_s, float)
    omega_grid = np.asarray(omega_grid, float)
    if floor is not None:
        keep = omega_grid >= float(floor)
        E_S = E_S[:, keep]
    c_data = np.asarray(C_s, float).ravel()
    Sigma_s = np.asarray(Sigma_s, float)
    Sig = 0.5 * (Sigma_s + Sigma_s.T)
    L = np.linalg.inv(np.linalg.cholesky(
        Sig + 1e-12 * np.trace(Sig) / len(Sig) * np.eye(len(Sig))))
    z, _ = _nnls(L @ E_S, L @ c_data)
    return float(np.linalg.norm(L @ (E_S @ z - c_data)))


class solver:
    """Persistent positivity-band solver for a FIXED (E_s, Sigma_s, kernel).

    The whitening, the recession-cone tests and the last optimal support of
    every (output, side) are kept, so evaluating the band at another data
    vector (a jackknife resample, a chi scan) is typically one closed-form
    solve per endpoint.  The results do not depend on this history.

        s = jks.positive_laplace.solver(E_s, Sigma_s, kernel, omega_grid)
        s.chi_min(C)                 -> exact NNLS tension of C
        s.bands(C, chi)              -> (lo, hi, M, info), see positivity_bounds
        s.nnls(C)                    -> (z*, chi_min), the maximum-likelihood
                                        positive spectrum on the grid

    Sigma_s enters only through its Cholesky factor, so the same object must
    not be reused across different input covariances."""

    def __init__(self, E_s, Sigma_s, kernel, omega_grid, floor=None, vtol=1e-10):
        omega_grid = np.asarray(omega_grid, float)
        E_S, E_L = np.asarray(E_s, float), np.asarray(kernel, float)
        K = len(omega_grid)
        if E_S.ndim != 2 or E_L.ndim != 2 or E_S.shape[1] != K or E_L.shape[1] != K:
            raise ValueError(
                "E_s (m, K) and kernel (p, K) must be 2-D with K=%d columns (one per "
                "omega_grid node); got shapes %s and %s" % (K, E_S.shape, E_L.shape))
        if floor is not None:
            keep = omega_grid >= float(floor)
            omega_grid, E_S, E_L = omega_grid[keep], E_S[:, keep], E_L[:, keep]
        if not (np.isfinite(E_S).all() and np.isfinite(E_L).all()):
            raise ValueError("E_s and kernel must be finite (got NaN/inf entries)")
        m, p = E_S.shape[0], E_L.shape[0]
        Sig = np.asarray(Sigma_s, float)
        Sig = 0.5 * (Sig + Sig.T)
        if Sig.shape != (m, m):
            raise ValueError("Sigma_s must be (%d, %d)" % (m, m))
        try:
            Lc = np.linalg.cholesky(Sig)
        except np.linalg.LinAlgError:
            Lc = np.linalg.cholesky(Sig + 1e-12 * np.trace(Sig) / m * np.eye(m))

        self.E_S, self.E_L, self.Lc = E_S, E_L, Lc
        self.Li = np.linalg.inv(Lc)
        self.A = self.Li @ E_S                     # whitened data weights
        self.m, self.p = m, p
        self.nrm = np.abs(E_L).max(1)
        self.dead = np.flatnonzero(np.abs(E_S).max(0) == 0.0)   # invisible nodes
        self.vtol = vtol                           # dual violation / max|k|
        self._supp = {}                            # (j, sign) -> last support
        self._last = (None, None)                  # (C bytes, nnls result)

        # recession-cone tests (data independent), skipped when trivially bounded
        self._cone = {}
        one_signed = ((E_S > 0).all(1) | (E_S < 0).all(1)).any()
        if not one_signed:
            colmax = np.abs(E_S).max(0)
            rs = np.where(colmax > 0.0, 1.0 / np.maximum(colmax, 1e-300), 1.0)
            E_eq = np.ascontiguousarray(E_S * rs[None, :])
            for j in range(p):
                if self.nrm[j] > 0.0:
                    self._cone[j] = _cone_unbounded(E_eq, E_L[j] * rs, 1e-9 * self.nrm[j])

    # ------------------------------------------------------------------ #
    def nnls(self, C):
        """(z*, chi_min) -- the Sigma-metric NNLS fit of C by a positive
        spectrum on the grid.  k.z* is the maximum-likelihood value of the
        output weight k and, unlike the band centre, does not move with chi."""
        c = np.asarray(C, float).ravel()
        if c.shape[0] != self.m:
            raise ValueError("C must have m=%d entries, got %d" % (self.m, c.shape[0]))
        key = c.tobytes()
        if self._last[0] != key:
            z, r = _nnls(self.A, self.Li @ c)
            self._last = (key, (z, float(r)))
        z, r = self._last[1]
        return z.copy(), r

    def chi_min(self, C):
        return self.nnls(C)[1]

    # ------------------------------------------------------------------ #
    def _one(self, j, a, chi, S_ml):
        """One target weight: exact band.  Returns (hi, lo, M, dcdchi, status,
        gap_rel, viol_rel); hi/lo are +-inf on unbounded sides, nan on failed
        sides; M and dcdchi are None unless both sides are solved."""
        nrm = self.nrm[j]
        if nrm <= 0.0:                             # zero target weight
            return 0.0, 0.0, np.zeros(self.m), 0.0, "zero_kernel", 0.0, 0.0
        ub_hi, ub_lo = self._cone.get(j, (False, False))
        if ub_hi is None or ub_lo is None:         # cone LP itself failed
            return np.nan, np.nan, None, None, "cone_lp_failed", np.nan, np.nan
        if ub_hi or ub_lo:
            st = "unbounded" if ub_hi and ub_lo else (
                "unbounded_hi" if ub_hi else "unbounded_lo")
            hi = np.inf if ub_hi else np.nan
            lo = -np.inf if ub_lo else np.nan
            return hi, lo, None, None, st, np.nan, np.nan
        out, w, gap, viol = {}, {}, 0.0, 0.0
        for sg in (+1, -1):
            ks = sg * self.E_L[j]
            r = _colgen(self.A, a, chi, ks, list(self._supp.get((j, sg), [])) + S_ml,
                        self.vtol * nrm, self.dead)
            if r is None:
                out[sg] = np.nan
                continue
            _, T, zT, wj, _ = r
            self._supp[(j, sg)] = T
            prim = float(ks[T] @ zT)                           # at an admissible z
            dual = float(a @ wj + chi * np.linalg.norm(wj))    # at a dual-feasible w
            out[sg] = sg * max(prim, dual)                     # the outer of the two
            w[sg] = wj
            scale = max(abs(dual), abs(prim))
            gap = max(gap, abs(dual - prim) / scale if scale > 0.0 else 0.0)
            vj = np.maximum(0.0, ks - self.A.T @ wj)
            vj[T] = 0.0                            # active: equalities, rounding only
            viol = max(viol, float(vj.max()) / nrm)
        if len(w) < 2:
            return out[+1], out[-1], None, None, "colgen_failed", np.nan, np.nan
        # envelope theorem: d hi/dC = Li^T w_hi, d lo/dC = -Li^T w_lo,
        #                   d hi/dchi = |w_hi|,  d lo/dchi = -|w_lo|
        M = 0.5 * (self.Li.T @ (w[+1] - w[-1]))
        dcdchi = 0.5 * (np.linalg.norm(w[+1]) - np.linalg.norm(w[-1]))
        return out[+1], out[-1], M, dcdchi, "ok", gap, viol

    def bands(self, C_vec, chi):
        """Exact admissible range of every target weight at the data vector
        C_vec; see positivity_bounds for the meaning of (lo, hi, M, info)."""
        c_data = np.asarray(C_vec, float).ravel()
        if c_data.shape[0] != self.m:
            raise ValueError("C must have m=%d entries, got %d"
                             % (self.m, c_data.shape[0]))
        if not np.isfinite(c_data).all():
            raise ValueError("C must be finite (got NaN/inf entries)")
        chi = float(chi)
        a = self.Li @ c_data
        z_ml, chi_min = self.nnls(c_data)
        S_ml = [int(i) for i in np.flatnonzero(z_ml > 0.0)] if chi > chi_min else None
        p = self.p
        lo = np.empty(p); hi = np.empty(p); M = np.full((p, self.m), np.nan)
        dcdchi = np.full(p, np.nan)
        status = []; gaps = []; viols = []
        for j in range(p):
            if S_ml is None and self.nrm[j] > 0.0:  # chi <= chi_min: no admissible z
                hi[j] = lo[j] = np.nan
                status.append("empty_set"); gaps.append(np.nan); viols.append(np.nan)
                continue
            hi[j], lo[j], Mj, dj, st, g, v = self._one(j, a, chi, S_ml)
            if Mj is not None:
                M[j] = Mj; dcdchi[j] = dj
            status.append(st); gaps.append(g); viols.append(v)
        info = dict(status=status, gap_rel=gaps, violation_rel=viols,
                    dcenter_dchi=dcdchi, hints=self)
        return lo, hi, M, info


def positivity_bounds(E_s, C_s, Sigma_s, kernel, omega_grid, chi, floor=None):
    """Exact admissible range of every target weight, plus the slope of the
    band midpoint.  Returns (lo, hi, M, info):

        lo[j], hi[j]   min/max of  kernel[j].z  over
                      { z >= 0 : (E_s z - C_s)^T Sigma_s^{-1} (E_s z - C_s) <= chi^2 }
                      (each finite endpoint is the outer of a primal value at an
                      admissible z and a dual value at a feasible certificate,
                      which agree to info['gap_rel'];  an endpoint is +-inf when
                      kernel[j] is unbounded on the set, i.e. when the recession
                      cone {d >= 0 : E_s d = 0} carries kernel[j])
        M[j]           d (lo[j]+hi[j])/2 / d C_s  at FIXED chi (m-vector, exact
                      by the envelope theorem; nan unless status is ok)
        info           dict with per-output
                         status        ok, zero_kernel, unbounded_hi,
                                       unbounded_lo, unbounded, empty_set
                                       (chi <= chi_min), or a failure string
                         gap_rel       |dual - primal| / |endpoint|
                         violation_rel dual violation off the support / max|kernel[j]|
                         dcenter_dchi  d (lo[j]+hi[j])/2 / d chi  at fixed C_s
                       and 'hints', the live solver object.

    E_s may have sign-changing entries; a grid node that no data weight sees
    (a zero column) carries invisible weight, which makes every kernel with a
    nonzero entry there unbounded -- reported, not capped.  For a chi scan or
    a full jackknife pass, build a `solver` once and call its bands() method
    directly."""
    s = solver(E_s, Sigma_s, kernel, omega_grid, floor=floor)
    return s.bands(C_s, chi)


def band_center(E_s, C_vec, Sigma_s, kernel, omega_grid, chi, hints=None,
                floor=None):
    """Center (lo+hi)/2 of every admissible band at data point C_vec.

    Returns (m, ok, hints):  m[j] = band center (nan where the band does not
    exist at C_vec, e.g. chi below chi_min(C_vec)); ok = per-output success
    mask; hints = the solver (pass it back in to reuse it)."""
    s = hints if isinstance(hints, solver) else solver(
        E_s, Sigma_s, kernel, omega_grid, floor=floor)
    lo, hi, M, info = s.bands(C_vec, chi)
    ok = np.array([st in ("ok", "zero_kernel") for st in info["status"]], bool)
    mm = np.where(ok, 0.5 * (lo + hi), np.nan)
    return mm, ok, s
