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
#@jks {"id": "blk", "files": ["guess.txt"]}
jks_block blk rows lam <<'JKS'
# a start value from the data, as in an mk
c=$(jks_info "$DB" C 1 | head -1 | awk '{print $1}')
jks_add "$DB" guess "[$c, $(cat guess.txt)]" \
  G2 "r['C'][2:4] * 2"
jks_add_from "$DB" "$IN_lam" lam lam2
JKS
'''


def flow_cli(*args, check=True, cwd=None):
    return run("jks_flow", *args, check=check, cwd=cwd, extra_env=STRAY)


def build(d, base):
    shutil.copyfile(base, os.path.join(d, "base.jks"))
    open(os.path.join(d, "guess.txt"), "w").write("0.7\n")
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


def assert_matches_bash(d, f, figure="fig"):
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
    if figure:
        assert os.path.getsize(os.path.join(work, "files", figure + ".pdf")) > 1000


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


def test_block(flow):
    d, f = flow
    flow_cli("export", f, "blk", os.path.join(d, "blk.jks"))
    r = load(os.path.join(d, "blk.jks"))
    assert r.get("guess").mean()[1] == 0.7 and r.get("lam2").mean()[0] == 0.5
    assert r.get("guess").mean()[0] == pytest.approx(r.get("C").mean()[1], rel=1e-12)
    # the file format round-trips (the here-document is kept as it is)
    assert core.flow.load(f).text() == open(f).read()
    # a declared file makes the block stale, and only the block
    open(os.path.join(d, "guess.txt"), "w").write("0.8\n")
    st = status(f)
    assert st["blk"] == ("stale", "input changed") and st["rows"][0] == st["fig"][0] == "ok"
    flow_cli("run", f)
    assert_matches_bash(d, f)
    os.remove(os.path.join(d, "guess.txt"))
    assert status(f)["blk"][0] == "missing"


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


# ---- import of an mk driver ----
MK = r'''#!/bin/bash
# a driver as they are written by hand
set -e
T=24
WIN="[4,6,8,10]"
cp base.jks data.jks
jks_add data.jks \
	omega0b "np.linspace(0.3, 2.5, 40)" \
	lam "[0.5, 0.25]" \

export JKS_CORRELATION_STRENGTH=0.9
export JKS_X=3
jks_plsa data.jks C "$WIN" "list(range(12))" omega0 C.plsa
unset JKS_CORRELATION_STRENGTH
jks_plsa data.jks C2 "$WIN" "list(range(12))" omega0 C2.plsa
jks_info data.jks C.plsa > info.txt
for tag in C C2
do
    jks_add data.jks int.${tag} "[ r['$tag'][t] * t**2 for t in range($T) ]"
    jks_plot2 int.${tag}.pdf data.jks "c1:int.${tag}:x"
done
for k in $(seq 1 2); do jks_rescale_variance data.jks C2 1.1; done
for tag in C C2; do
  for t in 3 5; do
    jks_add data.jks x.${tag}.${t} "[ r['${tag}'][$t] ]"
  done
done
for row in 'C 4' 'C2 6'; do
  read -r tag t0 <<< "$row"
  jks_add data.jks "y.${tag}" "[ r['${tag}'][${t0}] ]"
done
jks_take sub.jks data.jks 'int.*'
cp sub.jks sub2.jks
jks_add sub2.jks z "r['int.C'] * 2"
jks_add_from data.jks sub2.jks z zz
mv sub2.jks final.jks
if [ -f nothing ]; then
  echo no
fi
if [ -f data.jks ]; then
  jks_add data.jks w "[ $T, $JKS_X ]"
fi
python3 -c 'import jks; print(len(jks.resamples("data.jks").keys()))'
jks_plot2 all.pdf data.jks "c1:C:C" "c2:zz:zz"
'''


def test_import_mk(ensemble, tmp_path):
    # the imported flow computes exactly the databases the driver writes
    from jks.flow import mk
    ran, imp = str(tmp_path / "ran"), str(tmp_path / "imp")
    for d in (ran, imp):
        os.makedirs(d)
        shutil.copyfile(ensemble["db"], os.path.join(d, "base.jks"))
        open(os.path.join(d, "mk"), "w").write(MK)
    p = subprocess.run(["bash", "mk"], cwd=ran, env=env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert p.returncode == 0, p.stdout[-3000:]
    f = os.path.join(imp, "ana.sh")
    out = flow_cli("import", f, os.path.join(imp, "mk")).stdout
    fl, report, files, lists = mk.import_mk(os.path.join(imp, "mk"), os.path.join(imp, "other.sh"))
    text = " ".join(t for _, t in report)
    for what in ("jks_info: prints only", "jks_plot2 skipped", "if ... fi is not supported",
                 "python3 is not a jks script; not a block either: the database name is inside single quotes",
                 "imported as block block on data.jks"):
        assert what in text, (what, text)
    b = fl.nodes["block"]
    assert b.parent == "zz" and b.block["script"].startswith("T=24\nexport JKS_X=3\n")
    assert 'jks_add ${DB} w "[ $T, $JKS_X ]"' in b.block["script"]
    assert lists == ["tags"] and fl.nodes["tags"].values == ["C", "C2"]
    assert sorted(files) == ["base.jks", "data.jks", "final.jks", "sub.jks"]
    assert fl.nodes["C.plsa"].cmd.env == {"JKS_CORRELATION_STRENGTH": "0.9"} and fl.nodes["C2.plsa"].cmd.env == {}
    assert "#   python3 -c 'import jks" in open(f).read()  # kept as a comment to review
    flow_cli("run", f, "-j", "2")
    for path, i in files.items():
        if path != "base.jks":
            flow_cli("export", f, i, os.path.join(imp, "export.jks"))
            assert_same_db(os.path.join(imp, "export.jks"), os.path.join(ran, path))
    assert os.path.getsize(os.path.join(imp, "all.pdf")) > 1000
    # the imported flow replays like any other
    assert_matches_bash(imp, f, figure=None)


LQCD = os.path.expanduser("~/SDP/positive_laplace/examples/lqcd")


@pytest.mark.skipif(not os.path.exists(os.path.join(LQCD, "mk")), reason="needs the lqcd example")
def test_import_lqcd_mk(tmp_path):
    for d in ("ran", "imp"):
        os.makedirs(str(tmp_path / d))
        for f in ("mk", "C_sp.jks"):
            shutil.copyfile(os.path.join(LQCD, f), str(tmp_path / d / f))
    p = subprocess.run(["bash", "mk"], cwd=str(tmp_path / "ran"), env=env(), stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
    assert p.returncode == 0, p.stdout[-3000:]
    f = str(tmp_path / "imp" / "ana.sh")
    flow_cli("import", f, str(tmp_path / "imp" / "mk"))
    flow_cli("run", f, "-j", "2")
    node = [l.split()[-1] for l in flow_cli("import", str(tmp_path / "imp" / "x.sh"), str(tmp_path / "imp" / "mk"))
            .stdout.split("\n") if l.strip().startswith("data.jks is node")][0]
    flow_cli("export", f, node, str(tmp_path / "imp" / "out.jks"))
    assert_same_db(str(tmp_path / "imp" / "out.jks"), str(tmp_path / "ran" / "data.jks"))
