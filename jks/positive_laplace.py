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

import functools
import warnings
from typing import Optional, Tuple

import numpy as np
import highspy

__all__ = [
    "sample_admissible",
    "min_chi",
]

_INF = highspy.kHighsInf
_OPTIMAL = highspy.HighsModelStatus.kOptimal
_INFEASIBLE = highspy.HighsModelStatus.kInfeasible
_UNBOUNDED = highspy.HighsModelStatus.kUnbounded


# --------------------------------------------------------------------------- #
# response kernels
# --------------------------------------------------------------------------- #
def _is_veronese4(E_S: np.ndarray, rtol=1e-8, atol=1e-14) -> bool:
    """True iff E_S (4 x K) columns lie on the curve (x, x^2, x^3, x^4)."""
    if E_S.shape[0] != 4:
        return False
    r0 = E_S[0]
    return (np.allclose(E_S[1], r0 ** 2, rtol, atol)
            and np.allclose(E_S[2], r0 ** 3, rtol, atol)
            and np.allclose(E_S[3], r0 ** 4, rtol, atol))


# --------------------------------------------------------------------------- #
# persistent HiGHS models
# --------------------------------------------------------------------------- #
class _HiGHS:
    """Persistent model  min cost^T x  s.t.  A_ub x <= b_ub,  A_eq x = b_eq,
    lo <= x <= up.  Constraints are fixed at build time; re-solve by cost only.
    (For per-step changing constraints see _Chord.)"""

    def __init__(self, n, lo, up, A_ub=None, b_ub=None, A_eq=None, b_eq=None):
        self.h = highspy.Highs()
        self.h.silent()
        self.h.setOptionValue("threads", 1)
        self.n = int(n)
        self.I32 = np.arange(self.n, dtype=np.int32)
        self.status = None
        for i in range(self.n):
            self.h.addVariable(float(lo[i]), float(up[i]), 0.0)
        if A_ub is not None:
            for i in range(A_ub.shape[0]):
                self.h.addRow(-_INF, float(b_ub[i]), self.n, self.I32,
                              np.ascontiguousarray(A_ub[i], np.float64))
        if A_eq is not None:
            for i in range(A_eq.shape[0]):
                self.h.addRow(float(b_eq[i]), float(b_eq[i]), self.n, self.I32,
                              np.ascontiguousarray(A_eq[i], np.float64))

    def solve(self, cost) -> Optional[np.ndarray]:
        self.h.changeColsCost(self.n, self.I32, np.ascontiguousarray(cost, np.float64))
        self.h.minimize()
        self.h.run()
        self.status = self.h.getModelStatus()   # kept: callers need to tell
        if self.status != _OPTIMAL:             # infeasible from unbounded
            return None
        return np.asarray(self.h.getSolution().col_value, np.float64)

    def objective(self, cost) -> Optional[float]:
        x = self.solve(cost)
        return None if x is None else float(x @ cost)


class _Chord:
    """Persistent model for the image-chord LP pair  (variables (z, t)):

        min/max  t    s.t.    E_S z - t w = c,   0 <= z <= W,   1^T z <= W.

    Per step only the equality RHS (c) and the t-column coefficients (w) change
    in place; ~0.15 ms for a chord pair."""

    def __init__(self, E_S: np.ndarray, W: float):
        m, K = E_S.shape
        self.h = highspy.Highs()
        self.h.silent()
        self.h.setOptionValue("threads", 1)
        self.I32 = np.arange(K, dtype=np.int32)
        R_t = 10.0 * W + 100.0                       # chord |t| is O(W); bound keeps HiGHS happy
        for i in range(K):
            self.h.addVariable(0.0, float(W), 0.0)
        self.tcol = int(self.h.addVariable(-R_t, R_t, 0.0))
        self.rows = list(range(m))
        idx = np.concatenate([self.I32, [self.tcol]])
        for i in range(m):
            self.h.addRow(0.0, 0.0, len(idx), idx,
                          np.concatenate([E_S[i].astype(np.float64), [-1.0]]))
        self.h.addRow(-_INF, float(W), K, self.I32, np.ones(K))

    def chord(self, c, w):
        h = self.h
        for i, r in enumerate(self.rows):
            h.changeRowBounds(r, float(c[i]), float(c[i]))
            h.changeCoeff(r, self.tcol, -float(w[i]))
        out = []
        for sgn in (1.0, -1.0):                 # min t , then min -t
            h.changeColCost(self.tcol, sgn)
            h.run()
            if h.getModelStatus() != _OPTIMAL:
                return None, None
            out.append(float(np.asarray(h.getSolution().col_value, np.float64)[self.tcol]))
        return out[0], out[1]


def _lp_failure(what: str, status, chi: float, G=None, omega_grid=None) -> str:
    """Message for an LP that did not reach optimality.  Infeasible really does
    mean the data admit no positive spectrum at this chi, so "increase chi" is
    the right advice; unbounded is a different illness and the opposite advice
    applies -- see below."""
    if status == _INFEASIBLE:
        return "%s: admissible set infeasible -- increase chi (chi=%.2f)" % (what, chi)
    if status == _UNBOUNDED and G is not None:
        # Every grid node is bounded only through the response columns.  Once
        # exp(-t*omega) underflows past the LP zero tolerance those columns read
        # as structurally zero, weight parked there is free, and max 1^T z does
        # not exist.  A larger chi widens the set and makes this worse.
        col = np.abs(np.asarray(G, float)).max(0)
        top = float(col.max())
        dead = col <= 1e-9 * top if top > 0.0 else np.ones(len(col), bool)
        w0 = float(np.asarray(omega_grid, float)[dead][0]) if dead.any() else None
        return ("%s: unbounded -- the omega grid runs past the numerical support "
                "of the response kernel%s.  The scaled response columns span "
                "%.1e .. %.1e across the grid, so the far nodes are invisible to "
                "the LP and carry free weight.  Shorten omega_grid or lower the "
                "largest data weight; raising chi (chi=%.2f) does not help."
                % (what, "" if w0 is None else " (from omega=%.3g on)" % w0,
                   top, float(col.min()), chi))
    return "%s: LP did not solve (HiGHS status %s, chi=%.2f)" % (
        what, str(status).rsplit(".", 1)[-1], chi)

# --------------------------------------------------------------------------- #
# ellipsoid faceting  (polyhedral outer approximation of the SOCP constraint)
# --------------------------------------------------------------------------- #
def _whiten(Sigma_s: np.ndarray) -> np.ndarray:
    """L_w with  L_w^T L_w = Sigma^{-1},  so that  ||L_w r||^2  is the Mahalanobis
    norm  r^T Sigma^{-1} r.

    The ORDER matters.  Both inv(chol(Sigma)) and its transpose are square roots
    of Sigma^{-1}, but of the two products: with  Sigma = L L^T,
        inv(L)^T inv(L) = (L L^T)^{-1} = Sigma^{-1}      <- what we need
        inv(L)   inv(L)^T = (L^T L)^{-1} != Sigma^{-1}   unless Sigma is diagonal
    Both the facet rows  u^T L_w (c - c_data) <= chi  (whose sup over unit u is
    ||L_w (c - c_data)||) and the exact ray clip use the first form, so L_w is
    inv(chol(Sigma)) and NOT its transpose."""
    m = Sigma_s.shape[0]
    return np.linalg.inv(np.linalg.cholesky(Sigma_s + 1e-15 * np.eye(m)))


def _sphere_facets(m: int, n_facets: int, seed: int) -> np.ndarray:
    """Unit directions u_i on S^{m-1} (axes + seeded random)."""
    rng = np.random.default_rng(seed)
    dirs = [np.eye(m)[i] for i in range(m)] + [np.eye(m)[i] * -1 for i in range(m)]
    R = rng.standard_normal((n_facets, m))
    dirs += list(R / np.linalg.norm(R, axis=1, keepdims=True))
    U = np.array(dirs)
    return U / np.linalg.norm(U, axis=1, keepdims=True)


def _ellipsoid_facets(c_data, Sigma_s, E_S, chi, n_facets, seed):
    """Rows (G, b) with  { z : G z <= b }  the facet outer-approximation of
    ||L (E_S z - c_data)||_2 <= chi.  Also returns the c-space rows (Ac_e, bc_e)."""
    m = len(c_data)
    L_Sigma = _whiten(Sigma_s)
    U = _sphere_facets(m, n_facets, seed)
    G = U @ L_Sigma @ E_S
    b = chi + U @ (L_Sigma @ c_data)
    Ac_e = U @ L_Sigma
    bc_e = chi + Ac_e @ c_data
    return G, b, Ac_e, bc_e


# --------------------------------------------------------------------------- #
# the image body  I = conv{0, W * cols(E_S)}  --  half-space description
# --------------------------------------------------------------------------- #
def _cross3_vec(U, Vv, Ww):
    """Vectorised 4-d cross product: (4,N) each -> (4,N);  a.x = det[x,u,v,w]."""
    M = np.stack([U, Vv, Ww], axis=1)                       # (4, 3, N)
    a = np.empty((4, M.shape[2]))
    for i in range(4):
        Mi = np.delete(M, i, axis=0)                        # (3, 3, N)
        A, B, C = Mi[:, 0, :], Mi[:, 1, :], Mi[:, 2, :]
        det = A[0] * (B[1] * C[2] - B[2] * C[1]) \
            - A[1] * (B[0] * C[2] - B[2] * C[0]) \
            + A[2] * (B[0] * C[1] - B[1] * C[0])
        a[i] = det if i % 2 == 0 else -det
    return a


@functools.lru_cache(maxsize=8)
def _curve_facets(E_S_key):
    """Facet half-spaces of  conv{0, cols(E_S)}  for a Veronese (4-d) response.

    The facets of this curve polytope are unions of consecutive index runs
    (verified exhaustively for small K); we generate the run-pattern candidates
    (~O(K^3), not C(K,4)), keep those passing a same-side test against every
    vertex (incl. the apex), and orient each so the containing side includes the
    apex.  Returns a list of (a_unit (4,), ref_index_or_None)."""
    V = np.asarray(E_S_key, float).reshape(4, -1)
    K = V.shape[1]
    tol = 1e-8
    i4 = np.arange(K)

    cands4 = [np.stack([i4, i4 + 1, i4 + 2, i4 + 3], axis=1) % K]
    ii, off = np.meshgrid(i4, np.arange(3, K - 1), indexing="ij")
    cands4.append((np.stack([ii, ii + 1, ii + 2, ii + off], axis=-1) % K).reshape(-1, 4))
    ii, off = np.meshgrid(i4, np.arange(3, K // 2 + 1), indexing="ij")
    cands4.append((np.stack([ii, ii + 1, ii + off, ii + off + 1], axis=-1) % K).reshape(-1, 4))
    ii, off = np.meshgrid(i4, np.arange(3, K - 1), indexing="ij")
    jj = ii + off
    kk = (ii[:, :, None] + np.arange(2, K - 1)[None, None, :]) % K
    cd = lambda a, b: np.minimum(np.abs(a - b), K - np.abs(a - b))
    mask = (cd(kk, ii[:, :, None]) >= 2) & (cd(kk, (ii + 1)[:, :, None]) >= 2) & (cd(kk, jj[:, :, None]) >= 2)
    m2 = np.stack([np.broadcast_to(ii[:, :, None], kk.shape),
                   np.broadcast_to((ii + 1)[:, :, None], kk.shape),
                   np.broadcast_to(jj[:, :, None], kk.shape), kk], axis=-1) % K
    cands4.append(m2[mask])
    cand4 = np.vstack(cands4)

    cands3 = [np.stack([i4, i4 + 1, i4 + 2], axis=1) % K]
    ii, off = np.meshgrid(i4, np.arange(2, K - 1), indexing="ij")
    cands3.append((np.stack([ii, ii + 1, ii + off], axis=-1) % K).reshape(-1, 3))
    msh = np.stack(np.meshgrid(i4, i4, i4, indexing="ij"), axis=-1)
    msk = (msh[..., 1] - msh[..., 0] >= 2) & (msh[..., 2] - msh[..., 1] >= 2) & \
          (msh[..., 0] + K - msh[..., 2] >= 3)
    cands3.append(msh[msk] % K)
    cand3 = np.vstack(cands3)

    def verify(cand, own):
        out = []
        for s in range(0, len(cand), 40000):
            c = cand[s:s + 40000]
            C_ = len(c)
            p = V[:, c]
            keep = np.ones((C_, K), bool)
            keep[np.arange(C_)[:, None], c] = False
            if own == 4:
                a = _cross3_vec(p[:, :, 1] - p[:, :, 0], p[:, :, 2] - p[:, :, 0], p[:, :, 3] - p[:, :, 0])
                ref = c[:, 0]
                s0 = -(a * p[:, :, 0]).sum(0)
                diff = V[None] - p[:, :, 0].T[:, :, None]
                side = np.einsum("ic,cik->ck", a, diff)
                sc = np.abs(np.where(keep, side, 0.0)).max(1)
                smax = np.where(keep, side, -np.inf).max(1)
                smin = np.where(keep, side, np.inf).min(1)
                good = ((smax <= tol * sc) & (s0 <= tol * sc)) | ((smin >= -tol * sc) & (s0 >= -tol * sc))
                good &= sc > 1e-30
            else:
                a = _cross3_vec(p[:, :, 0], p[:, :, 1], p[:, :, 2])
                ref = None
                side = (V.T @ a).T
                sc = np.abs(np.where(keep, side, 0.0)).max(1)
                good = ((np.where(keep, side, -np.inf).max(1) <= tol * sc)
                        | (np.where(keep, side, np.inf).min(1) >= -tol * sc))
                good &= sc > 1e-30
            an = a / np.linalg.norm(a, axis=0)[None, :]
            out += [(an[:, r], ref[r] if ref is not None else None) for r in np.where(good)[0]]
        oriented = []
        for a_unit, r in out:
            if r is None:
                if float((a_unit @ V).max()) > 1e-8:
                    a_unit = -a_unit
                oriented.append((a_unit, None))
            else:
                b = float(a_unit @ V[:, r])
                mx = float((a_unit @ V).max())
                scale = 1.0 + abs(b)
                if mx > b + 1e-8 * scale or 0.0 > b + 1e-9 * scale:
                    a_unit = -a_unit
                oriented.append((a_unit, r))
        return oriented

    return verify(cand4, 4) + verify(cand3, 3)


def _image_halfspaces(E_S: np.ndarray, W: float, n_checks: int = 30, seed: int = 0):
    """Verified half-space description (Ac, bc) of  I = conv{0, W*cols(E_S)},
    or None (caller falls back to exact per-step chord LPs).  Certified by
    all-vertex containment plus a support-function probe (supp_I is closed form)."""
    m, K = E_S.shape
    if m != 4 or K < 6 or not _is_veronese4(E_S):
        return None
    facets = _curve_facets(tuple(np.round(E_S, 10).ravel()))
    if not facets:
        return None
    Ac = np.array([f[0] for f in facets])
    ref = np.array([f[1] if f[1] is not None else -1 for f in facets])
    bc = np.where(ref >= 0, W * (Ac * E_S[:, ref].T).sum(1), 0.0)
    V_full = np.hstack([np.zeros((m, 1)), W * E_S])
    if float((Ac @ V_full - bc[:, None]).max()) > 1e-8 * max(1.0, float(bc.max())):
        return None
    probe = _HiGHS(m, -_INF * np.ones(m), _INF * np.ones(m), Ac, bc)
    for w in _sphere_facets(m, n_checks, seed):
        val = probe.objective(-np.asarray(w, float))        # max w^T c over H
        if val is None or val > W * max(0.0, float((w @ E_S).max())) + 1e-6:
            return None
    return Ac, bc


# --------------------------------------------------------------------------- #
# small LP / hit-and-run utilities
# --------------------------------------------------------------------------- #
def _ray_clip(A, b, c, w):
    """tau-interval [lo, hi] keeping  c + tau w  inside the slab  {x : A x <= b}."""
    v = A @ w
    s = b - A @ c
    up, dn = v > 1e-14, v < -1e-14
    hi = float((s[up] / v[up]).min()) if up.any() else 1e300
    lo = float((s[dn] / v[dn]).max()) if dn.any() else -1e300
    return lo, hi


def _max_slack(n, lo, up, A, b):
    """Chebyshev-centre LP: maximize the uniform slack over  {lo <= x <= up, A x <= b}.
    Appends one slack variable t (so each row reads  A_i x + t <= b_i) and returns
    the solution x* (the last component is the achieved slack) together with the
    HiGHS status, so a caller can report *why* x* is None."""
    m = A.shape[0]
    model = _HiGHS(n + 1, np.concatenate([lo, [-1e6]]), np.concatenate([up, [1e6]]),
                   np.hstack([A, np.ones((m, 1))]), b)
    return model.solve(np.r_[np.zeros(n), -1.0]), model.status


# --------------------------------------------------------------------------- #
# exact conditional moments (replaces the fibre chain)
# --------------------------------------------------------------------------- #
def _conditional_moments(E_S, E_L, cs, W, ones, K, m, p, n_sub, rng, c_data):
    """Moments of c_L from the EXACT conditional range at fixed c_S.

    For each subsampled chunk point c, two LPs per output give
        lo_j(c) = min kernel[j] . z ,  hi_j(c) = max kernel[j] . z
        s.t.  E_S z = c,  0 <= z <= W,  1^T z <= W
    i.e. the range of that response over the positive spectra which reproduce c
    exactly.  Both ends are attained by genuine admissible spectra, so lo >= 0.

    Taking the conditional law uniform on [lo, hi] and comonotone across outputs,
    the law of total (co)variance gives
        E[c_L]        = E_c[mid]
        Cov(c_S, c_L) = Cov_c(c, mid)                 (c_S is fixed given c)
        Cov(c_L)      = Cov_c(mid) + E_c[half_j half_k] / 3
    with mid = (lo+hi)/2 and half = (hi-lo)/2."""
    n_sub = min(int(n_sub), len(cs))
    sub = rng.choice(len(cs), n_sub, replace=False)
    h = highspy.Highs()
    h.silent()
    h.setOptionValue("threads", 1)
    I32 = np.arange(K, dtype=np.int32)
    for _ in range(K):
        h.addVariable(0.0, float(W), 0.0)
    for i in range(m):
        h.addRow(float(c_data[i]), float(c_data[i]), K, I32,
                 np.ascontiguousarray(E_S[i], np.float64))
    h.addRow(-_INF, float(W), K, I32, ones)

    lo_c = np.empty((n_sub, p))
    hi_c = np.empty((n_sub, p))
    keep = np.ones(n_sub, bool)
    for s in range(n_sub):
        cc = cs[sub[s]]
        for i in range(m):
            h.changeRowBounds(i, float(cc[i]), float(cc[i]))
        for j in range(p):
            for sgn in (1.0, -1.0):
                h.changeColsCost(K, I32, np.ascontiguousarray(sgn * E_L[j], np.float64))
                h.run()
                if h.getModelStatus() != _OPTIMAL:
                    keep[s] = False
                    break
                x = np.asarray(h.getSolution().col_value, np.float64)
                val = float(E_L[j] @ x)
                if sgn > 0.0:
                    lo_c[s, j] = val
                else:
                    hi_c[s, j] = val
            if not keep[s]:
                break

    n = int(keep.sum())
    if n < 2:
        raise RuntimeError(
            "conditional fibre: only %d of %d subsampled c values gave a solvable LP, "
            "so no moments can be formed" % (n, n_sub))
    if n < 0.9 * n_sub:
        warnings.warn(
            "conditional fibre: dropped %d of %d subsampled c values whose conditional "
            "LP did not solve (%.1f%%); the retained set may not be representative"
            % (n_sub - n, n_sub, 100.0 * (1.0 - n / n_sub)), RuntimeWarning, stacklevel=3)

    csub = cs[sub][keep]
    lo_c, hi_c = lo_c[keep], hi_c[keep]
    mid = 0.5 * (lo_c + hi_c)
    half = 0.5 * (hi_c - lo_c)
    mean_S, mean_L = csub.mean(0), mid.mean(0)
    dS, dM = csub - mean_S, mid - mean_L
    cov_SS = dS.T @ dS / (n - 1)
    cov_SL = dS.T @ dM / (n - 1)
    cov_LL = dM.T @ dM / (n - 1) + (half.T @ half) / (3.0 * n)
    u = rng.random((n, 1))
    cl_samp = mid + half * (2.0 * u - 1.0)      # inside [lo, hi] -> never negative
    return mean_S, mean_L, cov_SS, cov_SL, cov_LL, csub, cl_samp


# --------------------------------------------------------------------------- #
# public: how far the data sit outside the positive cone
# --------------------------------------------------------------------------- #
def min_chi(E_s, C_s, Sigma_s, omega_grid, floor=None, n_facets=1500, seed=0,
            chi_max=20.0, tol=1e-6) -> float:
    """Smallest chi at which the admissible set is non-empty.

    chi_min == 0 means the measured C_s is reproduced exactly by some positive
    spectrum on omega_grid.  chi_min > 0 means it is not: the data sit that many
    Mahalanobis sigma outside the positive cone.  The chi^2 admissible set is
    then a spherical CAP rather than a full ellipsoid, and anything that assumes
    the ellipsoid stops holding near chi_min -- in particular the sampled
    covariance is no longer affine in chi^2, so a two-point (chi^2_a, chi^2_b)
    split into statistical and systematic parts becomes meaningless.  Run with
    chi^2 well above chi_min^2, or reduce the tension.

    Because the facet rows OUTER-approximate the ellipsoid, the value returned is
    a slight LOWER bound on the true minimum.  Returns inf if no chi <= chi_max
    admits a positive spectrum."""
    omega_grid = np.asarray(omega_grid, float)
    E_S = np.asarray(E_s, float)
    if floor is not None:
        keep = omega_grid >= float(floor)
        omega_grid, E_S = omega_grid[keep], E_S[:, keep]
    c_data = np.asarray(C_s, float).ravel()
    Sigma_s = np.asarray(Sigma_s, float)
    K = E_S.shape[1]
    zero = np.zeros(K)

    def feasible(chi):
        G, b, _, _ = _ellipsoid_facets(c_data, Sigma_s, E_S, chi, n_facets, seed)
        return _HiGHS(K, zero, _INF * np.ones(K), G, b).objective(zero) is not None

    if feasible(0.0):
        return 0.0
    if not feasible(float(chi_max)):
        return float("inf")
    lo, hi = 0.0, float(chi_max)
    while hi - lo > tol * max(hi, 1.0):
        mid = 0.5 * (lo + hi)
        if feasible(mid):
            hi = mid
        else:
            lo = mid
    return hi


# --------------------------------------------------------------------------- #
# public: the two-stage sampler
# --------------------------------------------------------------------------- #
def sample_admissible(E_s, C_s, Sigma_s, kernel, omega_grid,
                      chi=2.0, floor=None,
                      n_facets=1500, n_samples=20000, warmup=4000,
                      seed=0, joint=False,
                      conditional_fibre=500) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample the admissible set of positive spectra; return (mean, covariance,
    samples) of the target response.

    Arguments
    ---------
    E_s        (m, K)  data response matrix -- row i is a weighted integral
                         w_i(omega) of the spectral density;  c_S[i] = E_s[i] @ z
    C_s        (m,)    measured data, aligned with the rows of E_s
    Sigma_s    (m, m)  full covariance of C_s
    kernel     (p, K)  target response matrix -- row j is the target weighted
                         integral;  c_L[j] = kernel[j] @ z.  A row
                         [exp(-5*omega_grid), ...]  is the Laplace correlator C(5)
    omega_grid (K,)    the spectral grid: the columns of E_s and kernel
    floor      optional: drop grid nodes (and the matching columns of E_s and
                         kernel) with  omega < floor
    joint      if True, return the concatenated (c_S, c_L) moments/samples
                         instead of c_L alone
    conditional_fibre
               number of chunk points on which the EXACT conditional range of each
               target response at fixed c_S is evaluated, by two LPs per output:
                   min / max  kernel[j] . z   s.t.  E_s z = c,  z >= 0,  1^T z <= W
               Both ends are attained by genuine admissible spectra, so lo >= 0 and
               the prediction can never come out negative.  The conditional law is
               taken uniform on [lo, hi] and comonotone across outputs, which is
               exact for every marginal and for Cov(c_S, c_L); only the conditional
               cross-output correlation is modelled.  A few hundred points suffice.

    The admissible set is  { z >= 0 :  (E_s z - C_s)^T Sigma_s^{-1}
    (E_s z - C_s) <= chi^2  (faceted into an outer polytope),  1^T z <= W_max }.
    E_s and kernel must be functionals of the SAME positive spectrum z (the
    admissible set is one measure) -- do not mix different operators'
    correlators.  The fast verified image-body half-spaces are used when the
    E_s columns lie on the 4-d Veronese curve, else exact per-step LP chords."""
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
    c_data = np.asarray(C_s, float).ravel()
    m, p = E_S.shape[0], E_L.shape[0]
    if c_data.shape[0] != m:
        raise ValueError("C_s must have m=%d entries (one per E_s row), got %d"
                         % (m, c_data.shape[0]))
    Sigma_s = np.asarray(Sigma_s, float)
    if Sigma_s.shape != (m, m):
        raise ValueError("Sigma_s must be (%d, %d), got %s" % (m, m, Sigma_s.shape))
    ones = np.ones(K)
    G, b, _, _ = _ellipsoid_facets(c_data, Sigma_s, E_S, chi, n_facets, seed)

    # total-weight cap  W_max = max 1^T z over the faceted set (one LP)
    lpz = _HiGHS(K, np.zeros(K), _INF * np.ones(K), G, b)
    _w = lpz.objective(-ones)                       # min -1^T z = -(max 1^T z) = -W_max
    if _w is None:
        raise RuntimeError(_lp_failure("total-weight cap", lpz.status, chi,
                                       G, omega_grid))
    W = -float(_w) + 1e-9

    rng = np.random.default_rng(seed + 1)
    # The rows of E_s go near-parallel once several exponentials share a narrow
    # omega window.  Nothing here inverts E_s any more -- the conditional LPs work
    # with E_s directly -- but a near-degenerate E_s still makes those LPs fragile,
    # so report it.
    sv_e = np.linalg.svd(E_S, compute_uv=False)
    cond_E = float(sv_e[0] / sv_e[-1]) if sv_e[-1] > 0.0 else float("inf")
    if cond_E > 1e10:
        warnings.warn(
            "the data response matrix E_s has condition number %.2e, leaving about %.0f "
            "significant digits.  The %d response rows are close to linearly dependent "
            "on this omega grid, which makes the conditional LPs fragile: use fewer "
            "rows, widen the grid, or rescale the columns."
            % (cond_E, max(0.0, 16.0 - np.log10(cond_E)), m), RuntimeWarning, stacklevel=2)

    # The ellipsoid is clipped EXACTLY (a scalar quadratic), not through its
    # facets: the facet rows stay in the z-space LPs above, where an outer
    # approximation is wanted, but in the hit-and-run they would only add an
    # O(n_facets^(-1/(m-1))) inflation of the set at O(n_facets) cost per step.
    L_w = _whiten(Sigma_s)
    chi2 = float(chi) ** 2

    def ellipsoid_clip(c, w):
        """tau-interval with  ||L_w (c + tau w - c_data)|| <= chi."""
        r = L_w @ (c - c_data)
        v = L_w @ w
        a = float(v @ v)
        if a <= 0.0:                                 # w is invisible to the data
            return (-1e300, 1e300) if float(r @ r) <= chi2 else (None, None)
        q = float(v @ r)
        disc = q * q - a * (float(r @ r) - chi2)
        if disc <= 0.0:                              # c outside (round-off only)
            return None, None
        s = disc ** 0.5
        return (-q - s) / a, (-q + s) / a

    # image body half-spaces (fast) or per-step chord LPs (safe)
    hs = _image_halfspaces(E_S, W, seed=seed + 7)
    if hs is not None:
        Ac_c, bc_c = hs
        use_lp = False
    else:
        Ac_c, bc_c = None, None
        use_lp = True
        chord = _Chord(E_S, W)

    def chord_clip(c, w):
        lo, hi = ellipsoid_clip(c, w)
        if lo is None:
            return None, None
        if use_lp:
            t_lo, t_hi = chord.chord(c, w)
            if t_lo is None:
                return None, None
            lo, hi = max(lo, min(t_lo, t_hi)), min(hi, max(t_lo, t_hi))
        else:
            s_lo, s_hi = _ray_clip(Ac_c, bc_c, c, w)
            lo, hi = max(lo, s_lo), min(hi, s_hi)
        return lo, hi

    n_reject = [0]

    def cstep(c):
        # A direction whose chord LP fails numerically is not usable, so redraw.
        # The failure belongs to the (c, w) pair, not to c -- at a state where one
        # direction fails, ~99% of fresh directions still succeed -- so a few draws
        # clear it.  If none does, reject the move and keep the state: staying put
        # is a valid hit-and-run step, whereas the old two-draw version fell
        # through to  hi - lo  with both None and raised TypeError.
        for _ in range(8):
            w = rng.standard_normal(m)
            lo, hi = chord_clip(c, w)
            if hi is not None and hi > lo:
                return c + (lo + (hi - lo) * rng.random()) * w
        n_reject[0] += 1
        return c

    # strictly-interior start: max-min ellipsoid slack over  z>=0, 1^T z<=W
    x, _st = _max_slack(K, np.zeros(K), W * ones, np.vstack([G, ones[None, :]]),
                        np.concatenate([b, [W]]))
    if x is None:
        raise RuntimeError(_lp_failure("interior start", _st, chi, G, omega_grid))
    if x[-1] <= 1e-12:
        raise RuntimeError("admissible set has empty interior -- increase chi (chi=%.2f)" % chi)
    c = E_S @ x[:K]
    # The facet rows OUTER-approximate the ellipsoid, so this Chebyshev centre can
    # sit in the overhang -- i.e. outside the exact ellipsoid the walk clips
    # against, which makes the very first ellipsoid_clip fail and every step
    # reject.  Fall back to the admissible point closest to c_data (the chi=0
    # facet LP), which lies inside whenever chi exceeds min_chi.
    if float(np.sum((L_w @ (c - c_data)) ** 2)) > chi2:
        G0, b0, _, _ = _ellipsoid_facets(c_data, Sigma_s, E_S, 0.0, n_facets, seed)
        x0, _st0 = _max_slack(K, np.zeros(K), W * ones, np.vstack([G0, ones[None, :]]),
                              np.concatenate([b0, [W]]))
        if x0 is not None:
            c = E_S @ x0[:K]
        if x0 is None or float(np.sum((L_w @ (c - c_data)) ** 2)) > chi2:
            raise RuntimeError(
                "no interior start inside the exact chi-ellipsoid (chi=%.2f): the facet "
                "outer approximation is looser here than the ellipsoid itself.  Raise "
                "n_facets, or compare chi against min_chi -- if they are close the "
                "admissible set is a thin cap." % chi)

    cs = np.empty((n_samples, m))
    for _ in range(int(warmup)):
        c = cstep(c)
    for i in range(n_samples):
        c = cstep(c)
        cs[i] = c
    # A rejected step keeps the state, which is a legitimate hit-and-run move, but
    # the directions that get rejected are the numerically hard near-tangent ones,
    # so a non-negligible rejection rate down-weights them and skews the sample.
    # At the observed rates (order 1e-5) that is irrelevant; warn well before it
    # matters, and refuse outright once the chain is effectively stuck.
    n_steps = int(warmup) + int(n_samples)
    frac = n_reject[0] / max(n_steps, 1)
    if frac > 0.25:
        raise RuntimeError(
            "chunk chain is not mixing: %d of %d steps (%.1f%%) found no usable chord "
            "-- the admissible set is probably degenerate at chi=%.2f"
            % (n_reject[0], n_steps, 100 * frac, chi))
    if frac > 1e-3:
        warnings.warn(
            "hit-and-run rejected %d of %d chunk steps (%.2f%%) because no usable chord "
            "was found in 8 draws (chi=%.2f).  Rejections are not isotropic -- they "
            "favour near-tangent directions -- so the sampled moments may be skewed at "
            "this rate.  Treat the quoted spread as indicative, and check convergence "
            "against a different seed." % (n_reject[0], n_steps, 100 * frac, chi),
            RuntimeWarning, stacklevel=2)

    if not conditional_fibre or int(conditional_fibre) < 2:
        raise ValueError("conditional_fibre must be an integer >= 2 (number of chunk "
                         "points at which the exact conditional range is evaluated); "
                         "got %r" % (conditional_fibre,))
    mean_S, mean_L, cov_SS, cov_SL, cov_LL, cs, cl_samp = _conditional_moments(
        E_S, E_L, cs, W, ones, K, m, p, int(conditional_fibre), rng, c_data)
    if joint:
        samples = np.hstack([cs, cl_samp])
        mean = np.concatenate([mean_S, mean_L])
        cov = np.block([[cov_SS, cov_SL], [cov_SL.T, cov_LL]])
    else:
        samples, mean, cov = cl_samp, mean_L, cov_LL
    return mean, cov, samples
