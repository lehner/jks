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
# Vectorized error analysis of a single tag, no GUI dependencies.
#
# Conventions (see AGENTS.md):
#   "info": (N-1)/N sum_b (b - <b>)^2, the bias-free errors printed by jks_info
#   "cov":  sum_b (b - <b>)^2, the convention of jk.cov() used by downstream fits
# A variation v contributes d d^T with d = block_v - mean in both conventions.
#
import fnmatch, re
import numpy as np

CONVENTIONS = ("info", "cov")


class tag_stats:
    def __init__(self, orig, blocks, tags, convention="info"):
        assert convention in CONVENTIONS
        self.shape = np.shape(orig)
        self.mean = np.atleast_1d(np.asarray(orig, dtype=np.float64)).ravel()
        n = len(self.mean)
        B = np.asarray(blocks, dtype=np.float64).reshape(len(tags), n)
        is_var = np.array([t[0] == "!" for t in tags], dtype=bool)
        S = B[~is_var]
        self.n_stat = len(S)
        if self.n_stat > 0:
            S = S - self.mean  # exact zeros for tags constant over blocks
            self.D = S - S.mean(axis=0)
            if convention == "info":
                self.D *= np.sqrt((self.n_stat - 1) / self.n_stat)
        else:
            self.D = np.zeros((0, n))
        self.shifts = dict(
            (tags[i][1:], B[i] - self.mean) for i in np.flatnonzero(is_var)
        )

    def vars(self):
        # variations that shift this tag
        return [v for v, d in self.shifts.items() if np.any(d != 0.0)]

    def stat_err(self):
        return np.sqrt(np.sum(self.D**2, axis=0))

    def var_err(self, v):
        return np.abs(self.shifts[v])

    def sys_err(self):
        s = np.zeros_like(self.mean)
        for d in self.shifts.values():
            s += d**2
        return np.sqrt(s)

    def tot_err(self):
        return np.sqrt(self.stat_err() ** 2 + self.sys_err() ** 2)

    def cov(self, which="total"):
        # which: "stat", "sys", "total" or a variation name
        if which == "stat":
            return self.D.T @ self.D
        if which in self.shifts:
            d = self.shifts[which]
            return np.outer(d, d)
        c = np.zeros((len(self.mean), len(self.mean)))
        for d in self.shifts.values():
            c += np.outer(d, d)
        if which == "sys":
            return c
        assert which == "total"
        return c + self.D.T @ self.D

    def cor(self, which="total"):
        c = self.cov(which)
        s = np.sqrt(np.diag(c))
        with np.errstate(divide="ignore", invalid="ignore"):
            r = c / np.outer(s, s)
        r[~np.isfinite(r)] = np.nan
        return r


def derived(orig, blocks, fnc):
    # apply fnc to the central value and every block, like res.apply
    m = np.atleast_1d(np.asarray(orig, dtype=np.float64)).ravel()
    B = np.asarray(blocks, dtype=np.float64).reshape(len(blocks), len(m))
    with np.errstate(divide="ignore", invalid="ignore"):
        return fnc(m[None, :])[0], fnc(B)


def effective_mass_log(x):
    # m(t) = log(c(t) / c(t+1)), rows are samples
    return np.log(x[:, :-1] / x[:, 1:])


def match(keys, pattern):
    # fnmatch; a pattern without wildcards matches as a substring
    pattern = pattern.strip()
    if pattern == "":
        return list(keys)
    if not any(c in pattern for c in "*?["):
        pattern = "*" + pattern + "*"
    return [k for k in keys if fnmatch.fnmatchcase(k, pattern)]


# ---- fit bands ----
#
# jks_fit stores for every fit range j the parameters p, followed by
# [p-value, chi2, dof, npar] if JKS_PVAL was set, and the fitted data as
# <fit>.<tag>.input.<j> (nan outside the range).


def fit_inputs(keys, fit):
    # data tag -> sorted range indices, from the .input tags of a fit
    out = {}
    for k in keys:
        if k.startswith(fit + ".") and ".input." in k:
            tag, j = k[len(fit) + 1 :].rsplit(".input.", 1)
            if j.isdigit():
                out.setdefault(tag, []).append(int(j))
    return dict((t, sorted(js)) for t, js in out.items())


def fit_tags(keys):
    keys = list(keys)
    return [k for k in keys if fit_inputs(keys, k)]


def fit_parameters(res, fit, nranges, j):
    # samples (central value first, then all blocks) of range j, and whether
    # the last four entries are p-value, chi2, dof, npar
    jk = res.get(fit)
    P = np.vstack([np.atleast_1d(np.asarray(jk.orig, dtype=np.float64))] +
                  [np.atleast_1d(np.asarray(b, dtype=np.float64)) for b in jk.blocks])
    stride = P.shape[1] // nranges
    assert stride * nranges == P.shape[1], "fit %s: %d numbers do not split into %d ranges" % (fit, P.shape[1], nranges)
    P = P[:, j * stride : (j + 1) * stride]
    tail = P[:, -4:] if stride >= 5 else None
    pval = tail is not None and np.all(tail == tail[0]) and tail[0, 3] == int(tail[0, 3]) and \
        0 < tail[0, 3] <= stride - 4 and tail[0, 2] == int(tail[0, 2]) and 0.0 <= tail[0, 0] <= 1.0
    return P, bool(pval)


def fit_function(src):
    # same signature and names as in jks_fit
    import math
    return eval("lambda x,p,r: " + src, {"math": math, "np": np, "numpy": np})


def fit_band(res, fit, src, nranges, j, xs, convention="cov", method="jackknife", meff=False):
    # f(x) on the grid xs with statistical and total errors
    #   jackknife: f evaluated with every block's parameters (and r[tag] of that block)
    #   linear:    as jks.write_confidence_band, g^T C g with forward differences (eps = 1e-8)
    # meff: log(f(x)/f(x+1)) instead of f(x)
    f = fit_function(src)
    g = (lambda x, p, r: np.log(f(x, p, r) / f(x + 1, p, r))) if meff else f
    P, pval = fit_parameters(res, fit, nranges, j)
    rt = sorted(set(re.findall(r"""r\[\s*['"]([^'"]+)['"]\s*\]""", src)))
    R = [dict((t, np.asarray(res.get(t).orig if s == 0 else res.get(t).blocks[s - 1])) for t in rt)
         for s in range(len(P))]
    xs = np.asarray(xs, dtype=np.float64)
    with np.errstate(all="ignore"):
        if method == "jackknife":
            Y = np.array([[g(x, P[s], R[s]) for x in xs] for s in range(len(P))], dtype=np.float64)
            s = tag_stats(Y[0], Y[1:], res.tags, convention)
            return s.mean, s.stat_err(), s.tot_err()
        assert method == "linear"
        npar = P.shape[1] - (4 if pval else 0)
        ps = tag_stats(P[0, :npar], P[1:, :npar], res.tags, convention)
        eps = 1e-8
        y = np.array([g(x, P[0], R[0]) for x in xs], dtype=np.float64)
        G = np.zeros((len(xs), npar))
        for i in range(npar):
            p = P[0].copy()
            p[i] += eps
            G[:, i] = (np.array([g(x, p, R[0]) for x in xs]) - y) / eps
        err = lambda C: np.sqrt(np.einsum("ki,ij,kj->k", G, C, G))
        return y, err(ps.cov("stat")), err(ps.cov("total"))
