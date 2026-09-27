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
# Flows: the engine (jks_flow run, the cache, deltas, staleness, rebase, gc) must
# give exactly what "bash flow.sh" gives.
#
import json, os, shutil, subprocess
import pytest
from conftest import ROOT, assert_same_db, env, load, run
from jks.flow import core, registry

# a stray setting of the caller must not change any result
STRAY = {"JKS_CORRELATION_STRENGTH": "0.3"}

LOOPS = r'''
#@jks {"id": "int"}
jks_begin int plsa
for name in $(jks_list_values names); do
  jks_apply int jks_add @ "int.${name}" "[ r['${name}'][t] * t**2 for t in range(24) ]"
done
#@jks {"id": "scaled", "mode": "sequence"}
jks_begin scaled int
for k in $(seq 1 3); do
  jks_apply scaled jks_rescale_variance @ C 1.1
done
#@jks {"id": "hlt"}
jks_begin hlt grid
for l in $(jks_values @lam lam); do
  jks_apply hlt jks_hlt @ C '[4,6,8,10]' '[5,7]' omega0 "H.${l}" "$l"
done
#@jks {"id": "rows"}
jks_begin rows int
for row in 'C 4' 'C2 6'; do
  read -r tag t0 <<< "$row"
  jks_apply rows jks_add @ "x.${tag}" "[ r['${tag}'][${t0}] ]"
done
#@jks {"id": "fig"}
jks_figure fig rows jks_plot2 - xr:0:20 c1:int.C:C c2:int.C2:C2
'''


def flow_cli(*args, check=True, cwd=None):
    return run("jks_flow", *args, check=check, cwd=cwd, extra_env=STRAY)


def build(d, base):
    shutil.copyfile(base, os.path.join(d, "base.jks"))
    f = os.path.join(d, "ana.sh")
    flow_cli("source", f, "raw", "base.jks")
    flow_cli("add", f, "grid", "raw", "jks_add", "@", "omega1", "np.linspace(0.3, 2.0, 30)")
    flow_cli("add", f, "plsa", "grid", "jks_plsa", "@", "C", "[4,6,8,10]", "list(range(12))", "omega0", "C.plsa")
    flow_cli("add", f, "JKS_CORRELATION_STRENGTH=0.9", "plsa9", "plsa", "jks_plsa", "@", "C", "[4,6,8,10]",
             "list(range(12))", "omega1", "C.plsa9", "3.84", "band9")
    flow_cli("add", f, "sub", "-", "jks_take", "@", "@plsa9", "C*")
    flow_cli("add", f, "lam", "raw", "jks_add", "@", "lam", "[0.5, 0.25]")
    flow_cli("list", f, "names", "C", "C2")
    with open(f, "a") as fh:
        fh.write(LOOPS)
    flow_cli("fmt", f)
    return f


def db_nodes(f):
    fl = core.flow.load(f)
    return [i for i, n in fl.nodes.items() if n.has_db() and not n.is_source()]


def assert_matches_bash(d, f):
    # every node's database equals the one "bash flow.sh" writes
    work = os.path.join(d, "ana.work")
    shutil.rmtree(os.path.join(work, "files"), ignore_errors=True)
    e = env()
    e.update(STRAY)
    p = subprocess.run(["bash", f], cwd=d, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert p.returncode == 0, p.stdout[-3000:]
    for i in db_nodes(f):
        out = os.path.join(d, "export-%s.jks" % i)
        flow_cli("export", f, i, out)
        assert_same_db(out, os.path.join(work, "files", i + ".jks"))
    assert os.path.getsize(os.path.join(work, "files", "fig.pdf")) > 1000


def status(f):
    out = {}
    for line in flow_cli("status", f).stdout.split("\n"):
        w = line.split()
        if len(w) >= 2 and not line.startswith(" "):
            out[w[0]] = (w[1], " ".join(w[2:4]))
    return out


@pytest.fixture(scope="module")
def built(ensemble, tmp_path_factory):
    d = str(tmp_path_factory.mktemp("flow"))
    f = build(d, ensemble["db"])
    flow_cli("run", f, "-j", "2")
    return d


@pytest.fixture
def flow(built, tmp_path):
    # a private copy of the computed flow
    d = str(tmp_path / "f")
    shutil.copytree(built, d, symlinks=True)
    return d, os.path.join(d, "ana.sh")


def test_run_matches_bash(flow):
    d, f = flow
    assert set(s for s, _ in status(f).values()) == {"ok"}
    assert_matches_bash(d, f)


def test_loops_and_side_nodes(flow):
    d, f = flow

    def node(i):
        out = os.path.join(d, "%s.jks" % i)
        flow_cli("export", f, i, out)
        return load(out)
    r = node("rows")
    assert {"int.C", "int.C2", "x.C", "x.C2"} <= set(r.keys())
    assert r.get("x.C2").mean()[0] == r.get("C2").mean()[6]
    assert {"H.0.5", "H.0.25"} <= set(node("hlt").keys())  # values of a tag of the side node
    # the sequence applied the rescaling (of the variance) three times
    en = core.engine(core.flow.load(f))
    m = en.meta(en.keys()["scaled"])
    assert m["mode"] == "sequence" and len(m["iterations"]) == 3
    a, s = node("int").get("C"), node("scaled").get("C")
    assert s.cov()[3][3] == pytest.approx(1.1 ** 3 * a.cov()[3][3], rel=1e-10)
    # the step's own environment applies (the caller's is ignored, see test_run_matches_bash)
    assert node("plsa9").get("C.plsa9").vars() == ["band", "band9"]


def test_cached_and_stored_as_deltas(flow):
    d, f = flow
    p = flow_cli("run", f)
    assert "done in" not in p.stdout  # nothing to compute
    en = core.engine(core.flow.load(f))
    keys = en.keys()
    assert en.meta(keys["plsa"])["stored"] == "delta"
    assert en.meta(keys["sub"])["stored"] == "full"  # a new database
    u = en.usage()
    assert u["nodes"]["plsa"]["current"]["changed"] == 1 and u["free"] == 0


def test_edit_recomputes_dependents(flow):
    d, f = flow
    text = open(f).read().replace("np.linspace(0.3, 2.0, 30)", "np.linspace(0.3, 2.0, 31)")
    open(f, "w").write(text)
    st = status(f)
    assert st["grid"] == ("stale", "definition changed")
    assert st["plsa"][0] == st["hlt"][0] == st["fig"][0] == "stale"
    assert st["raw"][0] == st["lam"][0] == st["names"][0] == "ok"
    p = flow_cli("run", f, "-j", "2")
    assert "lam " not in p.stdout
    assert set(s for s, _ in status(f).values()) == {"ok"}
    assert_matches_bash(d, f)
    # the old results are no longer needed
    en = core.engine(core.flow.load(f))
    free, count = en.gc(dry=True)
    assert free > 0 and count >= 5
    assert en.gc() == (free, count) and en.gc(dry=True) == (0, 0)
    assert_matches_bash(d, f)


def test_input_change_is_only_flagged(flow):
    d, f = flow
    run("jks_add", os.path.join(d, "base.jks"), "extra", "[1.0]")
    st = status(f)
    assert st["grid"] == ("stale", "input changed") and st["raw"][0] == "ok"
    flow_cli("run", f, "-j", "2")
    assert_matches_bash(d, f)


def test_rebase(flow):
    d, f = flow
    flow_cli("rebase", f, "hlt", "lam")
    fl = core.flow.load(f)
    assert fl.nodes["hlt"].parent == "lam"
    flow_cli("run", f, "-j", "2")
    assert_matches_bash(d, f)


def test_errors(flow):
    d, f = flow
    p = flow_cli("rm", f, "grid", check=False)
    assert p.returncode == 1
    p = flow_cli("add", f, "bad", "raw", "jks_nonexistent", "@", check=False)
    assert p.returncode == 1
    p = flow_cli("add", f, "bad", "nothere", "jks_add", "@", "x", "[1.0]", check=False)
    assert p.returncode == 1
    flow_cli("rm", f, "fig")
    assert "fig" not in core.flow.load(f).nodes


# ---- registry ----
COMMANDS = [
    "jks_add data.jks omega0 'np.linspace(0.23, 1.2, 60)' omega_low \"0*r['omega0']\"",
    "jks_plsa data.jks C '[14,16,18,20,23,25]' 'list(range(40))' omega0 C.4.14",
    "jks_plsa data.jks C '[14,16]' 'list(range(40))' omega0 X 3.84 band.x",
    "jks_blsa data.jks C '[14,16]' 'list(range(40))' omega0 lo hi C.b",
    "JKS_CORRELATION_STRENGTH=0.9 jks_plsa data.jks C '[14,16]' '[0,1]' omega0 C.s",
    "jks_fit data.jks C 'range(11,25)' 'p[0]*math.exp(-p[1]*x)' C2 'range(5,9)' 'p[0]*x' '[0.012,0.43]' fit1",
    "jks_take out.jks in.jks 'C*' 'int.*'",
    "jks_rm data.jks 'tmp.*'",
    "jks_gevp_2pt g.jks c.jks a,b 'C_%s_%s' 'gevp.%s' 1",
    "jks_hlt data.jks C '[14,16]' '[10,14]' omega0 C.hlt 0.5",
]


@pytest.mark.parametrize("line", COMMANDS)
def test_registry_round_trip(line):
    e, name, argv = registry.split_command(line)
    s = registry.BY_NAME[name]
    assert s.build(s.parse(argv)) == argv
    assert registry.split_command(registry.join_command(e, name, argv)) == (e, name, argv)


def test_registry_scripts_exist():
    for s in registry.SCRIPTS:
        assert os.path.exists(os.path.join(ROOT, "scripts", s.name)), s.name
