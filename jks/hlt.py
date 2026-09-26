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
import mpmath
import numpy as np

__all__ = ["solver"]


# --------------------------------------------------------------------------- #
# Hansen-Lupo-Tantalo (arXiv:1903.06476) coefficients on the grid.
#
# Each output weight k is approximated by  kbar(omega) = sum_i g_i e_i(omega),
# g minimizing
#     W[g] = (1 - lam) A[g]/A[0] + lam B[g]/C_0^2,
#     A[g] = int_grid d omega exp(alpha omega) omega^(2p) (k - kbar)^2,
#     B[g] = g^T Sigma g,
# the integral by the trapezoidal rule on the grid, C_0 the mean of the first
# input weight.  The power p is identical to scaling every input and output
# weight by omega^p.
#
# Precision.  g solves the normal equations  N g = r,
#     N = (1-lam)/A0 Gram + lam/C0^2 Sigma,   Gram_il = sum_j qw_j e_i(w_j) e_l(w_j).
# With D = diag(N)^-1/2 the scaled matrix DND has unit diagonal, so its largest
# eigenvalue is <= m, and its smallest is >= lam/C0^2 min_i(Sigma_ii/N_ii) lmin(corr)
# (corr = the correlation matrix of Sigma).  Every ingredient is a sum of positive
# terms or an eigenvalue of a matrix with condition < 1e10, so the bound
#     kappa <= m C0^2 / (lam min_i(Sigma_ii/N_ii) lmin(corr))
# is reliable in double precision even when kappa itself is 1e40.  For
# kappa <= 1e6 the double-precision stacked least-squares solve is used (error
# <~ eps kappa < 1e-10); beyond that the normal equations are solved in mpmath
# with ceil(log10 kappa) + 20 digits, and every such solve is repeated with 20
# more digits: the two must agree to 1e-10 of the statistical error, else the
# precision is raised (and the solve fails if that does not converge).
# The data C and the weights on the grid are taken as exact (integer-time weights
# exp(-t omega) are re-evaluated at the working precision), and g.C and kbar are
# also formed in mpmath: the HLT coefficients alternate in sign and are large, so
# both can cancel by many orders of magnitude.

class solver:
    """HLT coefficients for a FIXED (inputs, Sigma, outputs, grid, lam, alpha, p).

        s = jks.hlt.solver(w_in, E_in, w_out, E_out, Sigma, C_mean, omega_grid,
                           lam, alpha=0.0, p=0.0)
        s.digits[j]        working precision of output j (None: double)
        s.A_rel[j]         A[g]/A[0], relative L2 mismatch of kbar
        s.B_rel[j]         B[g]/C_0^2
        s.estimate(C)      g.C for every output
        s.kernel(j)        kbar_j on the grid

    w_in / w_out are the weight specifications (an int t for exp(-t omega),
    anything else for an array), E_in / E_out the weights on the grid in
    physical units (no column rescaling: A[g] is a statement about the functions
    in physical units).  Raises RuntimeError if a solve does not converge."""

    def __init__(self, w_in, E_in, w_out, E_out, Sigma, C_mean, omega_grid,
                 lam, alpha=0.0, p=0.0):
        self.w_in, self.w_out = list(w_in), list(w_out)
        self.E_in = np.asarray(E_in, float)                  # (m, K)
        self.E_out = np.asarray(E_out, float)                # (p, K)
        self.grid = np.asarray(omega_grid, float)
        self.lam = float(lam)
        self.c_mn = np.asarray(C_mean, float)
        K = self.K = len(self.grid)
        assert 0.0 < self.lam < 1.0, "lambda must be in (0, 1)"
        assert K >= 2 and np.all(np.diff(self.grid) > 0), "omega_grid must be strictly increasing"
        if p < 0.0:
            assert self.grid[0] > 0.0, "p < 0 needs omega > 0 on the whole grid"
        elif p > 0.0:
            assert self.grid[0] >= 0.0, "p != 0 needs omega >= 0 on the whole grid"
        assert self.c_mn[0] != 0.0, "the first input weight has zero mean; B[g] normalization C_0 undefined"

        # trapezoidal quadrature weights times exp(alpha omega) omega^(2p)
        dw = np.zeros(K)
        dw[1:] += 0.5 * np.diff(self.grid)
        dw[:-1] += 0.5 * np.diff(self.grid)
        self.qw = dw * np.exp(alpha * self.grid) * (self.grid ** (2 * p) if p != 0.0 else 1.0)
        self.sq = np.sqrt(self.qw)
        S = np.asarray(Sigma, float)
        self.Sig = 0.5 * (S + S.T)
        self.Lt = np.linalg.cholesky(self.Sig).T            # B[g] = |Lt g|^2
        self.m, self.p = len(self.c_mn), len(self.E_out)
        self.C0 = float(self.c_mn[0])

        self.gram_diag = (self.E_in ** 2) @ self.qw
        self.A0_d = (self.E_out ** 2) @ self.qw
        sd = np.sqrt(np.diag(self.Sig))
        self.lmin_corr = float(np.linalg.eigvalsh(self.Sig / np.outer(sd, sd)).min())
        self._mp_cache = {}

        sols = [self._solve_output(j) for j in range(self.p)]
        self.g = [s_[0] for s_ in sols]
        self.digits = [s_[1] for s_ in sols]
        self.A_rel = np.array([s_[2] for s_ in sols])
        self.B_rel = np.array([s_[3] for s_ in sols])
        self._kbar = [s_[4] for s_ in sols]

    # ------------------------------------------------------------------ #
    def _kappa_bound(self, j):
        lam, C0 = self.lam, self.C0
        Nd = (1 - lam) / self.A0_d[j] * self.gram_diag + lam / C0 ** 2 * np.diag(self.Sig)
        return self.m * C0 ** 2 / (lam * np.min(np.diag(self.Sig) / Nd) * self.lmin_corr)

    def _hlt_double(self, k, A0):
        """stacked, column-equilibrated least squares (no normal equations)"""
        lam, m = self.lam, self.m
        M = np.vstack([np.sqrt((1 - lam) / A0) * (self.sq[:, None] * self.E_in.T),
                       np.sqrt(lam) / abs(self.C0) * self.Lt])
        rhs = np.concatenate([np.sqrt((1 - lam) / A0) * self.sq * k, np.zeros(m)])
        sc = np.linalg.norm(M, axis=0)
        sc[sc == 0.0] = 1.0
        return np.linalg.lstsq(M / sc, rhs, rcond=None)[0] / sc

    def _mp_rows(self, ws, arrs, dps):
        """weights on the grid at dps digits; integer times re-evaluated exactly"""
        with mpmath.workdps(dps):
            om = [mpmath.mpf(float(x)) for x in self.grid]
            return [[mpmath.exp(-e * o) for o in om] if isinstance(e, int)
                    else [mpmath.mpf(float(x)) for x in a] for e, a in zip(ws, arrs)]

    def _mp_setup(self, dps):
        if dps not in self._mp_cache:
            m = self.m
            with mpmath.workdps(dps):
                E = self._mp_rows(self.w_in, self.E_in, dps)
                q = [mpmath.mpf(float(x)) for x in self.qw]
                Gram = [[mpmath.fsum(qj * a * b for qj, a, b in zip(q, E[i], E[l]))
                         for l in range(m)] for i in range(m)]
                S = [[mpmath.mpf(float(self.Sig[i, l])) for l in range(m)] for i in range(m)]
            self._mp_cache[dps] = (E, q, Gram, S)
        return self._mp_cache[dps]

    def _hlt_mp(self, j, dps):
        """g (as mpf list) minimizing W, solved at dps digits"""
        m = self.m
        E, q, Gram, S = self._mp_setup(dps)
        with mpmath.workdps(dps):
            k = self._mp_rows([self.w_out[j]], [self.E_out[j]], dps)[0]
            A0 = mpmath.fsum(qj * x * x for qj, x in zip(q, k))
            a = (1 - mpmath.mpf(self.lam)) / A0
            b = mpmath.mpf(self.lam) / mpmath.mpf(self.C0) ** 2
            N = mpmath.matrix(m, m); r = mpmath.matrix(m, 1)
            for i in range(m):
                r[i] = a * mpmath.fsum(qj * x * y for qj, x, y in zip(q, E[i], k))
                for l in range(m):
                    N[i, l] = a * Gram[i][l] + b * S[i][l]
            d = [1 / mpmath.sqrt(N[i, i]) for i in range(m)]
            for i in range(m):
                r[i] *= d[i]
                for l in range(m):
                    N[i, l] *= d[i] * d[l]
            y = mpmath.lu_solve(N, r)
            return [d[i] * y[i] for i in range(m)]

    @staticmethod
    def _mp_dot(g, c, dps):
        with mpmath.workdps(dps):
            return mpmath.fsum(gi * mpmath.mpf(float(ci)) for gi, ci in zip(g, c))

    def _solve_output(self, j):
        """returns (g, dps or None, A_rel, B_rel, kbar), g as float array (dps
        None) or mpf list, kbar as float array"""
        m, K, Sig, C0 = self.m, self.K, self.Sig, self.C0
        if self.A0_d[j] == 0.0:
            return np.zeros(m), None, 0.0, 0.0, np.zeros(K)
        kap = self._kappa_bound(j)
        if kap <= 1e6:
            k = self.E_out[j]
            g = self._hlt_double(k, self.A0_d[j])
            kbar = self.E_in.T @ g
            return g, None, float(self.qw @ (k - kbar) ** 2) / self.A0_d[j], \
                float(g @ Sig @ g) / C0 ** 2, kbar
        dps = int(np.ceil(np.log10(kap))) + 20
        g1 = self._hlt_mp(j, dps)
        for _ in range(4):
            g = self._hlt_mp(j, dps + 20)
            gf = np.array([float(x) for x in g])
            st = float(np.sqrt(max(gf @ Sig @ gf, 0.0)))
            dv = abs(float(self._mp_dot(g1, self.c_mn, dps + 20)
                           - self._mp_dot(g, self.c_mn, dps + 20)))
            if dv <= 1e-10 * st:
                break
            g1, dps = g, dps + 20
        else:
            raise RuntimeError(f"output weight {j}: the HLT solve did not converge in "
                               f"precision up to {dps} digits (kappa bound {kap:.1e})")
        dd = dps + 20
        E, q, _, S = self._mp_setup(dd)
        with mpmath.workdps(dd):
            k = self._mp_rows([self.w_out[j]], [self.E_out[j]], dd)[0]
            A0 = mpmath.fsum(qj * x * x for qj, x in zip(q, k))
            kb = [mpmath.fsum(g[i] * E[i][jj] for i in range(m)) for jj in range(K)]
            A_rel = float(mpmath.fsum(qj * (x - y) ** 2 for qj, x, y in zip(q, k, kb)) / A0)
            B_rel = float(mpmath.fsum(g[i] * S[i][l] * g[l]
                                      for i in range(m) for l in range(m)) / C0 ** 2)
        return g, dd, A_rel, B_rel, np.array([float(x) for x in kb])

    # ------------------------------------------------------------------ #
    def estimate(self, c):
        """g.c for every output"""
        out = np.empty(self.p)
        for j, (g, dd) in enumerate(zip(self.g, self.digits)):
            out[j] = float(self._mp_dot(g, c, dd)) if dd is not None else float(g @ np.asarray(c, float))
        return out

    def kernel(self, j):
        """kbar_j = sum_i g_i e_i on the grid (formed at the working precision)"""
        return self._kbar[j].copy()
