#
#    JKS - Measurement database system
#    Copyright (C) 2024  Christoph Lehner (christoph.lehner@ur.de, https://github.com/lehner/jks)
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
import math, random, scipy.optimize, numpy, decimal, sys
import jks.distributions


#
# performs chi2 minimization of  chi2 = dX . iCov . dX   with  dX_i = em - x_i
#
# =>  chi2 = \sum_{i,j}  (f(x_i) - x_i) iCov_{ij} (f(x_j) - x_j)
#
# In eigenrepresentation:
#
# iCov_{ij} = 1/ln vn_i vn_j => chi2 = \sum_n dx_n^2 / ln
#
# with dx_n = \sum_i dX_i vn_i = \sum_i (em - x_i) vn_i
#
# => chi2 = \sum_{n} ( \sum_i (f(x_i) - x_i) vn_i )^2 (1/ln)
#
def ad(x, eps, i):
    return [x[j] if i != j else x[j] + eps for j in range(len(x))]


class fit:

    #
    # Data type
    #
    np_datatype = numpy.float64

    def __init__(self, mean, cov, r=None):
        if r == None:
            r = range(len(mean))
        self.r = r
        self.mean = [mean[i] for i in r]
        if type(cov) != list:
            cov = [[cov]]
        self.cov = numpy.matrix([[cov[i][j] for j in r] for i in r], self.np_datatype)

        eigenvalues, eigenvectors = numpy.linalg.eig(self.cov)
        idx = eigenvalues.argsort()

        self.ev = (eigenvalues[idx], eigenvectors[:, idx])
        self.nr = range(len(self.mean))

    def chi2_compute(self, ff, eigenvalues, verbose, pars):

        f = ff([numpy.float64(p) for p in pars])

        ev = self.ev
        mean = self.mean
        nr = self.nr

        res = 0.0

        if verbose:
            print("Chi2 Computation\n------------------------------------")
            print("P    = " + str(pars))
            for i in nr:
                print("f[%d] = %g, mean[%d] = %g" % (i, f[i], i, mean[i]))
            print("")

        for n in eigenvalues:

            sp = 0.0
            for i in nr:
                sp += (f[i] - mean[i]) * ev[1][i, n]

            if verbose:
                sev = "chi2_ev%d = %g  (%g / %g)  " % (
                    n,
                    sp * sp / ev[0][n],
                    sp * sp,
                    ev[0][n],
                )
                sev += " " * (70 - len(sev))
                sev += "[ "
                for i in nr:
                    sev += "%.3g " % ev[1][i, n]
                sev += "]"
                print(sev)

            res += sp * sp / ev[0][n]

        if verbose:
            print("\n chi2 = %.15g\n" % res)

        return res

    def fit(
        self,
        f,
        scipy_method,
        _guess,
        tolerance,
        maxiter,
        verbose,
        estimate_hessians,
        freeze_index=None,
        eigenvalues=None,
    ):

        if eigenvalues is None:
            eigenvalues = self.nr

        evs = self.ev[0].tolist()

        sev = [evs[i] for i in eigenvalues]
        condition_number = sev[len(sev) - 1] / sev[0]

        if freeze_index is None:
            guess = _guess
            freeze_guess = []
        else:
            guess = _guess[0:freeze_index]
            freeze_guess = _guess[freeze_index:]

        num = 0.0
        den = 0.0
        chi2 = 0.0
        dof = len(eigenvalues) - len(guess)

        # min
        minres = scipy.optimize.minimize(
            fun=lambda pars: self.chi2_compute(
                f, eigenvalues, verbose, numpy.array(pars.tolist() + freeze_guess)
            ),
            x0=guess,
            method=scipy_method,
            tol=tolerance,
            options={"maxiter": maxiter, "disp": verbose},
        )

        guess = _guess

        if verbose and minres.success == False:
            print("Fitter failed: " + minres.message)

        if verbose:
            print("")

        hessian_PP = None
        hessian_PM = None
        if minres.success:
            val = minres.x.tolist() + freeze_guess
            chi2 = float(self.chi2_compute(f, eigenvalues, verbose, val))
            if estimate_hessians != 0.0:
                estimate_hessians = numpy.array(
                    estimate_hessians, dtype=numpy.longdouble
                )
                mean0 = self.mean
                hessian_PP = numpy.array(
                    [[0.0 for j in range(len(guess))] for i in range(len(guess))],
                    dtype=numpy.longdouble,
                )
                hessian_PM = numpy.array(
                    [[0.0 for j in range(len(mean0))] for i in range(len(guess))],
                    dtype=numpy.longdouble,
                )
                for i in range(len(guess)):
                    for j in range(len(guess)):
                        x_pp = self.chi2_compute(
                            f,
                            eigenvalues,
                            verbose,
                            ad(ad(val, estimate_hessians, j), estimate_hessians, i),
                        )
                        x_pm = self.chi2_compute(
                            f,
                            eigenvalues,
                            verbose,
                            ad(ad(val, -estimate_hessians, j), estimate_hessians, i),
                        )
                        x_mp = self.chi2_compute(
                            f,
                            eigenvalues,
                            verbose,
                            ad(ad(val, estimate_hessians, j), -estimate_hessians, i),
                        )
                        x_mm = self.chi2_compute(
                            f,
                            eigenvalues,
                            verbose,
                            ad(ad(val, -estimate_hessians, j), -estimate_hessians, i),
                        )
                        hessian_PP[i][j] = (
                            (x_pp + x_mm - x_mp - x_pm) / 4.0 / estimate_hessians**2.0
                        )
                    for j in range(len(mean0)):
                        self.mean = ad(mean0, estimate_hessians, j)
                        x_pp = self.chi2_compute(
                            f, eigenvalues, verbose, ad(val, estimate_hessians, i)
                        )
                        x_pm = self.chi2_compute(
                            f, eigenvalues, verbose, ad(val, -estimate_hessians, i)
                        )
                        self.mean = ad(mean0, -estimate_hessians, j)
                        x_mp = self.chi2_compute(
                            f, eigenvalues, verbose, ad(val, estimate_hessians, i)
                        )
                        x_mm = self.chi2_compute(
                            f, eigenvalues, verbose, ad(val, -estimate_hessians, i)
                        )
                        self.mean = mean0
                        hessian_PM[i][j] = (
                            (x_pp + x_mm - x_mp - x_pm) / 4.0 / estimate_hessians**2.0
                        )
                self.mean = mean0

        return {
            "val": minres.x.tolist(),
            "success": minres.success,
            "chi2": chi2,
            "dof": dof,
            "range": self.r,
            "p_right_tail": stats.distributions.p_value_right_tail(chi2, dof),
            "p": stats.distributions.p_value(chi2, dof),
            "eigenspace": eigenvalues,
            "condition_number": condition_number,
            "eigenvalues": evs,
            "nfev": minres.nfev,
            "hessian_PP": hessian_PP,
            "hessian_PM": hessian_PM,
        }
