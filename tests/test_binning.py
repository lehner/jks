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
# Delete-bin jackknife covariance (jks.binning, JKS_BIN) against a brute-force
# jackknife of binned measurements, on a database of two streams.
#
import os
import numpy as np
import pytest

import jks
import jks.corrIO as corrIO
from jks import binning
from conftest import run, correlators

NA, NB = 24, 17  # configurations of the two streams


def corrfiles(tmp_path_factory):
    # corrfiles of streams ensA (24 configs) and ensB (17 configs); x[s] = C_a_a.r per config
    d = tmp_path_factory.mktemp("streams")
    x = {}
    for s, n, seed in (("ensA", NA, 1), ("ensB", NB, 7)):
        os.makedirs(str(d / s))
        cs = correlators(seed)[:n]
        for c, m in enumerate(cs):
            w = corrIO.writer(str(d / s / ("c.%d.bin" % (100 + 10 * c))))
            for tag, v in m.items():
                w.write(tag, list(v))
            w.close()
        x[s] = np.array([np.real(m["C_a_a"]) for m in cs])
    return d, x


@pytest.fixture(scope="module")
def pooled(tmp_path_factory):
    # the two streams imported together: one jackknife over both
    d, x = corrfiles(tmp_path_factory)
    db = str(d / "pooled.jks")
    run("jks_create_correlator_from_corrfile", db, "ensA", str(d / "ensA" / "c.*.bin"), "ensB", str(d / "ensB" / "c.*.bin"))
    return db, x


@pytest.fixture(scope="module")
def two(tmp_path_factory):
    # the two streams imported separately and merged: one jackknife per stream
    d, x = corrfiles(tmp_path_factory)
    pats = []
    for s in x:
        pats += [s, str(d / (s + ".jks"))]
        run("jks_create_correlator_from_corrfile", pats[-1], s, str(d / s / "c.*.bin"))
    db = str(d / "two.jks")
    run("jks_tagged_merge", db, *pats)  # one jackknife per stream, as in a merge of ensembles
    run("jks_add", db, "C_a_a.r", "r['ensA/C_a_a.r'] + r['ensB/C_a_a.r']")  # varies in both streams
    return db, x


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("JKS_BIN", raising=False)
    monkeypatch.delenv("JKS_BIN_MODE", raising=False)
    monkeypatch.delenv("JKS_BIN_POOL", raising=False)


def brute(x, m, s, convention="cov"):
    # jackknife of the means of bins of m measurements, bins within each stream of the list x
    # (or the single stream x) from configuration s on, scaled by N_kept/N to the mean of all
    xs = x if isinstance(x, list) else [x]
    N = sum(len(v) for v in xs)
    y = np.vstack([v[s : s + ((len(v) - s) // m) * m].reshape(-1, m, v.shape[1]).mean(axis=1) for v in xs])
    nb = len(y)
    th = np.array([(y.sum(axis=0) - yb) / (nb - 1) for yb in y])
    d = th - th.mean(axis=0)
    c = d.T @ d * nb * m / N
    return c * (nb - 1) / nb if convention == "info" else c


def brute_overlap(x, m):
    # moving-block jackknife, windows within each stream, N/(m W) sum_j D_j D_j^T
    xs = x if isinstance(x, list) else [x]
    N = sum(len(v) for v in xs)
    mu = np.vstack(xs).mean(axis=0)
    D = np.array([(N * mu - v[j : j + m].sum(axis=0)) / (N - m) - mu for v in xs for j in range(len(v) - m + 1)])
    return N / (m * len(D)) * D.T @ D


def rel(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return np.abs(a - b).max() / np.abs(b).max()


def test_bin1_is_cov(two):
    db, x = two
    jk = jks.resamples(db).get("C_a_a.r")
    assert rel(jk.cov(bin=1), jk.cov()) < 1e-12
    assert rel(jk.cov(bin="*:1", mode="overlap"), jk.cov()) < 1e-12
    assert jk.cov() == jk.cov(bin=None)


@pytest.mark.parametrize("mode", ["single", "offsets", "overlap"])
@pytest.mark.parametrize("m", [2, 3, 5])
def test_exact_on_primary_data(two, m, mode):
    db, x = two
    jk = jks.resamples(db).get("C_a_a.r")
    if mode == "overlap":
        ref = sum(brute_overlap(x[s], m) for s in x)
    else:
        offs = range(m) if mode == "offsets" else [0]
        ref = sum(np.mean([brute(x[s], m, o) for o in offs], axis=0) for s in x)
    assert rel(jk.cov(bin=m, mode=mode), ref) < 1e-10


def test_per_stream_and_env_override(two, monkeypatch):
    db, x = two
    jk = jks.resamples(db).get("C_a_a.r")
    ref = brute(x["ensA"], 3, 0) + brute(x["ensB"], 1, 0)
    assert rel(jk.cov(bin="ensA:3", mode="single"), ref) < 1e-10
    assert rel(jk.cov(bin="en?A:3,*:1", mode="single"), ref) < 1e-10
    monkeypatch.setenv("JKS_BIN", "ensA:3")
    monkeypatch.setenv("JKS_BIN_MODE", "single")
    assert rel(jk.cov(bin=4, mode="overlap"), ref) < 1e-10
    # variations are not binned
    jk = jk.addvar("shift", np.array(jk.mean()) * 1.01, "test")
    sys_ref = np.array(jk.tcov()) - np.array(jk.cov())
    assert np.allclose(np.array(jk.tcov(bin=2)) - np.array(jk.cov(bin=2)), sys_ref, rtol=1e-12, atol=0)


def test_parse():
    assert binning.parse("2") == [("*", 2)]
    assert binning.parse(3) == [("*", 3)]
    assert binning.parse("a-0:2, b*:4") == [("a-0", 2), ("b*", 4)]
    for bad in ("a:x", "a:0", "a:2,", "a:2.5", ":2"):
        with pytest.raises(ValueError):
            binning.parse(bad)


def test_info_binned(two):
    # jks_info prints the bias-free (Nb-1)/Nb convention per stream
    db, x = two
    ref = brute(x["ensA"], 2, 0, "info") + brute(x["ensB"], 2, 0, "info")
    p = run("jks_info", db, "C_a_a.r", extra_env={"JKS_BIN": "2", "JKS_BIN_MODE": "single"})
    stat = np.array([float(l.split()[2]) for l in p.stdout.splitlines() if l[0].isdigit()])
    assert rel(stat, np.sqrt(np.diag(ref))) < 1e-12


def test_reporting_and_typo_warning(two):
    db, x = two
    out = run("jks_info", db, "C_a_a.r", "3", extra_env={"JKS_BIN": "ensA:2,ensC:3"}).stdout
    assert out.count("# JKS_BIN ensA: 24 configs, bin 2 (11-12 bins, offsets)") == 1
    assert out.count("# JKS_BIN ensB: 17 configs, bin 1 (no match)") == 1
    assert "# WARNING JKS_BIN: no stream matches 'ensC'; unbinned: ensB" in out
    # an explicit default silences the warning
    out = run("jks_info", db, "C_a_a.r", "3", extra_env={"JKS_BIN": "ensA:2,ensC:3,*:1"}).stdout
    assert "WARNING" not in out and "# JKS_BIN ensB: 17 configs, bin 1\n" in out
    # overview lists the streams
    out = run("jks_info", db, extra_env={"JKS_BIN": "ensB:2"}).stdout
    assert "- stream ensA: 24 configs, bin 1 (no match)" in out and "- stream ensB: 17 configs, bin 2" in out
    # no output without JKS_BIN
    assert "JKS_BIN" not in run("jks_info", db, "C_a_a.r").stdout


def test_errors(two, db):
    db2, x = two
    p = run("jks_info", db2, "C_a_a.r", check=False, extra_env={"JKS_BIN": "ensB:9"})
    assert p.returncode == 1 and "ERROR: JKS_BIN: 17 configs of stream ensB leave fewer than 2 bins of 9" in p.stdout
    p = run("jks_info", db2, "C_a_a.r", check=False, extra_env={"JKS_BIN": "ensB:x"})
    assert p.returncode == 1 and "ERROR: JKS_BIN" in p.stdout
    p = run("jks_info", db2, "C_a_a.r", check=False, extra_env={"BIN": "2"})
    assert p.returncode == 1 and "use JKS_BIN" in p.stdout
    p = run("jks_set_variance", db, "C", "3", "0.1", check=False, extra_env={"JKS_BIN": "2"})
    assert p.returncode == 1 and "ERROR" in p.stdout


def test_fit_uses_binned_cov(db):
    # jks_fit weights with the binned covariance; the fit runs and stores a result
    run("jks_fit", db, "C", "range(4,12)", "p[0]*math.exp(-p[1]*x)", "[1.0,0.45]", "fit", extra_env={"JKS_BIN": "2"})
    res = jks.resamples(db)
    assert "fit" in res.set and np.all(np.isfinite(res.get("fit").mean()))


@pytest.mark.parametrize("mode", ["single", "offsets", "overlap"])
@pytest.mark.parametrize("m", [1, 2, 3, 5])
def test_pooled_exact(pooled, m, mode, monkeypatch):
    # one jackknife over both streams: bins within the streams, jackknife over all bins
    db, x = pooled
    monkeypatch.setenv("JKS_BIN_POOL", "ensA+ensB")
    jk = jks.resamples(db).get("C_a_a.r")
    xs = [x["ensA"], x["ensB"]]
    if mode == "overlap":
        ref = brute_overlap(xs, m)
    else:
        offs = range(m) if mode == "offsets" else [0]
        ref = np.mean([brute(xs, m, o) for o in offs], axis=0)
    assert rel(jk.cov(bin=m, mode=mode), ref) < 1e-10
    if m == 1:
        assert rel(jk.cov(bin=1), jk.cov()) < 1e-12


def test_pooled_checks(pooled, two):
    db, x = pooled
    # undeclared pool: per-stream treatment, warned
    out = run("jks_info", db, "C_a_a.r", extra_env={"JKS_BIN": "2"}).stdout
    assert "it looks like part of a jackknife over several streams" in out
    out = run("jks_info", db, "C_a_a.r", extra_env={"JKS_BIN": "2", "JKS_BIN_POOL": "ensA+ensB"}).stdout
    assert "WARNING" not in out
    assert "# JKS_BIN ensA (pool ensA+ensB): 24 configs, bin 2 (11-12 bins, offsets)" in out
    # a pool of separate jackknifes, warned
    out = run("jks_info", two[0], "ensA/C_a_a.r", extra_env={"JKS_BIN": "2", "JKS_BIN_POOL": "ensA+ensB"}).stdout
    assert "it looks like a separate jackknife, not part of pool ensA+ensB" in out
    # typo in a pool
    out = run("jks_info", db, "C_a_a.r", extra_env={"JKS_BIN": "2", "JKS_BIN_POOL": "ensA+ensC"}).stdout
    assert "JKS_BIN_POOL: in pool 'ensA+ensC' no stream matches 'ensC'" in out
    # overview
    out = run("jks_info", db, extra_env={"JKS_BIN": "2", "JKS_BIN_POOL": "ens*"}).stdout
    assert "- stream ensB (pool ensA+ensB): 17 configs, bin 2" in out
    # different bin sizes in one pool
    p = run("jks_info", db, "C_a_a.r", check=False, extra_env={"JKS_BIN": "ensA:2,ensB:3", "JKS_BIN_POOL": "ensA+ensB"})
    assert p.returncode == 1 and "different bin sizes" in p.stdout


def test_parse_pool():
    assert binning.parse_pool("a+b, c*") == [("a", "b"), ("c*",)]
    assert binning.populations(["a", "b", "c1", "c2", "d"], binning.parse_pool("a+b,c*")) == [["a", "b"], ["c1", "c2"], ["d"]]
    with pytest.raises(ValueError):
        binning.parse_pool("a+")
