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
#
# Statistical covariance of delete-bin jackknife resamples, estimated from the
# stored delete-one blocks (nothing binned is stored).
#
# Streams: configuration tag "<stream>-<label>", stream = prefix before the last "-"
# (a Markov chain).  Bins never cross streams.  Populations: the streams of one
# jackknife.  By default every stream is its own population (a merge of separately
# imported ensembles); JKS_BIN_POOL declares streams imported together into one
# jackknife (jks_create_correlator_from_corrfile db ensA patA ensB patB).
#
# In a population with N configurations and deviations d_i = b_i - orig, deleting the m
# configurations of a bin B shifts the estimate by
#
#   D_B = (N - 1) / (N_kept - m) sum_{i in B} d_i
#
# (exact for primary data, leading order for derived quantities), N_kept = configurations
# in bins.  Covariance per population (cov() convention, sum over its Nb bins):
#
#   single:   N_kept/N sum_B (D_B - <D>)(D_B - <D>)^T, bins of every stream from its first
#             configuration, the trailing n mod m of each stream dropped; N_kept/N refers
#             the error of the mean of the kept configurations to the mean of all N
#   offsets:  average of single over the m starting offsets s = 0..m-1 (the first s
#             configurations of every stream dropped)
#   overlap:  moving-block jackknife, all W windows of m consecutive configurations within
#             the streams, N / (m W) sum_j D_j D_j^T  (= N/(N-m) times the bias-free estimate)
#
# m = 1 is the ordinary jackknife.  Populations add.  The "info" convention (jks_info)
# scales each population by (Nb - 1)/Nb (overlap: (N - m)/N).
#
# Setting: JKS_BIN overrides the bin argument, JKS_BIN_MODE the mode argument.
#   JKS_BIN=2                         every stream
#   JKS_BIN=ens1:2,ens2:4,'48VF*:3'   fnmatch patterns, first match wins, others 1
#   JKS_BIN='ens1:3,*:2'              explicit default
#   JKS_BIN_POOL='ensA+ensB,C-s*'     populations of several streams ('+' joins patterns)
#
import fnmatch, os, sys
import numpy as np

MODES = ("offsets", "single", "overlap")

_reported = set()
_checked = set()
_warned = set()
_streams_cache = {}


def parse(spec):
    # spec: int, "m", "pat:m,...", dict {pat: m} or list of (pat, m) -> list of (pat, m)
    if isinstance(spec, (int, np.integer)):
        entries = [("*", int(spec))]
    elif isinstance(spec, dict):
        entries = list(spec.items())
    elif isinstance(spec, str):
        entries = []
        for e in spec.split(","):
            e = e.strip()
            if e == "":
                raise ValueError("JKS_BIN: empty entry in '%s'" % spec)
            pat, sep, m = e.rpartition(":")
            entries.append((pat.strip() if sep else "*", m.strip()))
    else:
        entries = list(spec)
    res = []
    for pat, m in entries:
        try:
            mi = int(m) if isinstance(m, (int, np.integer)) else int(str(m), 10)
        except ValueError:
            raise ValueError("JKS_BIN: bin size '%s' of '%s' is not an integer" % (m, pat))
        if mi < 1:
            raise ValueError("JKS_BIN: bin size %d of '%s' must be >= 1" % (mi, pat))
        if pat == "":
            raise ValueError("JKS_BIN: empty pattern")
        res.append((pat, mi))
    return res


def parse_pool(spec):
    # "a+b,c*" -> [("a", "b"), ("c*",)]
    res = []
    for e in (spec or "").split(","):
        e = e.strip()
        if e == "":
            continue
        pats = tuple(p.strip() for p in e.split("+"))
        if any(p == "" for p in pats):
            raise ValueError("JKS_BIN_POOL: empty pattern in '%s'" % e)
        res.append(pats)
    return res


def setting(bin=None, mode=None):
    # active (entries, mode, pools) or None; the environment overrides the arguments
    spec = os.environ.get("JKS_BIN", bin)
    mode = os.environ.get("JKS_BIN_MODE", mode) or "offsets"
    if mode not in MODES:
        raise ValueError("JKS_BIN_MODE: '%s' is not one of %s" % (mode, ", ".join(MODES)))
    if spec is None or (isinstance(spec, str) and spec.strip() == ""):
        return None
    return parse(spec), mode, parse_pool(os.environ.get("JKS_BIN_POOL"))


def stream(tag):
    return tag.rsplit("-", 1)[0] if "-" in tag else ""


def streams(tags):
    # stream -> indices of its configurations among the non-"!" tags, in database order
    key = tuple(tags)
    if key not in _streams_cache:
        s = {}
        for i, t in enumerate([t for t in tags if t[0] != "!"]):
            s.setdefault(stream(t), []).append(i)
        _streams_cache[key] = dict((k, np.array(v)) for k, v in s.items())
    return _streams_cache[key]


def populations(names, pools):
    # list of lists of streams: the first pool entry with a pattern matching a stream takes
    # every stream matching one of its patterns; other streams are alone
    out, done = [], set()
    for name in names:
        if name in done:
            continue
        pop = [name]
        for pats in pools:
            if any(fnmatch.fnmatchcase(name, p) for p in pats):
                pop = [s for s in names if s not in done and any(fnmatch.fnmatchcase(s, p) for p in pats)]
                break
        done.update(pop)
        out.append(pop)
    return out


def lookup(entries, name):
    # bin size and whether an entry matched
    for pat, m in entries:
        if fnmatch.fnmatchcase(name, pat):
            return m, True
    return 1, False


def _name(s):
    return s if s != "" else '""'


def _warn(key, msg):
    if key in _warned:
        return
    _warned.add(key)
    sys.stderr.write("# WARNING %s\n" % msg)
    sys.stderr.flush()


def _check(entries, pools, strs):
    key = (tuple(entries), tuple(pools), tuple(sorted(strs)))
    if key in _checked:
        return
    _checked.add(key)
    fallthrough = [s for s in strs if not lookup(entries, s)[1]]
    unmatched = [pat for pat, m in entries if not any(fnmatch.fnmatchcase(s, pat) for s in strs)]
    if fallthrough and unmatched:
        _warn(key + ("bin",), "JKS_BIN: no stream matches %s; unbinned: %s" % (
            ", ".join("'%s'" % p for p in unmatched), ", ".join(_name(s) for s in fallthrough)))
    for pats in pools:
        hit = [p for p in pats if any(fnmatch.fnmatchcase(s, p) for s in strs)]
        if hit and len(hit) < len(pats):
            _warn(key + pats, "JKS_BIN_POOL: in pool '%s' no stream matches %s" % (
                "+".join(pats), ", ".join("'%s'" % p for p in pats if p not in hit)))


def _fluctuates(d, mean):
    # elements on which the deviations exceed rounding (1e-12 of the value)
    return np.sqrt((d * d).sum(axis=0)) > 1e-12 * np.abs(mean)


def _plausible(pop, ds, mean):
    # per-stream sums of the deviations: zero (to rounding) for a primary quantity of a
    # separate jackknife, of the order of bias/error for a derived one; for streams of one
    # jackknife of the order of the difference of the stream means in units of the error
    r = []
    for d in ds:
        with np.errstate(divide="ignore", invalid="ignore"):
            x = np.abs(d.sum(axis=0)) / np.sqrt((d * d).sum(axis=0))
        x = x[np.isfinite(x) & _fluctuates(d, mean)]
        r.append(x)
    if len(pop) == 1:
        if len(r[0]) and r[0].max() > 1.0:
            _warn(("pooled", pop[0]), "JKS_BIN_POOL: the deviations of stream %s do not sum to zero; "
                  "it looks like part of a jackknife over several streams (declare them in JKS_BIN_POOL)" % _name(pop[0]))
    else:
        for name, x in zip(pop, r):
            if len(x) and x.max() < 1e-8:
                _warn(("separate", name, tuple(pop)), "JKS_BIN_POOL: the deviations of stream %s sum to zero; "
                      "it looks like a separate jackknife, not part of pool %s" % (_name(name), "+".join(map(_name, pop))))


def _report(name, n, m, matched, mode, nb, pop):
    key = (name, n, m, mode if m > 1 else None, matched, tuple(pop))
    if key in _reported:
        return
    _reported.add(key)
    if not matched:
        what = "bin 1 (no match)"
    elif m == 1:
        what = "bin 1"
    else:
        what = "bin %d (%s bins, %s)" % (m, nb, mode)
    p = " (pool %s)" % "+".join(map(_name, pop)) if len(pop) > 1 else ""
    sys.stderr.write("# JKS_BIN %s%s: %d configs, %s\n" % (_name(name), p, n, what))
    sys.stderr.flush()


def _range(xs):
    xs = sorted(set(xs))
    return str(xs[0]) if len(xs) == 1 else "%d-%d" % (xs[0], xs[-1])


def _population(ds, m, mode, convention, label):
    # rows R (R^T R = covariance) of one population of streams with deviations ds; also
    # the number of bins of every stream (for the report)
    ns = [len(d) for d in ds]
    N = sum(ns)
    if m == 1:
        d = np.vstack(ds)
        r = d - d.mean(axis=0)
        if convention == "info":
            r = r * np.sqrt((N - 1) / N)
        return r, [str(n) for n in ns]
    if mode == "overlap":
        D = []
        for d in ds:
            if len(d) < m:
                raise ValueError("JKS_BIN: %d configs of stream %s are fewer than the bin size %d" % (len(d), label, m))
            c = np.cumsum(np.vstack([np.zeros((1, d.shape[1])), d]), axis=0)
            D.append(c[m:] - c[:-m])
        D = (N - 1) / (N - m) * np.vstack(D)
        if N < 2 * m:
            raise ValueError("JKS_BIN: %d configs of %s leave fewer than 2 bins of %d" % (N, label, m))
        r = D * np.sqrt(N / (m * len(D)))
        if convention == "info":
            r = r * np.sqrt((N - m) / N)
        return r, [str(n - m + 1) for n in ns]
    offs = range(m) if mode == "offsets" else [0]
    r = []
    for s in offs:
        nbs = [(n - s) // m for n in ns]
        if min(nbs) < 1 or sum(nbs) < 2:
            raise ValueError("JKS_BIN: %s configs of %s leave fewer than 2 bins of %d" % ("+".join(map(str, ns)), label, m))
        S = np.vstack([d[s : s + nb * m].reshape(nb, m, -1).sum(axis=1) for d, nb in zip(ds, nbs)])
        nk = sum(nbs) * m
        D = (N - 1) / (nk - m) * S
        # error of the mean of the nk kept configurations, scaled to the mean of all N
        rb = (D - D.mean(axis=0)) * np.sqrt(nk / N / len(offs))
        if convention == "info":
            rb = rb * np.sqrt((len(D) - 1) / len(D))
        r.append(rb)
    return np.vstack(r), [_range((n - s) // m for s in offs) for n in ns]


def rows(orig, blocks, tags, bin=None, mode=None, convention="cov", report=True):
    # matrix R with stat covariance R^T R, or None if binning is not active
    st = setting(bin, mode)
    if st is None:
        return None
    entries, mode, pools = st
    mean = np.atleast_1d(np.asarray(orig, dtype=np.float64)).ravel()
    B = np.asarray(blocks, dtype=np.float64).reshape(len(tags), len(mean))
    S = B[np.array([t[0] != "!" for t in tags], dtype=bool)] - mean
    strs = streams(tags)
    if report:
        _check(entries, pools, list(strs))
    out = []
    for pop in populations(list(strs), pools):
        ds = [S[strs[name]] for name in pop]
        look = [lookup(entries, name) for name in pop]
        ms = sorted(set(m for m, matched in look))
        label = "stream %s" % _name(pop[0]) if len(pop) == 1 else "pool %s" % "+".join(map(_name, pop))
        if len(ms) > 1:
            raise ValueError("JKS_BIN: the streams of %s have different bin sizes %s" % (label, ms))
        if not np.any(_fluctuates(np.vstack(ds), mean)):
            continue  # the tag does not depend on this population (beyond rounding)
        r, nbs = _population(ds, ms[0], mode, convention, label)
        if report:
            _plausible(pop, ds, mean)
            for name, d, (m, matched), nb in zip(pop, ds, look, nbs):
                if np.any(_fluctuates(d, mean)):
                    _report(name, len(d), m, matched, mode, nb, pop)
        out.append(r)
    if len(out) == 0:
        return np.zeros((0, len(mean)))
    return np.vstack(out)


def describe(tags, bin=None, mode=None):
    # ([(stream, configs, bin size, matched, population)], mode) of a database, or None if
    # binning is not active
    st = setting(bin, mode)
    if st is None:
        return None
    entries, mode, pools = st
    strs = streams(tags)
    _check(entries, pools, list(strs))
    res = []
    for pop in populations(list(strs), pools):
        for name in pop:
            res.append((name, len(strs[name])) + lookup(entries, name) + (pop,))
    return res, mode


def cov(orig, blocks, tags, bin=None, mode=None, convention="cov"):
    # binned stat covariance (list of lists) or None if binning is not active
    R = rows(orig, blocks, tags, bin, mode, convention)
    if R is None:
        return None
    return (R.T @ R).tolist()
