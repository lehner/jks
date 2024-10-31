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
import math, numpy
from jks.resamples import resamples
from jks.measurements import measurements, jackknife
from jks.fit import fit
import jks.corrIO


def qfit(
    mn,
    cv,
    r,
    fnc,
    guess,
    tolerance=1e-7,
    maxiter=100,
    verbose=False,
    simplex=True,
    estimate_hessians=0.0,
    freeze_index=None,
):
    return fit(mn, cv, r).fit(
        lambda pars: [fnc(i, pars) for i in r],
        "Nelder-Mead",
        guess,
        tolerance,
        maxiter,
        verbose,
        estimate_hessians,
        freeze_index,
    )


# write helper function
def write(fn, arr):
    f = open(fn, "w")
    for row in arr:
        for col in row:
            f.write(str(col))
            f.write(" ")
        f.write("\n")
    f.close()


# format value and error
def gformat(value, errors, etags, times="\\times"):
    err_digits = 2
    error = max([math.fabs(errors[e]) for e in etags])
    val_digits_left_of_period = int(
        math.floor(1e-10 + math.log(math.fabs(value)) / math.log(10.0)) + 1
    )
    if error == 0.0:
        return "%.15g" % (value)
    else:
        err_digits_left_of_period = int(
            math.floor(1e-10 + math.log(error) / math.log(10.0)) + 1
        )

    digits_left_of_period = max([val_digits_left_of_period, err_digits_left_of_period])
    digits_right_of_period = err_digits_left_of_period - err_digits
    if digits_left_of_period < 0:
        digits_shift = -digits_left_of_period + 1
    elif digits_right_of_period > 0:
        digits_shift = -digits_right_of_period
    else:
        digits_shift = 0
    value *= 10**digits_shift
    errors_rescaled = dict(
        [(e, errors[e] * 10**-digits_right_of_period) for e in etags]
    )
    digits_left_of_period += digits_shift
    digits_right_of_period += digits_shift

    s = ("{0:%d.%df}" % (digits_left_of_period, -digits_right_of_period)).format(value)
    for e in etags:
        if errors[e] == 0.0:
            continue
        if digits_right_of_period == -1:
            s = s + "(" + "{0:02.1f}".format(errors_rescaled[e] / 10.0) + ")"
        else:
            s = s + "(" + "{0:02.0f}".format(errors_rescaled[e]) + ")"
        if e != "":
            s = s + "_{%s}" % e
    if digits_shift != 0:
        if digits_shift == -1:
            s += " %s 10" % times
        else:
            s += " %s 10^{%d}" % (times, -digits_shift)
    return s


def format(value, error, error_ndigits=None):
    exp_digits = 0
    err_extr_digits = 0
    if error_ndigits != None and error_ndigits < 0:
        err_extr_digits = -error_ndigits
        error_ndigits = None
    if error_ndigits == None:
        error_ndigits = (
            int(math.floor(-math.log(error) / math.log(10))) + 1 + err_extr_digits
        )
        if error_ndigits < 0:
            error *= 10.0**error_ndigits
            value *= 10.0**error_ndigits
            exp_digits = -error_ndigits
            error_ndigits = 0
    value_rescaled = round(value * math.pow(10, error_ndigits)) * math.pow(
        10, -error_ndigits
    )
    error_rescaled = int(round(error * math.pow(10, error_ndigits)))
    s = (
        ("{:." + str(error_ndigits) + "f}").format(value_rescaled)
        + "("
        + str(error_rescaled)
        + ")"
    )
    if exp_digits > 0:
        if exp_digits == 1:
            s += " x 10"
        else:
            s += " x 10^%d" % exp_digits
    return s


#
def write_confidence_band(f, pars, pars_cov, eps, xrang, outfn):
    # f(x,pars) = f(x,pars) +- sqrt( (df/dpars_i) (x,pars) pars_cov_ij (df/dpars_j) (x,pars) )
    fout = open(outfn, "wt")
    for x in xrang:
        fx = f(x, pars)
        dfx = [
            (
                f(x, [pars[i] + eps if i == j else pars[i] for i in range(len(pars))])
                - f(x, pars)
            )
            / eps
            for j in range(len(pars))
        ]
        var = 0.0
        for i in range(len(pars)):
            for j in range(len(pars)):
                var += dfx[i] * dfx[j] * pars_cov[i][j]

        if type(x) == type(0.0):
            pos = "%g" % x
        elif type(x) == type(0):
            pos = "%d" % x
        elif type(x) == type([]):
            pos = str(x)

        fout.write("%s %.15g %.15g\n" % (pos, fx, math.sqrt(var)))

    fout.close()


def gaussian_noise(cov, n):
    r = range(len(cov))
    np_datatype = numpy.float64
    cov = numpy.matrix([[cov[i][j] for j in r] for i in r], np_datatype)

    # check if symmetric real matrix
    assert numpy.isrealobj(cov)
    assert numpy.allclose(cov, cov.T)

    eigenvalues, eigenvectors = numpy.linalg.eigh(cov)
    idx = eigenvalues.argsort()

    evals, evecs = eigenvalues[idx], eigenvectors[:, idx].tolist()
    largest = sorted(evals)[-1]
    evals[numpy.abs(evals) < 1e-15 * largest] = (1e-100) * largest
    evals = evals.tolist()
    evr = [
        numpy.random.normal(0.0, math.sqrt(evals[i]), n).tolist()
        for i in range(len(evals))
    ]
    return [[sum([evr[i][j] * evecs[l][i] for i in r]) for l in r] for j in range(n)]


def draw(m, cov, n):
    es = gaussian_noise(cov, n)
    return [[m[i] + e[i] for i in range(len(m))] for e in es]
