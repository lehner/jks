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
# Shared fixtures: a synthetic ensemble (written as corrfiles and imported with
# the real importer), running scripts of this checkout, comparing databases.
#
import os, shutil, subprocess, sys
import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, ROOT)

import jks  # noqa: E402  (this checkout, not an installed copy)
import jks.corrIO as corrIO  # noqa: E402

NCONF, T = 24, 24
E = [0.45, 0.95]  # energies of the two states
Z = [[1.0, 0.5], [0.6, -0.8]]  # overlaps <0|O_a|n>
OPS = ["a", "b"]


def env():
    # scripts and python of this checkout; stray JKS_* settings of the caller are dropped
    e = dict((k, v) for k, v in os.environ.items() if not k.startswith("JKS_") and k not in ("BIN", "STATS_KEEP_FIXED"))
    e["PATH"] = SCRIPTS + os.pathsep + os.path.dirname(sys.executable) + os.pathsep + e.get("PATH", "")
    e["PYTHONPATH"] = ROOT + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    e["PYTHONUNBUFFERED"] = "1"
    return e


def run(script, *args, cwd=None, check=True, extra_env=None, script_file=None):
    # run scripts/<script> with this python -> CompletedProcess (stdout and stderr together)
    e = env()
    e.update(extra_env or {})
    p = subprocess.run([sys.executable, script_file or os.path.join(SCRIPTS, script)] + [str(a) for a in args],
                       cwd=cwd, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if check and p.returncode != 0:
        raise AssertionError("%s %s failed (%d):\n%s" % (script, " ".join(map(str, args)), p.returncode, p.stdout))
    return p


def old_script(name, tmp):
    # a script as committed (HEAD), to compare against; skipped outside a git checkout
    try:
        src = subprocess.run(["git", "-C", ROOT, "show", "HEAD:scripts/%s" % name], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no git checkout")
    p = os.path.join(str(tmp), "old_" + name)
    with open(p, "wb") as f:
        f.write(src)
    return p


def content(path):
    # a database without its origin (argv, date, ...), for comparisons
    import pickle, lz4.frame
    try:
        with lz4.frame.open(path, "rb") as f:
            s = pickle.load(f)
    except RuntimeError:
        with open(path, "rb") as f:
            s = pickle.load(f)
    s.pop("origin", None)
    return s


def assert_same_db(a, b):
    # bit-identical tags (same order), configurations, variations, info and arrays
    x, y = content(a), content(b)
    assert list(x["set"]) == list(y["set"])
    for k in x:
        if k != "set":
            assert x[k] == y[k], k
    for t in x["set"]:
        for f in ("orig", "blocks", "N"):
            assert np.array_equal(np.asarray(x["set"][t][f]), np.asarray(y["set"][t][f]), equal_nan=True), (t, f)


def correlators(seed=1):
    # per configuration: the 2x2 correlator matrix C_ab(t) of two states, with noise that is
    # correlated in t (a random walk) and grows relative to the signal
    rng = np.random.default_rng(seed)
    t = np.arange(T)
    out = []
    for c in range(NCONF):
        walk = np.cumsum(rng.normal(size=T)) / np.sqrt(T)
        m = {}
        for i, a in enumerate(OPS):
            for j, b in enumerate(OPS):
                exact = sum(Z[i][n] * Z[j][n] * np.exp(-E[n] * t) for n in range(2))
                noise = 0.01 * np.exp(0.08 * t) * (walk + 0.3 * rng.normal(size=T)) * (1.0 if i == j else 0.5)
                m["C_%s_%s" % (a, b)] = exact * (1.0 + noise) + 1j * 1e-3 * rng.normal(size=T) * np.exp(-E[0] * t)
        out.append(m)
    return out


def write_corrfiles(directory, first=100, step=10):
    os.makedirs(directory, exist_ok=True)
    for c, m in enumerate(correlators()):
        w = corrIO.writer(os.path.join(directory, "ens.%d.bin" % (first + step * c)))
        for tag, v in m.items():
            w.write(tag, list(v))
        w.close()
    return os.path.join(directory, "ens.*.bin")


@pytest.fixture(scope="session")
def ensemble(tmp_path_factory):
    # base.jks: C_a_b.r/.i imported from corrfiles, C = C_a_a.r and an omega grid
    d = tmp_path_factory.mktemp("ensemble")
    pat = write_corrfiles(str(d / "corr"))
    db = str(d / "base.jks")
    run("jks_create_correlator_from_corrfile", db, "ens", pat)
    run("jks_add", db, "C", "r['C_a_a.r']", "C2", "r['C_b_b.r']", "omega0", "np.linspace(0.3, 2.5, 40)")
    return {"dir": str(d), "db": db, "pattern": pat}


@pytest.fixture
def db(ensemble, tmp_path):
    # a private copy of base.jks
    p = str(tmp_path / "data.jks")
    shutil.copyfile(ensemble["db"], p)
    return p


def load(path):
    return jks.resamples(path)
