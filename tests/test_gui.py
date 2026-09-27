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
# jks_gui in a headless browser: pages load without errors and the main controls
# work.  Needs the [gui] extra and playwright with chromium, otherwise skipped.
#
import http.cookiejar, os, shutil, socket, subprocess, sys, time, urllib.error, urllib.request
import pytest
from conftest import SCRIPTS, env, run

pytest.importorskip("nicegui")
sync_api = pytest.importorskip("playwright.sync_api")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class gui:
    # jks_gui on a free port -> .url (with the token unless no_token)
    def __init__(self, target, cwd, no_token=True, extra=(), extra_env=None):
        self.port = free_port()
        args = [sys.executable, os.path.join(SCRIPTS, "jks_gui"), "--port", str(self.port),
                "--history", os.path.join(cwd, "history.json")] + list(extra) + [target]
        if no_token:
            args.insert(2, "--no-token")
        self.log = open(os.path.join(cwd, "gui.log"), "w+")
        # without pytest's variables: nicegui would start in its own test mode
        e = dict((k, v) for k, v in env().items() if not k.startswith("PYTEST_"))
        e.update(extra_env or {})
        self.p = subprocess.Popen(args, cwd=cwd, env=e, stdout=self.log, stderr=subprocess.STDOUT)
        self.url = None
        for _ in range(300):
            self.log.seek(0)
            for line in self.log.read().split("\n"):
                if line.startswith("jks_gui: http"):
                    self.url = line.split()[1]
            if self.url and self.up():
                return
            if self.p.poll() is not None:
                break
            time.sleep(0.1)
        self.stop()
        raise AssertionError("jks_gui did not start:\n" + self.output())

    def up(self):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/" % self.port, timeout=1)
        except urllib.error.HTTPError:
            return True  # answers (e.g. 403 without token)
        except OSError:
            return False
        return True

    def output(self):
        self.log.seek(0)
        return self.log.read()

    def stop(self):
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # browser not installed
            pytest.skip("no chromium for playwright: %s" % e)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    pg.errors = []
    # plotly's resize of a plot whose tab was just hidden is harmless
    pg.on("pageerror", lambda e: pg.errors.append(str(e)) if "Resize must be passed a displayed plot" not in str(e)
          else None)
    yield pg
    pg.close()


def test_token_required(db, tmp_path):
    g = gui(db, str(tmp_path), no_token=False)
    try:
        base = "http://127.0.0.1:%d/" % g.port
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base, timeout=5)
        assert e.value.code in (401, 403)
        # the token sets a cookie and redirects to the page
        browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        assert browser.open(g.url, timeout=5).status == 200
        assert browser.open(g.url.split("?")[0], timeout=5).status == 200  # same host as the cookie
    finally:
        g.stop()


def test_browser_gets_the_printed_url(db, tmp_path):
    # --browser (and a local display on macOS) opens exactly the URL with the token
    opened = str(tmp_path / "opened.txt")
    fake = str(tmp_path / "browser.sh")
    with open(fake, "w") as f:
        f.write('#!/bin/sh\necho "$1" >> %s\n' % opened)
    os.chmod(fake, 0o755)
    g = gui(db, str(tmp_path), no_token=False, extra=["--browser"], extra_env={"BROWSER": fake})
    try:
        for _ in range(100):
            if os.path.exists(opened):
                break
            time.sleep(0.1)
        assert open(opened).read().split() == [g.url]
    finally:
        g.stop()


def test_database_page(db, tmp_path, page):
    g = gui(db, str(tmp_path))
    try:
        page.goto(g.url)
        page.get_by_role("cell", name="C", exact=True).click()
        page.wait_for_selector(".js-plotly-plot", timeout=15000)
        for tab in ("Table", "Correlation", "Distribution", "Info", "Plot"):
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(600)
        assert page.errors == []
    finally:
        g.stop()
    assert "Traceback" not in g.output()


def test_flow_page_usage_and_docs(ensemble, tmp_path, page):
    d = str(tmp_path)
    shutil.copyfile(ensemble["db"], os.path.join(d, "base.jks"))
    f = os.path.join(d, "ana.sh")
    run("jks_flow", "source", f, "raw", "base.jks")
    run("jks_flow", "add", f, "grid", "raw", "jks_add", "@", "omega1", "np.linspace(0.3, 2.0, 30)")
    run("jks_flow", "run", f)
    g = gui(f, d)
    try:
        page.goto(g.url)
        page.wait_for_selector("canvas", timeout=15000)
        # disk usage
        page.locator("header button").filter(has_text="KB").click()
        page.get_by_text("Disk usage:").wait_for(timeout=10000)
        assert page.get_by_role("cell", name="grid", exact=True).count() == 1
        page.get_by_role("button", name="Close").click()
        # documentation: underscores are not emphasis (z_j stays z_j)
        page.locator("header button").filter(has=page.locator("i", has_text="menu_book")).click()
        page.get_by_role("cell", name="jks_blsa", exact=True).click()
        page.get_by_text("with positivity z_j >= 0").wait_for(timeout=10000)
        assert page.errors == []
    finally:
        g.stop()
    assert "Traceback" not in g.output()


def test_add_block(ensemble, tmp_path, page):
    d = str(tmp_path)
    shutil.copyfile(ensemble["db"], os.path.join(d, "base.jks"))
    f = os.path.join(d, "ana.sh")
    run("jks_flow", "source", f, "raw", "base.jks")
    run("jks_flow", "add", f, "grid", "raw", "jks_add", "@", "omega1", "np.linspace(0.3, 2.0, 30)")
    run("jks_flow", "run", f)
    g = gui(f, d)
    try:
        page.goto(g.url)
        page.get_by_role("button", name="Add block").click()  # after the selected node, grid
        page.get_by_text("New block").wait_for(timeout=10000)
        page.get_by_role("textbox", name="script", exact=True).fill('jks_add "$DB" twice "2 * r[\'C\']"\n')
        page.get_by_role("button", name="Save and run").click()
        for _ in range(150):  # saved, then computed by the page
            if "twice" in open(f).read():
                line = [l for l in run("jks_flow", "status", f).stdout.split("\n") if l.startswith("block ")]
                if line and line[0].split()[1] == "ok":
                    break
            page.wait_for_timeout(200)
        from jks.flow import core
        n = core.flow.load(f).nodes["block"]
        assert n.kind == "block" and n.parent == "grid"
        run("jks_flow", "export", f, "block", os.path.join(d, "b.jks"))
        from conftest import load
        r = load(os.path.join(d, "b.jks"))
        assert (r.get("twice").mean() == 2 * r.get("C").mean()).all()
        assert page.errors == []
    finally:
        g.stop()
    assert "Traceback" not in g.output()


def test_import_mk_from_the_open_dialog(ensemble, tmp_path, page):
    from test_flow import MK
    d = str(tmp_path)
    shutil.copyfile(ensemble["db"], os.path.join(d, "base.jks"))
    open(os.path.join(d, "mk"), "w").write(MK)
    g = gui(os.path.join(d, "base.jks"), d)
    try:
        page.goto(g.url)
        page.locator("header button").filter(has=page.locator("i", has_text="folder_open")).click()
        row = page.get_by_role("row").filter(has=page.get_by_role("cell", name="mk", exact=True))
        row.wait_for(timeout=10000)
        assert row.get_by_role("cell", name="mk driver", exact=True).count() == 1
        row.click()
        page.get_by_role("button", name="Import").click()
        page.get_by_text("mk.flow.sh:").wait_for(timeout=15000)
        assert page.get_by_text("imported as block node block on data.jks").count() == 1
        page.get_by_role("button", name="Open the flow").click()
        page.wait_for_selector("canvas", timeout=15000)
        assert os.path.exists(os.path.join(d, "mk.flow.sh")) and page.errors == []
    finally:
        g.stop()
    assert "Traceback" not in g.output()
