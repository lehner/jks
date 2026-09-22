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

def _dual_bound_one(E_eq, C_s, Lc, chi, rhs, box0, maxit=200, tol=1e-9,
                    box_max=25, init_cuts=None):
    """phi = min { v.C_s + chi*||Lc^T v|| : E_eq^T v >= rhs },  v free, |v| <= box.

    E_eq is column-equilibrated (O(1) entries); rhs = rs * k / nrm with nrm =
    max|k|, so the optimum is O(1) (the unscaled optimum of a late-lag kernel
    is below HiGHS dual tolerance and silently corrupts the answer) and
    v ~ O(1/nrm) (hence box0).  init_cuts reuses the Kelley cuts of a previous
    solve at different data (the cuts are data-independent) for fast
    re-evaluation.  Returns (phi_best, v_best, status, cuts); phi_best is the
    exact objective at v_best; the caller checks v_best's majorisation in
    original units.  A solution sitting on the box is never accepted as
    converged (the objective may keep improving beyond it)."""
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

    cuts = (list(init_cuts) if init_cuts
            else [np.eye(m)[i] for i in range(m)] + [-np.eye(m)[i] for i in range(m)])
    box = float(box0)
    best, v_best = np.inf, None
    nbox = 0
    stalled = 0
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
                return None, None, "infeasible", cuts
            continue
        if st == _UNBOUNDED:                              # admissible set empty
            return None, None, "empty_set", cuts
        if st != _OPTIMAL:
            return None, None, str(st).rsplit(".", 1)[-1], cuts
        x = np.asarray(h.getSolution().col_value, np.float64)
        v, s = x[:m], x[m]
        lb = float(C_s @ v + chi * s)
        w = Lc.T @ v
        val = float(C_s @ v + chi * np.sqrt(max(float(w @ w), 0.0)))
        at_box = np.abs(v).max() > 0.999 * box
        # best is a VALID bound regardless of the gap (exact objective at a
        # majorisation-feasible v), so any stop keeps rigor; stop on the
        # optimality gap OR on stall -- the gap floor sits at the HiGHS LP
        # noise level, and a tight tol alone would burn all of maxit
        if val < best and (best == np.inf or val < best * (1.0 - 1e-11)):
            best, v_best = val, v.copy()
            stalled = 0
        else:
            stalled += 1
        if not at_box and stalled >= 2:
            break
        if not at_box and best - lb <= tol * max(1.0, abs(best)):
            break
        if not at_box and float(w @ w) <= 1e-300:
            break
        if float(w @ w) > 1e-300:
            u = w / np.sqrt(float(w @ w))
            if not cuts or float(np.abs(u - np.asarray(cuts[-1])).max()) > 1e-12:
                cuts.append(u)
        if at_box:                 # certificate wants more range (or the dual
            box *= 8.0             # is unbounded: admissible set empty)
            nbox += 1
            if nbox > box_max:
                return None, None, "empty_set", cuts
    if v_best is None:
        return None, None, "no_solution", cuts
    return best, v_best, "ok", cuts


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


def _solve_one_output(E_S, E_eq, k, c_data, Lc, chi, rs, tol, maxit, hint):
    """One target weight: rigorous band without safety margins.
    Returns (hi_raw, lo_raw, M, status, viol_rel, n_cuts, hint_out);
    raw values are +-inf on unbounded sides, None on unsolved sides; M is the
    midpoint slope (None unless fully solved).  hint = (cuts_hi, cuts_lo,
    ub_hi, ub_lo) from a previous call with the same (E, k, chi) -- the cuts
    and the cone result are data-independent -- or None."""
    nrm = float(np.abs(k).max())
    if nrm <= 0.0:                       # zero target weight
        return 0.0, 0.0, None, "zero_kernel", 0.0, 0, (None, None, None, None)
    k = k.copy()
    k[np.abs(k) <= 1e-9 * nrm] = 0.0     # at the boundedness tolerance
    if hint is not None and hint[2] is not None:
        ub_hi, ub_lo = hint[2], hint[3]
    else:
        ub_hi, ub_lo = _cone_unbounded(E_eq, k * rs, 1e-9 * nrm)
    if ub_hi is None or ub_lo is None:   # cone LP itself failed
        return None, None, None, "cone_lp_failed", np.nan, -1, hint
    hint = ((hint[0] if hint else None), (hint[1] if hint else None),
            ub_hi, ub_lo)
    box0 = 8.0 / nrm                     # v ~ O(1/nrm)
    hi_raw = lo_raw = None
    if ub_hi:
        hi_raw = np.inf
        st_h, ch, nc_h = "unbounded", hint[0], 0
    else:
        phi_h, v_h, st_h, ch = _dual_bound_one(
            E_eq, c_data, Lc, float(chi), rs * k / nrm, box0, maxit, tol,
            init_cuts=hint[0])
        nc_h = len(ch)
        hi_raw = nrm * phi_h if st_h == "ok" else None
    if ub_lo:
        lo_raw = -np.inf
        st_l, cl, nc_l = "unbounded", hint[1], 0
    else:
        phi_l, v_l, st_l, cl = _dual_bound_one(
            E_eq, c_data, Lc, float(chi), -rs * k / nrm, box0, maxit, tol,
            init_cuts=hint[1])
        nc_l = len(cl)
        lo_raw = -nrm * phi_l if st_l == "ok" else None
    hint_out = (ch if (not ub_hi and st_h == "ok") else hint[0],
                cl if (not ub_lo and st_l == "ok") else hint[1],
                ub_hi, ub_lo)
    if ub_hi and ub_lo:
        return hi_raw, lo_raw, None, "unbounded", np.nan, nc_h + nc_l, hint_out
    if ub_hi:
        return hi_raw, lo_raw, None, "unbounded_hi", np.nan, nc_h + nc_l, hint_out
    if ub_lo:
        return hi_raw, lo_raw, None, "unbounded_lo", np.nan, nc_h + nc_l, hint_out
    if st_h != "ok" or st_l != "ok":
        return hi_raw, lo_raw, None, st_h if st_h != "ok" else st_l, np.nan, -1, hint_out
    # certificate check in ORIGINAL units: u = nrm v must satisfy E^T u >= +/- k
    u_h = nrm * v_h
    u_l = nrm * v_l
    viol = max(float(np.maximum(0.0, k - E_S.T @ u_h).max()),
               float(np.maximum(0.0, -k - E_S.T @ u_l).max()))
    M = 0.5 * nrm * (v_h - v_l)
    return hi_raw, lo_raw, M, "ok", viol / nrm, nc_h + nc_l, hint_out


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
    boundedness tolerance.  info["hints"] carries the per-output Kelley cuts
    for fast re-evaluation at other data points via band_center."""
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

    colmax = np.abs(E_S).max(0)                # sign-aware column equilibration
    rs = np.where(colmax > 0.0, 1.0 / np.maximum(colmax, 1e-300), 1.0)
    E_eq = E_S * rs[None, :]

    lo = np.empty(p); hi = np.empty(p); M = np.empty((p, m))
    status = []; viols = []; ncuts = []; hints = []
    cmargin = float(np.abs(c_data).sum()
                    + chi * np.sqrt(float((Lc ** 2).sum())))
    for j in range(p):
        hraw, lraw, Mj, st, viol, nc, hint = _solve_one_output(
            E_S, E_eq, E_L[j], c_data, Lc, chi, rs, tol, maxit, None)
        if st == "ok":
            margin = viol * cmargin      # one-sided safety on each endpoint
            hi[j] = hraw + margin
            lo[j] = lraw - margin
        else:                            # keep +-inf on the unbounded side
            hi[j] = hraw if hraw is not None else np.nan
            lo[j] = lraw if lraw is not None else np.nan
        M[j] = 0.0 if st == "zero_kernel" else (Mj if Mj is not None else np.nan)
        status.append(st); viols.append(viol); ncuts.append(nc); hints.append(hint)
    info = dict(status=status, violation_rel=viols, ncuts=ncuts, hints=hints)
    return lo, hi, M, info


def band_center(E_s, C_vec, Sigma_s, kernel, omega_grid, chi, hints=None,
                floor=None, tol=1e-9, maxit=200):
    """Center (lo+hi)/2 of every admissible band at data point C_vec.

    The same problem as positivity_bounds evaluated at a DIFFERENT data vector
    (e.g. a jackknife resample), returning only the centers.  The Kelley cuts
    are data-independent, so pass the hints from the main positivity_bounds
    call to make each re-evaluation a few LP solves.

    Returns (m, ok, hints):  m[j] = band center (nan where the band does not
    exist at C_vec, e.g. chi below chi_min(C_vec), or the solver failed);
    ok = per-output success mask; hints = refined cuts for the next call.
    Centers are margin-free (the safety margins cancel in (lo+hi)/2)."""
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
    c_data = np.asarray(C_vec, float).ravel()
    m, p = E_S.shape[0], E_L.shape[0]
    if c_data.shape[0] != m:
        raise ValueError("C_vec must have m=%d entries, got %d" % (m, c_data.shape[0]))
    if not np.isfinite(c_data).all():
        raise ValueError("C_vec must be finite (got NaN/inf entries)")
    Sig = np.asarray(Sigma_s, float)
    Sig = 0.5 * (Sig + Sig.T)
    if Sig.shape != (m, m):
        raise ValueError("Sigma_s must be (%d, %d)" % (m, m))
    try:
        Lc = np.linalg.cholesky(Sig)
    except np.linalg.LinAlgError:
        Lc = np.linalg.cholesky(Sig + 1e-12 * np.trace(Sig) / m * np.eye(m))
    colmax = np.abs(E_S).max(0)
    rs = np.where(colmax > 0.0, 1.0 / np.maximum(colmax, 1e-300), 1.0)
    E_eq = E_S * rs[None, :]

    mm = np.full(p, np.nan)
    ok = np.zeros(p, bool)
    hout = []
    for j in range(p):
        hint = hints[j] if hints is not None else None
        hraw, lraw, Mj, st, viol, nc, hint2 = _solve_one_output(
            E_S, E_eq, E_L[j], c_data, Lc, chi, rs, tol, maxit, hint)
        if st in ("ok", "zero_kernel"):
            mm[j] = 0.5 * (hraw + lraw)
            ok[j] = True
        hout.append(hint2)
    return mm, ok, hout
