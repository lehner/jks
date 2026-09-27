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
# The jks_* scripts: behaviour that was fixed, and cross-checks between scripts.
#
import glob, os, shutil, stat, struct, binascii
import numpy as np
import pytest
from conftest import (ROOT, NCONF, E, assert_same_db, correlators, load, old_script, run, write_corrfiles)

WIN = "[4,6,8,10]"  # input times of the spectral tools
WOUT = "list(range(12))"


def tags(path):
    return list(load(path).keys())


def pages(path):
    if not shutil.which("pdfinfo"):
        pytest.skip("needs pdfinfo")
    import subprocess
    out = subprocess.run(["pdfinfo", path], stdout=subprocess.PIPE, text=True, check=True).stdout
    return int([l for l in out.split("\n") if l.startswith("Pages:")][0].split()[1])


# ---- import ----
def test_importers_agree_and_read_only_inputs(ensemble, tmp_path):
    # the novar importer gives the same data (it numbers configurations by position);
    # write-protected raw data can be imported; the tag order is that of the files
    d = str(tmp_path / "corr")
    pat = write_corrfiles(d)
    for f in glob.glob(os.path.join(d, "*")):
        os.chmod(f, stat.S_IRUSR)
    a, b = str(tmp_path / "a.jks"), str(tmp_path / "b.jks")
    run("jks_create_correlator_from_corrfile", a, "ens", pat)
    run("jks_create_correlator_from_corrfile_novar", b, "ens", pat)
    ra, rb = load(a), load(b)
    assert list(ra.keys()) == list(rb.keys()) == [x + y for x in correlators()[0] for y in (".r", ".i")]
    for t in ra.keys():
        assert np.array_equal(ra.get(t).orig, rb.get(t).orig) and np.array_equal(ra.get(t).blocks, rb.get(t).blocks)
    assert ra.tags == ["ens-%08d" % (100 + 10 * k) for k in range(NCONF)]
    assert rb.tags == ["ens-%08d" % (NCONF + k) for k in range(NCONF)]
    # the same file again (the order used to change from run to run)
    c = str(tmp_path / "c.jks")
    run("jks_create_correlator_from_corrfile", c, "ens", pat, extra_env={"PYTHONHASHSEED": "7"})
    assert_same_db(a, c)


def test_extract_config_returns_the_measurement(db):
    # the reconstructed configuration equals what was written for it
    k = 3
    out = run("jks_extract_config", db, "C", "ens-%08d" % (100 + 10 * k)).stdout.split("\n")
    exact = correlators()[k]["C_a_a"].real
    for t in range(5):
        i, v, _ = out[t].split()
        assert int(i) == t and abs(float(v) - exact[t]) <= 1e-12 * abs(exact[t])


def test_dump_corrs(tmp_path):
    d = str(tmp_path / "c")
    write_corrfiles(d)
    out = run("dump-corrs", os.path.join(d, "ens.100.bin"), "C_a_b").stdout.split("\n")
    assert out[0].startswith("Tag[C_a_b] Size[24]")
    exact = correlators()[0]["C_a_b"]
    j, re_, im = out[3].split()
    assert int(j) == 2 and float(re_) == pytest.approx(exact[2].real, rel=1e-14)
    assert float(im) == pytest.approx(exact[2].imag, rel=1e-14)
    # flagged records (real only, empty) of other writers
    p = str(tmp_path / "flagged.bin")
    with open(p, "wb") as f:
        for tag, flags, stored, full in [("real", 2, [1.5, 2.5], [1.5, 0.0, 2.5, 0.0]), ("empty", 1, [], [0.0] * 4)]:
            t = (tag + "\0").encode()
            f.write(struct.pack("i", len(t)) + t)
            crc = binascii.crc32(struct.pack("d" * 4, *full)) & 0xffffffff
            f.write(struct.pack("IHH", crc, 2, flags) + struct.pack("d" * len(stored), *stored))
    out = run("dump-corrs", p).stdout
    assert "Flags[real]" in out and "1 2.5 0" in out and "Flags[empty]" in out
    assert run("dump-corrs", check=False).returncode == 0  # usage


# ---- small tools ----
def test_info_zero_element(db):
    r = load(db)
    jk = r.get("C")
    o = np.array(jk.orig)
    o[1] = 0.0
    jk.orig = o
    r.save(db)
    out = run("jks_info", db, "C", "1").stdout
    assert "0.0(" in out or "0.00" in out


def test_add_fit_helpers(db):
    fit = "fit(r, [('C', range(8,16), lambda t,p: p[0]*np.exp(-p[1]*t))], [1.3, 0.45])"
    run("jks_add", db, "F", fit, "G", fit.replace("fit(", "cfit("))
    r = load(db)
    f, g = r.get("F").mean(), r.get("G").mean()
    assert len(f) == 5 and np.isfinite(f[:2]).all() and np.isnan(f[2:]).all()
    assert g[1] == pytest.approx(E[0], rel=0.05) and g[3] == 6  # chi2, dof, p appended


def test_rm(db, tmp_path):
    ref = str(tmp_path / "ref.jks")
    shutil.copyfile(db, ref)
    run("jks_rm", db, "C_*", "omega0")
    run("jks_rm", ref, "C_*", "omega0", script_file=old_script("jks_rm", tmp_path))
    assert_same_db(db, ref)
    assert tags(db) == ["C", "C2"]
    # removing every tag keeps configurations; tags can be added again
    run("jks_rm", db, "*")
    r = load(db)
    assert list(r.keys()) == [] and len(r.tags) == NCONF
    run("jks_add", db, "x", "[1.0]")
    assert tags(db) == ["x"]


def test_take(db, tmp_path):
    a, b = str(tmp_path / "a.jks"), str(tmp_path / "b.jks")
    run("jks_take", a, db, "C_a*", "C")
    run("jks_take", b, db, "C_a*", "C", script_file=old_script("jks_take", tmp_path))
    assert_same_db(a, b)
    c = str(tmp_path / "c.jks")
    p = run("jks_take", c, db, "C_a*", "C_a_a*", "C", "nothing")  # overlapping patterns, one without match
    assert "WARNING: no tag matches nothing" in p.stdout
    assert_same_db(a, c)
    p = run("jks_take", str(tmp_path / "d.jks"), db, "nothing*", check=False)
    assert p.returncode == 1 and "ERROR" in p.stdout and not os.path.exists(str(tmp_path / "d.jks"))


def test_create_parameter(tmp_path):
    p = str(tmp_path / "p.jks")
    assert run("jks_create_parameter", p, check=False).returncode == 0 and not os.path.exists(p)
    run("jks_create_parameter", p, "mass", "1.5", "0.1", "L", "48", "0")
    r = load(p)
    assert r.get("mass").mean()[0] == 1.5 and r.get("mass").tcov()[0][0] == pytest.approx(0.01)
    assert r.get("L").tcov()[0][0] == 0.0


def test_set_variance(db):
    run("jks_set_variance", db, "C", "1", "0.05")
    jk = load(db).get("C")
    assert np.sqrt(jk.cov()[1][1]) == pytest.approx(0.05 * jk.mean()[1], rel=1e-10)
    run("jks_add", db, "K", "[1.0, r['C'][0]]")
    p = run("jks_set_variance", db, "K", "0", "0.05", check=False)
    assert p.returncode == 1 and "does not fluctuate" in p.stdout
    assert np.isfinite(load(db).get("K").blocks).all()


def test_add_from_argument_check(db, tmp_path):
    other = str(tmp_path / "o.jks")
    shutil.copyfile(db, other)
    before = open(db, "rb").read()
    run("jks_add_from", db, other, "C", "D", "C2")  # unpaired: usage, nothing written
    assert open(db, "rb").read() == before
    run("jks_add_from", db, other, "C", "D", "C2", "D2")
    r = load(db)
    assert np.array_equal(r.get("D2").blocks, r.get("C2").blocks)


def test_gevp(db, tmp_path):
    out = str(tmp_path / "g.jks")
    run("jks_gevp_2pt", out, db, "a,b", "C_%s_%s.r", "gevp.%s", "1")
    r = load(out)
    assert r.get("gevp.En-0").mean()[4] == pytest.approx(E[0], rel=0.02)
    assert r.get("gevp.En-1").mean()[3] == pytest.approx(E[1], rel=0.1)
    before = open(db, "rb").read()
    for script, extra in (("jks_gevp_2pt", []), ("jks_gevp_2pt_tref", ["2"])):
        p = run(script, db, db, "a,b", "C_%s_%s.r", "gevp.%s", "1", *extra, check=False)
        assert p.returncode == 1 and "ERROR" in p.stdout
    assert open(db, "rb").read() == before


# ---- fits ----
def test_slow_fit_propagates_like_fit(db):
    args = ["C", "range(8,16)", "p[0]*math.exp(-p[1]*x)", "[1.3,0.45]"]
    run("jks_fit", db, *args, "fit1")
    run("jks_slow_fit", db, *args, "sfit1")
    r = load(db)
    a, b = r.get("fit1"), r.get("sfit1")
    assert np.allclose(a.mean()[:2], b.mean()[:2], rtol=1e-6)
    assert np.allclose(np.sqrt(np.diag(a.tcov()))[:2], np.sqrt(np.diag(b.tcov()))[:2], rtol=1e-3)
    assert a.mean()[1] == pytest.approx(E[0], rel=0.02)


# ---- spectral ----
def test_plsa_band_variation(db, tmp_path):
    ref = str(tmp_path / "ref.jks")
    shutil.copyfile(db, ref)
    old = old_script("jks_plsa", tmp_path)
    for tgt, script in ((db, None), (ref, old)):
        run("jks_plsa", tgt, "C", WIN, WOUT, "omega0", "P1", script_file=script)
        run("jks_plsa", tgt, "C", "[4,8,12]", WOUT, "omega0", "P2", script_file=script)
    # default: one shared !band, bit-identical to the committed script
    assert_same_db(db, ref)
    r = load(db)
    assert [t for t in r.tags if t[0] == "!"] == ["!band"]
    # error_tag gives a separate variation
    run("jks_plsa", db, "C", WIN, WOUT, "omega0", "P3", "1", "band.p3")
    r = load(db)
    assert [t for t in r.tags if t[0] == "!"] == ["!band", "!band.p3"]
    assert np.array_equal(r.get("P3").mean(), r.get("P1").mean())
    # an existing tag_out is refused before the computation
    p = run("jks_plsa", db, "C", WIN, WOUT, "omega0", "P1", check=False)
    assert p.returncode == 1 and "exists already" in p.stdout


def test_plsa_anchor_and_blsa_identity(db):
    run("jks_add", db, "lo", "0*r['omega0']", "hi", "0*r['omega0'] + np.inf")
    run("jks_plsa", db, "C", WIN, WOUT, "omega0", "P")
    run("jks_blsa", db, "C", WIN, WOUT, "omega0", "lo", "hi", "B", "1", "band.b")
    r = load(db)
    p, b = r.get("P"), r.get("B")
    # blsa with l=0, u=inf is plsa (the variations only differ in name)
    assert np.array_equal(p.mean(), b.mean()) and np.array_equal(p.cov(), b.cov())
    assert np.array_equal(p.tcov(), b.tcov())
    # at an input time the band is the statistical error (half-width close to the input error)
    c = r.get("C")
    assert p.mean()[6] == pytest.approx(c.mean()[6], rel=1e-3)
    assert np.sqrt(p.tcov()[6][6]) == pytest.approx(np.sqrt(c.cov()[6][6]), rel=0.1)


def test_hlt_runs(db):
    run("jks_hlt", db, "C", WIN, "[5,7]", "omega0", "H", "0.5")
    h, c = load(db).get("H").mean(), load(db).get("C").mean()
    assert np.isfinite(h).all() and h[0] == pytest.approx(c[5], rel=0.05)


# ---- plots ----
def _have(*tools):
    return all(shutil.which(t) for t in tools)


@pytest.mark.skipif(not _have("gnuplot", "pdfcrop", "exiftool"), reason="needs gnuplot, pdfcrop and exiftool")
def test_plot_settings_anywhere_and_exit_status(db, tmp_path):
    out = str(tmp_path / "p.pdf")
    run("jks_plot", out, db, "c1:C:C", "yr:0:1e-3", "c2:C2:C2", "newpage", "c3:C:again", "xr:2:20")
    assert pages(out) == 2
    p = run("jks_plot", str(tmp_path / "bad.pdf"), db, "c1:C:x", "l1:nofunc(x):bad", check=False)
    assert p.returncode == 1 and "gnuplot failed" in p.stdout


def test_plot2(db, tmp_path):
    out = str(tmp_path / "p2.pdf")
    run("jks_plot2", out, db, "xr:2:20", "c1:C:C", "c2:C2:C2")
    assert os.path.getsize(out) > 1000


def test_plot_dist(db, tmp_path):
    out = str(tmp_path / "d.pdf")
    p = run("jks_plot_dist", out, db, "C", "10", "6", "C(10)")
    assert "Avg:" in p.stdout and pages(out) == 6
    # odd N: the first configuration is dropped, and so are the part lists
    d = str(tmp_path / "corr")
    pat = write_corrfiles(d)
    os.remove(os.path.join(d, "ens.330.bin"))
    odd = str(tmp_path / "odd.jks")
    run("jks_create_correlator_from_corrfile", odd, "ens", pat)
    p = run("jks_plot_dist", out, odd, "C_a_a.r", "10", "6", "C(10)")
    part = [l for l in p.stdout.split("\n") if l.startswith("Part 0 / 2")][0]
    assert part.split("[")[1].startswith("'ens-00000110'") and part.count("ens-") == (NCONF - 2) // 2
