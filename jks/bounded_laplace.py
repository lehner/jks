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

__all__ = ["solver"]


# --------------------------------------------------------------------------- #
# exact bounds under a box prior by column generation.
#
# This generalizes jks.positive_laplace from  z >= 0  to  lower <= z <= upper;
# with the defaults lower = 0, upper = inf it reproduces jks.positive_laplace
# bit for bit (same faces, same floating-point operations).
#
# For each target weight k(omega) the admissible range
#     [ lo_k, hi_k ] = range of  k.z   over
#     { l <= z <= u : || A z - a || <= chi },     A = Lc^-1 E_S,  a = Lc^-1 C_s
# (Lc: Sigma_s = Lc Lc^T) is computed EXACTLY on the grid.  l is finite, u may
# be +inf node by node; l = 0, u = inf is the positivity problem.
#
# With z = l + x the box becomes 0 <= x <= c (c = u - l), the data a' = a - A l
# and the value shifts by k.l.  An optimum of  max s*k.x  has a free set T
# (|T| <= m, A_T of full rank), a set U of nodes at their upper bound, and all
# other nodes at 0.  The nodes in U only shift the data,
#     a_U = a' - A_U c_U,
# so the free part is the closed form of the positivity solver on a_U: with
# A_T = QR, z0 = R^-1 Q^T a_U, rho^2 = chi^2 - |a_U - Q Q^T a_U|^2,
#
#     x_T   = z0 + rho R^-1 y / |y|,   y = R^-T (s k_T),
#     w     = (|y| / rho) (A_T x_T - a_U)            (whitened dual)
#
# and it is the optimum iff 0 <= x_T <= c_T and the reduced cost
# r = s k - A^T w is <= 0 at nodes at 0 and >= 0 at nodes in U (KKT).  For ANY
# w with r <= 0 on the nodes with c = inf,
#     s k.x  <=  a'.w + chi |w| + sum_{c_j < inf} max(r_j, 0) c_j,
# so the dual value is a certificate.  It is evaluated with r = 0 on the free
# nodes and r <= 0 on the nodes at 0, i.e. only the nodes in U contribute to
# the sum: KKT holds there to rounding / vtol, the same tolerance as in
# jks.positive_laplace, and the sum over all finite nodes would multiply that
# rounding by c (an O(1) widening for c ~ 1e9 was seen).  As there, the KKT
# test is per node at the rounding level of r_j,  |r_j| <= vtol (|k_j| +
# |A_j| |w|) on the wrong side, which does not depend on the column scaling.
#
# _colgen solves exactly on a small candidate set S of free nodes (every face
# of S and every lower/upper split of the rest of S, largest faces first),
# nodes outside S held at their current bound, then adds the most violated
# node (at 0 with r > 0, or in U with r < 0) and repeats.  The previous
# optimum (T, U) of the same (output, side) is first tried as a single face
# (KKT on the whole grid is sufficient), so a new data vector (a jackknife
# resample) typically costs one closed form.  Otherwise it starts from the
# bounded-least-squares solution (_bvls, an exact active-set method started
# from the NNLS solution): its interior nodes as S -- reduced to a full-rank
# set of at most m nodes without moving A x (_reduce), since every node of S
# can also sit at a bound (3^|S| splits) -- and its nodes at u as U.  Without
# finite upper bounds the previous free set is added to S as in
# jks.positive_laplace.  The least-squares point is admissible for every such
# start, so the restricted problem is never empty.
#
# For u = inf nodes and GENERAL data weights the admissible set can be
# unbounded: its recession cone is { d >= 0 on the u = inf nodes, d = 0 on the
# others : E_S d = 0 }.  A target weight is bounded iff k.d = 0 along every
# cone direction -- one small LP per side (_cone_unbounded) on the u = inf
# columns only, skipped when some data row is of one strict sign there (e.g.
# any Laplace weight) or when every node has a finite upper bound.

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


def _shifted(A, a, c, U):
    """a_U = a - A_U c_U (a itself for empty U)."""
    if not U:
        return a
    Ul = sorted(U)
    return a - A[:, Ul] @ c[Ul]


def _face_setup(A, a, aa, chi, T):
    """The ks-independent part of _face: (A_T, column norms, R, rho, z0), or
    None if the face is rank deficient or cannot reach the chi ball."""
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
    return AT, cn, R, np.sqrt(rho2), np.linalg.solve(R, qa)


def _face(A, a, aa, chi, ks, T, fc, key):
    """Closed-form optimum of  max ks.x  s.t. ||A x - a|| <= chi  with x
    supported on T (sign of x_T not imposed); a is already shifted by the
    nodes at their upper bound, `key` identifies that shift.  Returns
    (x_T, w) or None if the face is rank deficient or cannot reach the chi
    ball.  `fc` caches _face_setup per (T, key); it is valid for one
    (a, chi) only and is shared by all target weights and both sides, which
    revisit the same few supports."""
    if not T:                                      # x_T empty, if admissible
        return (np.zeros(0), np.zeros(A.shape[0])) if aa <= chi * chi else None
    k = (tuple(T), key)
    if k not in fc:
        fc[k] = _face_setup(A, a, aa, chi, T)
    f = fc[k]
    if f is None:
        return None
    AT, cn, R, rho, z0 = f
    y = np.linalg.solve(R.T, ks[T] / cn)
    ny = np.linalg.norm(y)
    if ny == 0.0:
        return None
    zT = (z0 + np.linalg.solve(R, y) * (rho / ny)) / cn
    return zT, (ny / rho) * (AT @ zT - a)


def _bvls(A, a, c, x0, frozen, maxit=1000):
    """min ||A x - a|| over 0 <= x <= c by the Stark-Parker active-set method,
    started from the admissible x0 (the clipped NNLS solution).  A should be
    column-equilibrated; nodes in `frozen` stay at 0.  Optimality is the KKT
    sign pattern of the gradient g = A^T (a - A x): g <= 0 at 0, g >= 0 at c."""
    K = A.shape[1]
    x = x0.copy()
    x[frozen] = 0.0
    fin = c < np.inf
    atU = fin & (x >= c)
    x[atU] = c[atU]
    F = (x > 0.0) & ~atU
    lock = np.zeros(K, bool); lock[frozen] = True
    tol = 1e-13 * max(np.linalg.norm(a), 1e-300)
    for it in range(maxit):
        # inner loop: least squares on F with the rest held, stepping back to
        # the box whenever the unconstrained solution leaves it
        for inner in range(K + 1):
            if not F.any():
                break
            fixed = ~F
            zF = np.linalg.lstsq(A[:, F], a - A[:, fixed] @ x[fixed], rcond=None)[0]
            xF, cF = x[F], c[F]
            if ((zF > 0.0) & (zF < cF)).all():
                x[F] = zF
                break
            d = zF - xF
            with np.errstate(divide="ignore", invalid="ignore"):
                t = np.where(d < 0, -xF / d, np.where(d > 0, (cF - xF) / d, np.inf))
            alpha = min(1.0, float(np.clip(t, 0.0, None).min()))
            xn = np.clip(xF + alpha * d, 0.0, cF)
            hit = (xn <= 0.0) | (xn >= cF) | (np.clip(t, 0.0, None) <= alpha)
            xn[hit & (xn <= 0.5 * cF)] = 0.0
            xn[hit & (xn > 0.5 * cF)] = cF[hit & (xn > 0.5 * cF)]
            x[F] = xn
            idx = np.flatnonzero(F)
            F[idx[hit]] = False
        g = A.T @ (a - A @ x)
        atU = fin & (x >= c) & ~F
        cand = np.where(~F & ~atU & ~lock, g, -np.inf)          # at 0, wants to grow
        cand = np.maximum(cand, np.where(atU & ~lock, -g, -np.inf))  # at c, wants to shrink
        j = int(np.argmax(cand))
        if cand[j] <= tol:
            return x
        F[j] = True
    return x


def _reduce(A, x, c, F):
    """Caratheodory reduction of an admissible point: while the interior
    columns A_F are rank deficient, move x_F along a null vector of A_F until
    a node reaches a bound (A x does not change).  Returns (x, F) with A_F of
    full column rank, |F| <= m -- a small start set for _colgen."""
    x = x.copy(); F = list(F)
    while F:
        AF = A[:, F]
        cn = np.linalg.norm(AF, axis=0)
        _, sv, Vt = np.linalg.svd(AF / cn)
        if len(F) <= len(sv) and sv[-1] > 1e-11 * sv[0]:
            break
        d = Vt[-1] / cn                            # A_F d ~ 0
        xF, cF = x[F], c[F]
        with np.errstate(divide="ignore", invalid="ignore"):
            up = np.where(d > 0, (cF - xF) / d, np.where(d < 0, -xF / d, np.inf))
            dn = np.where(d < 0, (cF - xF) / d, np.where(d > 0, -xF / d, -np.inf))
        i_up, i_dn = int(np.argmin(up)), int(np.argmax(dn))
        t, i = (up[i_up], i_up) if up[i_up] <= -dn[i_dn] else (dn[i_dn], i_dn)
        x[F] = np.clip(xF + t * d, 0.0, cF)
        j = F.pop(i)
        x[j] = cF[i] if x[j] > 0.5 * cF[i] else 0.0    # the node that hit its bound
    return x, F


def _splits(n):
    """All subsets of range(n), fewest elements first (empty first)."""
    for size in range(n + 1):
        yield from combinations(range(n), size)


def _restricted(A, a, chi, ks, S, U_out, c, vtol, fc, cnA):
    """Exact optimum of the problem restricted to 0 <= x_S <= c_S, nodes
    outside S at 0 or (U_out) at c: the first face T of S (largest first) and
    lower/upper split of S \\ T that satisfies the KKT conditions on S.
    Returns (T, U, x_T, w) with U the full set of nodes at c, or None."""
    m = A.shape[0]
    AS = A[:, S]
    fin = [i for i in range(len(S)) if c[S[i]] < np.inf]
    for size in range(min(len(S), m), -1, -1):
        for T in combinations(range(len(S)), size):
            Ts = set(T)
            rest = [i for i in fin if i not in Ts]
            for up in _splits(len(rest)):
                Ui = [rest[i] for i in up]
                U = U_out | {S[i] for i in Ui}
                key = tuple(sorted(U))
                aU = _shifted(A, a, c, U)
                r = _face(A, aU, float(aU @ aU), chi, ks, [S[i] for i in T], fc, key)
                if r is None or (size and r[0].min() < 0.0):
                    continue
                if size and (r[0] > c[[S[i] for i in T]]).any():
                    continue
                viol = ks[S] - AS.T @ r[1]
                viol[list(T)] = 0.0
                viol[Ui] = -viol[Ui]               # nodes at c need r >= 0
                if (viol <= vtol * (np.abs(ks[S]) + cnA[S] * np.linalg.norm(r[1]))).all():  # S may be empty
                    return [S[i] for i in T], U, r[0], r[1]
    return None


def _relviol(viol, tol):
    """viol / tol per node (tol = 0: 0 if viol <= 0, else inf)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(tol > 0.0, viol / np.where(tol > 0.0, tol, 1.0), np.where(viol > 0.0, np.inf, 0.0))


def _most_violated(A, ks, T, U, w, frozen, vtol, cnA):
    """(node, violation / tolerance) of the KKT condition over the whole grid:
    r > 0 at a node at 0, r < 0 at a node in U, r = ks - A^T w; the
    tolerance is the rounding level of r_j, vtol (|ks_j| + |A_j| |w|)."""
    viol = ks - A.T @ w
    if U:
        Ul = list(U)
        viol[Ul] = -viol[Ul]
    viol[T] = 0.0
    viol[frozen] = 0.0
    rel = _relviol(viol, vtol * (np.abs(ks) + cnA * np.linalg.norm(w)))
    jn = int(np.argmax(rel))
    return jn, rel[jn]


def _colgen(A, a, chi, ks, S0, U0, c, vtol, frozen, fc, cnA, prev=None, maxit=200):
    """Column generation for  max ks.x  s.t. 0 <= x <= c, ||A x - a|| <= chi.
    `frozen` are the nodes never priced in: grid nodes no data weight sees
    (zero columns of A) and nodes with c = 0.  The recession-cone test has
    already decided that the kernel vanishes at the unseen c = inf nodes; the
    unseen finite nodes are placed at their optimal bound by the caller.
    `prev` = (T, U) of an earlier optimum is tried first as a single face:
    KKT on the whole grid is sufficient, so if it holds that face is the
    optimum.  `fc`: face cache (_face).  Returns (T, U, x_T, w) or None."""
    if prev is not None:
        T, U = prev
        aU = _shifted(A, a, c, U)
        r = _face(A, aU, float(aU @ aU), chi, ks, T, fc, tuple(sorted(U)))
        if r is not None and not (T and (r[0].min() < 0.0 or (r[0] > c[T]).any())):
            if _most_violated(A, ks, T, U, r[1], frozen, vtol, cnA)[1] <= 1.0:
                return list(T), set(U), r[0], r[1]
    S = list(dict.fromkeys(int(i) for i in S0))
    U_out = set(U0) - set(S)
    for it in range(maxit):
        r = _restricted(A, a, chi, ks, S, U_out, c, vtol, fc, cnA)
        if r is None:
            return None
        T, U, xT, w = r
        jn, v = _most_violated(A, ks, T, U, w, frozen, vtol, cnA)
        if v <= 1.0:                               # dual feasible: optimal
            return r
        S = T + [jn]
        U_out = U - {jn}
    return None


class solver:
    """Persistent band solver under a box prior  lower <= z <= upper  for a
    FIXED (E_s, Sigma_s, kernel, lower, upper).

    The whitening, the recession-cone tests and the last optimal free set of
    every (output, side) are kept, so evaluating the band at another data
    vector (a jackknife resample, a chi scan) is typically one closed-form
    solve per endpoint.  The results do not depend on this history.

        s = solver(E_s, Sigma_s, kernel, omega_grid, lower=None, upper=None)
        s.chi_min(C)                 -> exact bounded-least-squares tension of C
        s.bands(C, chi)              -> (lo, hi, M, info)
        s.nnls(C)                    -> (z*, chi_min), the maximum-likelihood
                                        spectrum in the box on the grid

    lower (default 0) must be finite, upper (default +inf) may be +inf per
    node, lower <= upper; a node with lower == upper is fixed.  E_s may have
    sign-changing entries; a grid node that no data weight sees (a zero
    column) carries invisible weight, which makes every kernel with a nonzero
    entry there unbounded if the node has no finite upper bound -- reported,
    not capped.  Sigma_s enters only through its Cholesky factor, so the same
    object must not be reused across different input covariances."""

    def __init__(self, E_s, Sigma_s, kernel, omega_grid, vtol=1e-10, lower=None, upper=None):
        K = len(omega_grid)
        E_S, E_L = np.asarray(E_s, float), np.asarray(kernel, float)
        if E_S.ndim != 2 or E_L.ndim != 2 or E_S.shape[1] != K or E_L.shape[1] != K:
            raise ValueError(
                "E_s (m, K) and kernel (p, K) must be 2-D with K=%d columns (one per "
                "omega_grid node); got shapes %s and %s" % (K, E_S.shape, E_L.shape))
        if not (np.isfinite(E_S).all() and np.isfinite(E_L).all()):
            raise ValueError("E_s and kernel must be finite (got NaN/inf entries)")
        l = np.zeros(K) if lower is None else np.array(lower, float).ravel()
        u = np.full(K, np.inf) if upper is None else np.array(upper, float).ravel()
        if l.shape != (K,) or u.shape != (K,):
            raise ValueError("lower and upper must have K=%d entries" % K)
        if not np.isfinite(l).all():
            raise ValueError("lower must be finite")
        if np.isnan(u).any() or (u < l).any():
            raise ValueError("upper must be >= lower (and not NaN)")
        m, p = E_S.shape[0], E_L.shape[0]
        Sig = np.asarray(Sigma_s, float)
        Sig = 0.5 * (Sig + Sig.T)
        if Sig.shape != (m, m):
            raise ValueError("Sigma_s must be (%d, %d)" % (m, m))
        try:
            Lc = np.linalg.cholesky(Sig)
        except np.linalg.LinAlgError:
            Lc = np.linalg.cholesky(Sig + 1e-12 * np.trace(Sig) / m * np.eye(m))

        self.E_S, self.E_L = E_S, E_L
        self.lower, self.upper = l, u
        self.c = u - l                             # box width in x = z - lower
        self._l0 = not l.any()                     # plain lower = 0
        self.Li = np.linalg.inv(Lc)
        self.A = self.Li @ E_S                     # whitened data weights
        self.m, self.p = m, p
        self.nrm = np.abs(E_L).max(1)
        unseen = np.abs(E_S).max(0) == 0.0
        inf = self.c == np.inf
        self.dead = np.flatnonzero(unseen)         # invisible nodes
        self.frozen = np.flatnonzero(unseen | (self.c == 0.0))
        self._unseen_fin = np.flatnonzero(unseen & ~inf & (self.c > 0.0))
        self.vtol = vtol                           # dual violation / (|k_j| + |A_j| |w|)
        self.cnA = np.linalg.norm(self.A, axis=0)  # |A_j|
        self._supp = {}                            # (j, sign) -> last free set
        self._last = (None, None)                  # (C bytes, nnls result)

        # recession-cone tests (data independent) on the u = inf nodes only,
        # skipped when trivially bounded
        self._cone = {}
        Ei = E_S[:, inf]
        if inf.any() and not ((Ei > 0).all(1) | (Ei < 0).all(1)).any():
            colmax = np.abs(Ei).max(0)
            rs = np.where(colmax > 0.0, 1.0 / np.maximum(colmax, 1e-300), 1.0)
            E_eq = np.ascontiguousarray(Ei * rs[None, :])
            for j in range(p):
                if self.nrm[j] > 0.0:
                    self._cone[j] = _cone_unbounded(E_eq, E_L[j][inf] * rs, 1e-9 * self.nrm[j])

    # ------------------------------------------------------------------ #
    def _a(self, c):
        """whitened data in x = z - lower coordinates"""
        a = self.Li @ c
        return a if self._l0 else a - self.A @ self.lower

    def _ls(self, a):
        """(x*, chi_min) of  min ||A x - a||  over the box 0 <= x <= c."""
        if np.isinf(self.c).all():
            z, r = _nnls(self.A, a)
            return z, float(r)
        # the NNLS optimum is exact; if it fits in the box it is the optimum
        z, r = _nnls(self.A, a)
        if (z <= self.c).all():
            return z, float(r)
        cn = np.linalg.norm(self.A, axis=0)        # equilibrated columns
        cn[cn == 0.0] = 1.0
        xe = _bvls(self.A / cn, a, self.c * cn, np.minimum(z, self.c) * cn, self.frozen)
        x = np.clip(xe / cn, 0.0, self.c)           # rounding of the unit change
        return x, float(np.linalg.norm(self.A @ x - a))

    def nnls(self, C):
        """(z*, chi_min) -- the Sigma-metric bounded least-squares fit of C by
        a spectrum in the box on the grid.  k.z* is the maximum-likelihood
        value of the output weight k and, unlike the band centre, does not
        move with chi."""
        c = np.asarray(C, float).ravel()
        if c.shape[0] != self.m:
            raise ValueError("C must have m=%d entries, got %d" % (self.m, c.shape[0]))
        key = c.tobytes()
        if self._last[0] != key:
            self._last = (key, self._ls(self._a(c)))
        x, r = self._last[1]
        return (x.copy() if self._l0 else self.lower + x), r

    def chi_min(self, C):
        return self.nnls(C)[1]

    # ------------------------------------------------------------------ #
    def _one(self, j, a, chi, S_ml, U_ml, fc):
        """One target weight: exact band.  Returns (hi, lo, M, dcdchi, status,
        gap_rel); hi/lo are +-inf on unbounded sides, nan on failed sides; M
        and dcdchi are None unless both sides are solved."""
        nrm = self.nrm[j]
        if nrm <= 0.0:                             # zero target weight
            return 0.0, 0.0, np.zeros(self.m), 0.0, "zero_kernel", 0.0
        ub_hi, ub_lo = self._cone.get(j, (False, False))
        if ub_hi is None or ub_lo is None:         # cone LP itself failed
            return np.nan, np.nan, None, None, "cone_lp_failed", np.nan
        if ub_hi or ub_lo:
            st = "unbounded" if ub_hi and ub_lo else (
                "unbounded_hi" if ub_hi else "unbounded_lo")
            return (np.inf if ub_hi else np.nan), (-np.inf if ub_lo else np.nan), \
                None, None, st, np.nan
        c = self.c
        fin = c < np.inf
        out, w, gap = {+1: np.nan, -1: np.nan}, {}, 0.0
        for sg in (+1, -1):
            ks = sg * self.E_L[j]
            # unseen nodes with a finite box sit at the bound that maximizes ks
            U0 = U_ml | {int(i) for i in self._unseen_fin if ks[i] > 0.0}
            prev = self._supp.get((j, sg))
            # with a finite box every node of S0 can also sit at its bound
            # (3^|S0| splits), so the earlier free set is only tried as a
            # face (prev) and not added to the start set
            S0 = S_ml if fin.any() or prev is None else list(prev[0]) + S_ml
            r = _colgen(self.A, a, chi, ks, S0, U0, c, self.vtol, self.frozen, fc, self.cnA, prev)
            if r is None:
                continue
            T, U, xT, w[sg] = r
            self._supp[(j, sg)] = (T, U)
            prim = float(ks[T] @ xT)                              # at an admissible z
            dual = float(a @ w[sg] + chi * np.linalg.norm(w[sg]))  # at a certificate
            if U:
                # nodes at their upper bound: primal c_j ks_j, and the dual
                # term max(r_j, 0) c_j of the certificate.  At free nodes r = 0
                # and at nodes at 0 r <= 0 up to rounding / vtol (as in
                # jks.positive_laplace); adding max(r, 0) c there would turn
                # that rounding into an O(c) widening for a large finite c.
                Ul = sorted(U)
                prim += float(ks[Ul] @ c[Ul])
                rc = ks[Ul] - self.A[:, Ul].T @ w[sg]
                dual += float(np.maximum(rc, 0.0) @ c[Ul])
            if not self._l0:
                off = float(ks @ self.lower)
                prim += off; dual += off
            out[sg] = sg * max(prim, dual)                        # the outer of the two
            scale = max(abs(dual), abs(prim))
            gap = max(gap, abs(dual - prim) / scale if scale > 0.0 else 0.0)
        if len(w) < 2:
            return out[+1], out[-1], None, None, "colgen_failed", np.nan
        # envelope theorem: d hi/dC = Li^T w_hi, d lo/dC = -Li^T w_lo,
        #                   d hi/dchi = |w_hi|,  d lo/dchi = -|w_lo|
        M = 0.5 * (self.Li.T @ (w[+1] - w[-1]))
        dcdchi = 0.5 * (np.linalg.norm(w[+1]) - np.linalg.norm(w[-1]))
        return out[+1], out[-1], M, dcdchi, "ok", gap

    def bands(self, C_vec, chi):
        """Exact admissible range of every target weight at the data vector
        C_vec.  Returns (lo, hi, M, info):

            lo[j], hi[j]   min/max of  kernel[j].z  over
                          { lower <= z <= upper :
                            (E_s z - C)^T Sigma_s^{-1} (E_s z - C) <= chi^2 }
                          (each finite endpoint is the outer of a primal value at
                          an admissible z and a dual value at a certificate,
                          which agree to info['gap_rel'];  +-inf when kernel[j]
                          is unbounded on the set)
            M[j]           d (lo[j]+hi[j])/2 / d C  at FIXED chi (m-vector, exact
                          by the envelope theorem; nan unless status is ok)
            info           dict with per-output
                             status        ok, zero_kernel, unbounded_hi,
                                           unbounded_lo, unbounded, empty_set
                                           (chi <= chi_min), or a failure string
                             gap_rel       |dual - primal| / |endpoint|
                             dcenter_dchi  d (lo[j]+hi[j])/2 / d chi  at fixed C"""
        c_data = np.asarray(C_vec, float).ravel()
        if c_data.shape[0] != self.m:
            raise ValueError("C must have m=%d entries, got %d"
                             % (self.m, c_data.shape[0]))
        if not np.isfinite(c_data).all():
            raise ValueError("C must be finite (got NaN/inf entries)")
        chi = float(chi)
        a = self._a(c_data)
        z_ml, chi_min = self.nnls(c_data)
        x_ml = z_ml if self._l0 else z_ml - self.lower
        if chi > chi_min:
            if np.isfinite(self.c).any():          # BVLS interior sets can exceed m
                F = [int(i) for i in np.flatnonzero((x_ml > 0.0) & (x_ml < self.c))
                     if i not in set(self.frozen)]
                x_ml, _ = _reduce(self.A, x_ml, self.c, F)
            S_ml = [int(i) for i in np.flatnonzero((x_ml > 0.0) & (x_ml < self.c))]
            U_ml = {int(i) for i in np.flatnonzero((self.c < np.inf) & (self.c > 0.0) & (x_ml >= self.c))}
            U_ml -= set(int(i) for i in self.frozen)
        else:
            S_ml = U_ml = None
        p = self.p
        lo = np.empty(p); hi = np.empty(p); M = np.full((p, self.m), np.nan)
        dcdchi = np.full(p, np.nan)
        status = []; gaps = []
        fc = {}                                    # face cache for this (a, chi)
        for j in range(p):
            if S_ml is None and self.nrm[j] > 0.0:  # chi <= chi_min: no admissible z
                hi[j] = lo[j] = np.nan
                status.append("empty_set"); gaps.append(np.nan)
                continue
            hi[j], lo[j], Mj, dj, st, g = self._one(j, a, chi, S_ml, U_ml, fc)
            if Mj is not None:
                M[j] = Mj; dcdchi[j] = dj
            status.append(st); gaps.append(g)
        return lo, hi, M, dict(status=status, gap_rel=gaps, dcenter_dchi=dcdchi)
