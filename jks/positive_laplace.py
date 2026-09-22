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


import numpy as np
import highspy

__all__ = [
    "min_chi_exact",
    "positivity_bounds",
    "band_center",
    "solver",
]

_INF = highspy.kHighsInf
_OPTIMAL = highspy.HighsModelStatus.kOptimal
_INFEASIBLE = highspy.HighsModelStatus.kInfeasible
_UNBOUNDED = highspy.HighsModelStatus.kUnbounded


# --------------------------------------------------------------------------- #
# deterministic certificate bounds (prototype replacement for the two-stage
# sampler + two-point chi^2 split).
#
# For each target weight k(omega) the admissible range
#     [ lo_k, hi_k ] = range of  k.z   over
#     { z >= 0 : (E_S z - C_s)^T Sigma_s^{-1} (E_S z - C_s) <= chi^2 }
# is computed EXACTLY (on the grid) from the small (m-dimensional) dual
#
#     hi_k = min_v  v.C + chi*||Lc^T v||   s.t.  E_S^T v >= k        (Lc: Sigma = Lc Lc^T)
#     lo_k = -min_v  v.C + chi*||Lc^T v||   s.t.  E_S^T v >= -k
#
# solved by Kelley cutting-plane on the norm epigraph, with every coefficient
# scaled to O(1) (the unscaled optimum at large lag is below HiGHS dual
# tolerance and silently corrupts the answer).  Each returned bound is the
# exact objective at a certificate v that satisfies the majorisation to
# within the reported violation, so the band can be checked in two lines of
# numpy.  The slope  M = d(m_k)/dC_s = 1/2 (nrm_v_hi - nrm_v_lo)  (envelope
# theorem) gives the statistical propagation:  central(c) = m + M (c - C_s).
#
# For GENERAL data weights E_S (sign-changing, zero columns) the admissible
# set { z >= 0 : (E_S z - C_s)^T Sigma_s^{-1} (E_S z - C_s) <= chi^2 } can be
# unbounded: its recession cone is { d >= 0 : E_S d = 0 }.  A target weight k
# is then bounded on the set iff  k.d = 0  for every cone direction d --
# checked by one small LP per side (below).  Bounded outputs are solved by the
# same dual as the positive-E_S case (no total-weight cap needed: the cap only
# compactifies, it does not change bounded optima); unbounded ones are reported
# as one-sided infinite bands, which is the honest answer (the old sampler
# replaced them with arbitrary W-cap-dependent finite numbers).
#
# The LP bookkeeping is INCREMENTAL: one HiGHS model per (output weight, side)
# is built once and kept alive, Kelley cuts are appended to it, the box is
# moved with changeColBounds, and a new data vector only needs
# changeColsCost -- so HiGHS dual-simplex warm starts from the previous basis
# and every cut is reused.  Re-creating the model inside the Kelley loop (one
# addRow call per row, ~40 times per solve) used to dominate the run time; at
# matched stopping rules the incremental form is 10x faster on both examples,
# with the band unchanged to 6e-13 of its width.  Part of that is spent on a
# longer stall budget (see stall_max), which buys a strictly tighter band; the
# net speed-up of a full analysis is ~4x (fake: 5.2 s -> 1.3 s) to ~2.6x (lqcd:
# 19.5 s -> 7.5 s), with bands 0.2-10% narrower than before.  The mathematics
# below -- scaling, box growth, stall and gap tests, cut de-duplication -- is
# exactly as before.

def _cone_unbounded(E_eq, k, tol):
    """(hi_unbounded, lo_unbounded) for  max/min k.z over { z >= 0 : E z = 0 }.
    E_eq is column-equilibrated; the test LP is  max (k*rs).d'  s.t.
    E_eq d' = 0,  d' in the simplex  (d = rs o d' maps back to original units,
    so the optimum is in k-units).  infeasible <=> cone = {0} <=> bounded."""
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
        if st == _INFEASIBLE:
            return False
        if st != _OPTIMAL:
            return None
        d = np.asarray(h.getSolution().col_value, np.float64)
        return float(kd @ d) > tol

    return probe(k), probe(-k)
# --------------------------------------------------------------------------- #


class _side:
    """The dual of ONE (output weight, side), kept alive across data points.

        phi = min { v.C_s + chi*||Lc^T v|| : E_eq^T v >= rhs },  v free, |v| <= box

    E_eq is column-equilibrated (O(1) entries); rhs = rs * k / nrm with nrm =
    max|k|, so the optimum is O(1) (the unscaled optimum of a late-lag kernel
    is below HiGHS dual tolerance and silently corrupts the answer) and
    v ~ O(1/nrm) (hence box0).  The Kelley cuts are data-independent, so the
    model is reused verbatim at every new data vector."""

    __slots__ = ("h", "m", "K", "E_eq", "Lc", "rhs", "cuts", "box", "idx",
                 "cut_max", "cost")

    def __init__(self, E_eq, rhs, Lc, box0, cut_max=400):
        self.E_eq, self.Lc = E_eq, Lc      # fixed for the life of the solver
        self.m = Lc.shape[0]
        self.K = rhs.shape[0]
        self.rhs = np.ascontiguousarray(rhs, np.float64)
        self.box = float(box0)
        self.idx = np.arange(self.m + 1, dtype=np.int32)
        self.cut_max = cut_max
        eye = np.eye(self.m)
        self.cuts = [eye[i] for i in range(self.m)] + [-eye[i] for i in range(self.m)]
        self.h = None
        self.cost = np.zeros(self.m + 1)
        self._build()

    def _rows(self, mat, lower, upper):
        n = mat.shape[0]
        self.h.addRows(n, np.ascontiguousarray(lower, np.float64),
                       np.ascontiguousarray(upper, np.float64), n * (self.m + 1),
                       np.arange(n, dtype=np.int32) * (self.m + 1),
                       np.ascontiguousarray(np.tile(self.idx, n), np.int32),
                       np.ascontiguousarray(mat.ravel(), np.float64))

    def _build(self):
        m, K = self.m, self.K
        h = highspy.Highs()
        h.silent()
        h.setOptionValue("threads", 1)
        for i in range(m):
            h.addVariable(-self.box, self.box, 0.0)
        h.addVariable(0.0, _INF, 0.0)                     # s (norm epigraph)
        self.h = h
        rows = np.zeros((K, m + 1))                       # majorisation rows
        rows[:, :m] = self.E_eq.T
        self._rows(rows, self.rhs, np.full(K, _INF))
        nc = len(self.cuts)                               # Kelley cuts s >= (Lc u).v
        cr = np.zeros((nc, m + 1))
        cr[:, :m] = np.asarray(self.cuts) @ self.Lc.T
        cr[:, m] = -1.0
        self._rows(cr, np.full(nc, -_INF), np.zeros(nc))
        self.set_cost(self.cost)      # a rebuild must not lose the objective

    def set_cost(self, cost):
        self.cost = np.ascontiguousarray(cost, np.float64)
        self.h.changeColsCost(self.m + 1, self.idx, self.cost)

    def grow_box(self):
        self.box *= 8.0
        for i in range(self.m):
            self.h.changeColBounds(i, -self.box, self.box)

    def add_cut(self, u):
        if self.cuts and float(np.abs(u - self.cuts[-1]).max()) <= 1e-12:
            return
        if len(self.cuts) >= self.cut_max:                # keep the pool bounded
            self.cuts = self.cuts[:2 * self.m] + self.cuts[-(self.cut_max // 2):]
            self.cuts.append(u)
            self._build()
            return
        self.cuts.append(u)
        row = np.zeros(self.m + 1)
        row[:self.m] = self.Lc @ u
        row[self.m] = -1.0
        self.h.addRow(-_INF, 0.0, self.m + 1, self.idx,
                      np.ascontiguousarray(row, np.float64))


def _dual_bound_one(side, C_s, chi, maxit=200, tol=1e-9, box_max=25,
                    stall_max=8):
    """Kelley cutting-plane solve of `side` at the data vector C_s.

    Returns (phi_best, v_best, status); phi_best is the exact objective at
    v_best, so it is a VALID bound whatever the remaining gap; the caller
    checks v_best's majorisation in original units.  A solution sitting on the
    box is never accepted as converged (the objective may keep improving
    beyond it)."""
    m, Lc = side.m, side.Lc
    cost = np.zeros(m + 1)
    cost[:m] = C_s
    cost[m] = chi
    side.set_cost(cost)
    best, v_best = np.inf, None
    nbox = 0
    stalled = 0
    for _ in range(maxit):
        h = side.h                 # add_cut() may have rebuilt the model
        h.run()
        st = h.getModelStatus()
        if st == _INFEASIBLE:
            # the majorisation is feasible for |v| large enough (E_eq columns
            # positive), so infeasibility is the box -- grow it
            side.grow_box()
            nbox += 1
            if nbox > box_max:
                return None, None, "infeasible"
            continue
        if st == _UNBOUNDED:                              # admissible set empty
            return None, None, "empty_set"
        if st != _OPTIMAL:
            return None, None, str(st).rsplit(".", 1)[-1]
        x = np.asarray(h.getSolution().col_value, np.float64)
        v, s = x[:m], x[m]
        lb = float(C_s @ v + chi * s)
        w = Lc.T @ v
        ww = max(float(w @ w), 0.0)
        val = float(C_s @ v + chi * np.sqrt(ww))
        at_box = np.abs(v).max() > 0.999 * side.box
        # best is a VALID bound regardless of the gap (exact objective at a
        # majorisation-feasible v), so any stop keeps rigor; stop on the
        # optimality gap OR on stall -- the gap floor sits at the HiGHS LP
        # noise level, and a tight tol alone would burn all of maxit.
        # stall_max is what actually terminates the loop in practice (tol has
        # no effect below ~1e-9): raising it from 2 to 8 tightens the lqcd band
        # by 0.5% and converges the quoted stat to 0.05%, at 3x the LP count --
        # affordable now that the model is incremental.  Set stall_max=2 for
        # the old, ~3x cheaper behaviour.
        if val < best and (best == np.inf or val < best * (1.0 - 1e-11)):
            best, v_best = val, v.copy()
            stalled = 0
        else:
            stalled += 1
        if not at_box and stalled >= stall_max:
            break
        if not at_box and best - lb <= tol * max(1.0, abs(best)):
            break
        if ww <= 1e-300:           # the norm term is inactive: no cut to add
            if not at_box:
                break
        else:
            side.add_cut(w / np.sqrt(ww))
        if at_box:                 # certificate wants more range (or the dual
            side.grow_box()        # is unbounded: admissible set empty)
            nbox += 1
            if nbox > box_max:
                return None, None, "empty_set"
    if v_best is None:
        return None, None, "no_solution"
    return best, v_best, "ok"


def min_chi_exact(E_s, C_s, Sigma_s, omega_grid, floor=None) -> float:
    """Exact  min_{z >= 0} || Sigma_s^{-1/2} (E_s z - C_s) ||  (nonnegative
    least squares; the admissible set is empty for chi below this value).
    Replaces the faceted lower bound of min_chi (which undershoots by up to
    ~12 % at n_facets=900)."""
    from scipy.optimize import nnls
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
    z, _ = nnls(L @ E_S, L @ c_data)
    return float(np.linalg.norm(L @ (E_S @ z - c_data)))


class solver:
    """Persistent positivity-band solver for a FIXED (E_s, Sigma_s, kernel).

    All the per-output LP models, their Kelley cuts and the data-independent
    recession-cone tests are built once and reused, so evaluating the band at
    another data vector (a jackknife resample, a chi scan) costs a
    changeColsCost plus a couple of warm-started simplex iterations.

        s = jks.positive_laplace.solver(E_s, Sigma_s, kernel, omega_grid)
        s.chi_min(C)                 -> exact NNLS tension of C
        s.bands(C, chi)              -> (lo, hi, M, info), see positivity_bounds
        s.nnls(C)                    -> (z*, chi_min), the maximum-likelihood
                                        positive spectrum on the grid

    Sigma_s enters only through its Cholesky factor, so the same object must
    not be reused across different input covariances."""

    def __init__(self, E_s, Sigma_s, kernel, omega_grid, floor=None,
                 tol=1e-9, maxit=200, stall_max=8):
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
            K = len(omega_grid)
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

        colmax = np.abs(E_S).max(0)                # sign-aware column equilibration
        rs = np.where(colmax > 0.0, 1.0 / np.maximum(colmax, 1e-300), 1.0)

        self.E_S, self.E_L, self.Lc, self.rs = E_S, E_L, Lc, rs
        self.E_eq = np.ascontiguousarray(E_S * rs[None, :])
        self.m, self.p = m, p
        self.tol, self.maxit, self.stall_max = tol, maxit, stall_max
        self._Li = None; self._Ew = None           # cached whitening
        self._sides = {}                           # (j, sign) -> _side
        self._cone = {}                            # j -> (ub_hi, ub_lo)
        self._knrm = {}                            # j -> (k thresholded, nrm)

    # ------------------------------------------------------------------ #
    def _kernel(self, j):
        if j not in self._knrm:
            k = self.E_L[j].copy()
            nrm = float(np.abs(k).max())
            if nrm > 0.0:
                k[np.abs(k) <= 1e-9 * nrm] = 0.0   # at the boundedness tolerance
            self._knrm[j] = (k, nrm)
        return self._knrm[j]

    def _side_of(self, j, sign, k, nrm):
        key = (j, sign)
        if key not in self._sides:
            self._sides[key] = _side(self.E_eq, sign * self.rs * k / nrm,
                                     self.Lc, 8.0 / nrm)   # v ~ O(1/nrm)
        return self._sides[key]

    def nnls(self, C):
        """(z*, chi_min) -- the Sigma-metric NNLS fit of C by a positive
        spectrum on the grid.  k.z* is the maximum-likelihood value of the
        output weight k and, unlike the band centre, does not move with chi."""
        from scipy.optimize import nnls as _nnls
        c = np.asarray(C, float).ravel()
        if c.shape[0] != self.m:
            raise ValueError("C must have m=%d entries, got %d" % (self.m, c.shape[0]))
        if self._Li is None:                       # whitening, built once
            self._Li = np.linalg.inv(self.Lc)
            self._Ew = np.ascontiguousarray(self._Li @ self.E_S)
        z, r = _nnls(self._Ew, self._Li @ c)
        return z, float(r)

    def chi_min(self, C):
        return self.nnls(C)[1]

    # ------------------------------------------------------------------ #
    def _one(self, j, c_data, chi):
        """One target weight: rigorous band without safety margins.
        Returns (hi_raw, lo_raw, M, status, viol_rel, n_cuts); raw values are
        +-inf on unbounded sides, None on unsolved sides; M is the midpoint
        slope (None unless fully solved)."""
        k, nrm = self._kernel(j)
        if nrm <= 0.0:                       # zero target weight
            return 0.0, 0.0, None, "zero_kernel", 0.0, 0
        if j not in self._cone:
            self._cone[j] = _cone_unbounded(self.E_eq, k * self.rs, 1e-9 * nrm)
        ub_hi, ub_lo = self._cone[j]
        if ub_hi is None or ub_lo is None:   # cone LP itself failed
            return None, None, None, "cone_lp_failed", np.nan, -1
        nc_h = nc_l = 0
        if ub_hi:
            hi_raw, st_h = np.inf, "unbounded"
        else:
            sh = self._side_of(j, +1, k, nrm)
            phi_h, v_h, st_h = _dual_bound_one(sh, c_data, float(chi), self.maxit,
                                               self.tol, stall_max=self.stall_max)
            nc_h = len(sh.cuts)
            hi_raw = nrm * phi_h if st_h == "ok" else None
        if ub_lo:
            lo_raw, st_l = -np.inf, "unbounded"
        else:
            sl = self._side_of(j, -1, k, nrm)
            phi_l, v_l, st_l = _dual_bound_one(sl, c_data, float(chi), self.maxit,
                                               self.tol, stall_max=self.stall_max)
            nc_l = len(sl.cuts)
            lo_raw = -nrm * phi_l if st_l == "ok" else None
        if ub_hi and ub_lo:
            return hi_raw, lo_raw, None, "unbounded", np.nan, nc_h + nc_l
        if ub_hi:
            return hi_raw, lo_raw, None, "unbounded_hi", np.nan, nc_h + nc_l
        if ub_lo:
            return hi_raw, lo_raw, None, "unbounded_lo", np.nan, nc_h + nc_l
        if st_h != "ok" or st_l != "ok":
            return hi_raw, lo_raw, None, (st_h if st_h != "ok" else st_l), np.nan, -1
        # certificate check in ORIGINAL units: u = nrm v must satisfy E^T u >= +/- k
        u_h = nrm * v_h
        u_l = nrm * v_l
        viol = max(float(np.maximum(0.0, k - self.E_S.T @ u_h).max()),
                   float(np.maximum(0.0, -k - self.E_S.T @ u_l).max()))
        M = 0.5 * nrm * (v_h - v_l)
        return hi_raw, lo_raw, M, "ok", viol / nrm, nc_h + nc_l

    def bands(self, C_vec, chi):
        """Exact admissible range of every target weight at the data vector
        C_vec; see positivity_bounds for the meaning of (lo, hi, M, info)."""
        c_data = np.asarray(C_vec, float).ravel()
        if c_data.shape[0] != self.m:
            raise ValueError("C must have m=%d entries, got %d"
                             % (self.m, c_data.shape[0]))
        if not np.isfinite(c_data).all():
            raise ValueError("C must be finite (got NaN/inf entries)")
        p = self.p
        lo = np.empty(p); hi = np.empty(p); M = np.empty((p, self.m))
        status = []; viols = []; ncuts = []
        cmargin = float(np.abs(c_data).sum()
                        + chi * np.sqrt(float((self.Lc ** 2).sum())))
        for j in range(p):
            hraw, lraw, Mj, st, viol, nc = self._one(j, c_data, chi)
            if st == "ok":
                margin = viol * cmargin      # one-sided safety on each endpoint
                hi[j] = hraw + margin
                lo[j] = lraw - margin
            else:                            # keep +-inf on the unbounded side
                hi[j] = hraw if hraw is not None else np.nan
                lo[j] = lraw if lraw is not None else np.nan
            M[j] = 0.0 if st == "zero_kernel" else (Mj if Mj is not None else np.nan)
            status.append(st); viols.append(viol); ncuts.append(nc)
        info = dict(status=status, violation_rel=viols, ncuts=ncuts, hints=self)
        return lo, hi, M, info


def positivity_bounds(E_s, C_s, Sigma_s, kernel, omega_grid, chi,
                      floor=None, tol=1e-9, maxit=200):
    """Exact admissible range of every target weight, plus the slope of the
    band midpoint.  Returns (lo, hi, M, info):

        lo[j], hi[j]   min/max of  kernel[j].z  over
                      { z >= 0 : (E_s z - C_s)^T Sigma_s^{-1} (E_s z - C_s) <= chi^2 }
                      (rigorous: each finite endpoint carries a one-sided safety
                      margin of  viol * (|C_s|_1 + chi*||Lc||_F);  an endpoint is
                      +-inf when kernel[j] is unbounded on the set, i.e. when the
                      recession cone {d >= 0 : E_s d = 0} carries kernel[j] --
                      see info['status'])
        M[j]           d (lo[j]+hi[j])/2 / d C_s   (m-vector; the statistical
                      propagation matrix, from the certificates, exact by the
                      envelope theorem;  nan for unbounded outputs)
        info           dict with per-output status / violation / cut counts
                      (status: ok, zero_kernel, unbounded_hi, unbounded_lo,
                      unbounded, or a solver failure string)

    E_s may have sign-changing entries; a grid node that no data weight sees
    (a zero column) carries invisible weight, which makes every kernel with a
    nonzero entry there unbounded -- reported, not capped.  Kernel entries
    below 1e-9 * max|kernel| are zeroed before solving (they are at the
    boundedness tolerance.  info["hints"] carries the live solver object for
    fast re-evaluation at other data points via band_center; for a chi scan or
    a full jackknife pass, build a `solver` once and call its bands() method
    directly."""
    s = solver(E_s, Sigma_s, kernel, omega_grid, floor=floor, tol=tol, maxit=maxit)
    c_data = np.asarray(C_s, float).ravel()
    if c_data.shape[0] != s.m:
        raise ValueError("C_s must have m=%d entries, got %d" % (s.m, c_data.shape[0]))
    return s.bands(c_data, chi)


def band_center(E_s, C_vec, Sigma_s, kernel, omega_grid, chi, hints=None,
                floor=None, tol=1e-9, maxit=200):
    """Center (lo+hi)/2 of every admissible band at data point C_vec.

    The same problem as positivity_bounds evaluated at a DIFFERENT data vector
    (e.g. a jackknife resample), returning only the centers.  Pass the solver
    from info["hints"] of the main positivity_bounds call to make each
    re-evaluation a couple of warm-started LP solves.

    Returns (m, ok, hints):  m[j] = band center (nan where the band does not
    exist at C_vec, e.g. chi below chi_min(C_vec), or the solver failed);
    ok = per-output success mask; hints = the solver, for the next call.
    Centers are margin-free (the safety margins cancel in (lo+hi)/2)."""
    s = hints if isinstance(hints, solver) else solver(
        E_s, Sigma_s, kernel, omega_grid, floor=floor, tol=tol, maxit=maxit)
    lo, hi, M, info = s.bands(C_vec, chi)
    ok = np.array([st in ("ok", "zero_kernel") for st in info["status"]], bool)
    mm = np.where(ok, 0.5 * (lo + hi), np.nan)
    return mm, ok, s
