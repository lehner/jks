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
# Prototype restriction:  E_S > 0 entrywise (Laplace-type data weights).  The
# total-weight cap 1^T z <= W (needed for unbounded sets when E_S has
# zero/negative entries) is then redundant: the recession cone of
# {z >= 0 : E_S z = c} is {0}.
# --------------------------------------------------------------------------- #

def _dual_bound_one(E_eq, C_s, Lc, chi, rhs, box0, maxit=200, tol=1e-9,
                    box_max=25):
    """phi = min { v.C_s + chi*||Lc^T v|| : E_eq^T v >= rhs },  v free, |v| <= box.

    E_eq is column-equilibrated (O(1) entries); rhs = rs * k / nrm with nrm =
    max|k|, so the optimum is O(1) (the unscaled optimum of a late-lag kernel
    is below HiGHS dual tolerance and silently corrupts the answer) and
    v ~ O(1/nrm) (hence box0).  Returns (phi_best, v_best, status, n_cuts);
    phi_best is the exact objective at v_best; the caller checks v_best's
    majorisation in original units."""
    m = len(C_s)
    K = rhs.shape[0]

    def build(box, cuts):
        h = highspy.Highs()
        h.silent()
        h.setOptionValue("threads", 1)
        idx = np.arange(m + 1, dtype=np.int32)
        for i in range(m):
            h.addVariable(-float(box), float(box), 0.0)
        h.addVariable(0.0, _INF, 0.0)                    # s (norm epigraph)
        for j in range(K):                               # majorisation rows
            row = np.zeros(m + 1)
            row[:m] = E_eq[:, j]
            h.addRow(float(rhs[j]), _INF, m + 1, idx,
                     np.ascontiguousarray(row, np.float64))
        for u in cuts:                                   # Kelley cuts s >= (Lc u).v
            row = np.zeros(m + 1)
            row[:m] = Lc @ u
            row[m] = -1.0
            h.addRow(-_INF, 0.0, m + 1, idx, np.ascontiguousarray(row, np.float64))
        cost = np.zeros(m + 1)
        cost[:m] = C_s
        cost[m] = chi
        h.changeColsCost(m + 1, idx, np.ascontiguousarray(cost, np.float64))
        return h

    cuts = [np.eye(m)[i] for i in range(m)] + [
        -np.eye(m)[i] for i in range(m)]
    box = float(box0)
    best, v_best = np.inf, None
    nbox = 0
    for it in range(1, maxit + 1):
        h = build(box, cuts)
        h.run()
        st = h.getModelStatus()
        if st == _INFEASIBLE:
            # the majorisation is feasible for |v| large enough (E_eq columns
            # positive), so infeasibility is the box -- grow it
            box *= 8.0
            nbox += 1
            if nbox > box_max:
                return None, None, "infeasible", len(cuts)
            continue
        if st == _UNBOUNDED:                              # admissible set empty
            return None, None, "empty_set", len(cuts)
        if st != _OPTIMAL:
            return None, None, str(st).rsplit(".", 1)[-1], len(cuts)
        x = np.asarray(h.getSolution().col_value, np.float64)
        v, s = x[:m], x[m]
        lb = float(C_s @ v + chi * s)
        w = Lc.T @ v
        val = float(C_s @ v + chi * np.sqrt(max(float(w @ w), 0.0)))
        if val < best:
            best, v_best = val, v.copy()
        if best - lb <= tol * max(1.0, abs(best)):
            break
        if float(w @ w) <= 1e-300:
            break
        cuts.append(w / np.sqrt(float(w @ w)))
        if np.abs(v).max() > 0.999 * box:                 # certificate wants more range
            box *= 8.0
            nbox += 1
            if nbox > box_max:
                # objective keeps improving with the box: dual unbounded
                # <=> admissible set empty (chi below chi_min)
                return None, None, "empty_set", len(cuts)
    if v_best is None:
        return None, None, "no_solution", len(cuts)
    return best, v_best, "ok", len(cuts)


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


def positivity_bounds(E_s, C_s, Sigma_s, kernel, omega_grid, chi,
                      floor=None, tol=1e-9, maxit=200):
    """Exact admissible range of every target weight, plus the slope of the
    band midpoint.  Returns (lo, hi, M, info):

        lo[j], hi[j]   min/max of  kernel[j].z  over
                      { z >= 0 : (E_s z - C_s)^T Sigma_s^{-1} (E_s z - C_s) <= chi^2 }
                      (rigorous outer approximation: each endpoint carries a
                      one-sided safety margin of  viol * |C_s|_1 * nrm)
        M[j]           d (lo[j]+hi[j])/2 / d C_s   (m-vector; the statistical
                      propagation matrix, from the certificates, exact by the
                      envelope theorem)
        info           dict with per-output status / violation / cut counts

    Prototype restriction: E_s must be strictly positive entrywise."""
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
    if not (E_S > 0).all():
        raise NotImplementedError(
            "positivity_bounds (prototype) requires E_s > 0 entrywise; the "
            "total-weight-cap extension for general weights is not implemented yet")
    c_data = np.asarray(C_s, float).ravel()
    m, p = E_S.shape[0], E_L.shape[0]
    if c_data.shape[0] != m:
        raise ValueError("C_s must have m=%d entries, got %d" % (m, c_data.shape[0]))
    Sig = np.asarray(Sigma_s, float)
    Sig = 0.5 * (Sig + Sig.T)
    if Sig.shape != (m, m):
        raise ValueError("Sigma_s must be (%d, %d)" % (m, m))
    try:
        Lc = np.linalg.cholesky(Sig)
    except np.linalg.LinAlgError:
        Lc = np.linalg.cholesky(Sig + 1e-12 * np.trace(Sig) / m * np.eye(m))

    rs = 1.0 / E_S.max(0)                    # column equilibration (E_S > 0)
    E_eq = E_S * rs[None, :]

    lo = np.empty(p); hi = np.empty(p); M = np.empty((p, m))
    status = []; viols = []; ncuts = []
    cmargin = float(np.abs(c_data).sum()
                    + chi * np.sqrt(float((Lc ** 2).sum())))
    for j in range(p):
        k = E_L[j]
        nrm = float(np.abs(k).max())
        if nrm <= 0.0:                       # zero target weight
            lo[j] = hi[j] = 0.0
            M[j] = 0.0
            status.append("zero_kernel"); viols.append(0.0); ncuts.append(0)
            continue
        box0 = 8.0 / nrm                     # v ~ O(1/nrm)
        phi_h, v_h, st_h, nc_h = _dual_bound_one(
            E_eq, c_data, Lc, float(chi), rs * k / nrm, box0, maxit, tol)
        phi_l, v_l, st_l, nc_l = _dual_bound_one(
            E_eq, c_data, Lc, float(chi), -rs * k / nrm, box0, maxit, tol)
        if st_h != "ok" or st_l != "ok":
            lo[j] = hi[j] = np.nan
            M[j] = np.nan
            status.append(st_h if st_h != "ok" else st_l)
            viols.append(np.nan); ncuts.append(-1)
            continue
        # certificate check in ORIGINAL units: u = nrm v must satisfy E^T u >= +/- k
        u_h = nrm * v_h
        u_l = nrm * v_l
        viol = max(float(np.maximum(0.0, k - E_S.T @ u_h).max()),
                   float(np.maximum(0.0, -k - E_S.T @ u_l).max()))
        margin = viol * cmargin              # one-sided safety on each endpoint
        hi[j] = nrm * phi_h + margin
        lo[j] = -nrm * phi_l - margin
        M[j] = 0.5 * nrm * (v_h - v_l)
        status.append("ok"); viols.append(viol / nrm)
        ncuts.append(nc_h + nc_l)
    info = dict(status=status, violation_rel=viols, ncuts=ncuts)
    return lo, hi, M, info
