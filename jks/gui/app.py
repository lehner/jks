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
# jks_gui application: page layout, command line and access token.
#
import argparse, glob, http.cookies, os, re, secrets, sys, urllib.parse
from nicegui import app, run, ui
from jks.flow import runner
from jks.gui import database, docs, history
from jks.gui.browser import database_view
from jks.gui.filepicker import file_picker
from jks.gui.step import MONO, preview_view, step_panel
from jks.gui import flowview
from jks.flow import core

recent = []
work_name = ".jks_work"
jobs = 2  # parallel steps in flows
inputs = None  # history.history of the step panel's fields


class token_middleware:
    # Every HTTP and websocket request needs the token, either as ?token=
    # (answered with a cookie and a redirect) or as that cookie.  Plain ASGI
    # so that the websocket of the UI is covered as well.
    def __init__(self, app, token, cookie):
        self.app, self.token, self.cookie = app, token, cookie

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        jar = http.cookies.SimpleCookie(headers.get(b"cookie", b"").decode("latin1"))
        if self.cookie in jar and secrets.compare_digest(jar[self.cookie].value, self.token):
            return await self.app(scope, receive, send)
        query = urllib.parse.parse_qs(scope.get("query_string", b"").decode())
        if scope["type"] == "http" and secrets.compare_digest(query.pop("token", [""])[0], self.token):
            loc = scope["path"] + ("?" + urllib.parse.urlencode(query, doseq=True) if query else "")
            await send({"type": "http.response.start", "status": 302, "headers": [
                (b"location", loc.encode()),
                (b"set-cookie", ("%s=%s; Path=/; HttpOnly; SameSite=Strict" % (self.cookie, self.token)).encode())]})
            return await send({"type": "http.response.body", "body": b""})
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"jks_gui: missing or wrong token, use the URL printed at startup\n"})


def remember(path):
    path = os.path.abspath(path)
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)


def url(path):
    return "/?" + urllib.parse.urlencode({"file": path})


class db_page:
    # one browser tab: the open database, its view, a step preview and the step panel
    def __init__(self, file):
        self.file = os.path.abspath(file) if file else ""
        self.base = os.path.dirname(self.file) if file else os.getcwd()
        self.work = runner.work(os.path.join(self.base, work_name))
        self.db = None
        self.history = inputs
        self.view = None
        self.panel = None
        self.dark = ui.dark_mode(False)

    async def build(self):
        with ui.header().classes("items-center gap-2 py-1"):
            ui.label("jks").classes("text-lg font-bold")
            ui.button(icon="folder_open", on_click=self.pick).props("flat dense color=white").tooltip("open a database or flow")
            with ui.button(icon="history").props("flat dense color=white").tooltip("recent databases"):
                with ui.menu():
                    for p in recent:
                        ui.menu_item(p, on_click=lambda p=p: ui.navigate.to(url(p)))
            self.title = ui.label(self.file or "no database open").classes("text-sm opacity-80 grow truncate")
            self.reload_btn = ui.button(icon="refresh", on_click=lambda: self.load(True)) \
                .props("flat dense color=white").tooltip("reload from disk")
            ui.button(icon="add_task", on_click=self.toggle_panel) \
                .props("flat dense color=white").tooltip("new step")
            if self.file:
                ui.button(icon="account_tree", on_click=self.new_flow) \
                    .props("flat dense color=white").tooltip("new flow from this database")
            ui.button(icon="menu_book", on_click=docs.index).props("flat dense color=white").tooltip("documentation")
            ui.button(icon="dark_mode", on_click=self.toggle_dark).props("flat dense color=white").tooltip("dark mode")
        self.drawer = ui.right_drawer(value=False).props("width=520 bordered").classes("p-3")
        self.body = ui.column().classes("w-full")
        if not self.file:
            self.reload_btn.disable()
            with self.body:
                ui.label("Open a database (.jks) or a flow (.sh) with the folder button, or start jks_gui with "
                         "file names. Steps that create a new database can be run from the step panel.").classes("m-8")
        else:
            await self.load()
        with self.drawer:
            self.panel = step_panel(self)
        ui.timer(5.0, self.check_disk)

    def toggle_panel(self):
        self.drawer.toggle()
        if self.drawer.value and self.panel is not None:
            self.panel.fill_active()

    def active_tag(self):
        # the tag inspected in the current view, if the open database has it
        v = self.view
        if v is None or v.active is None or self.db is None or v.active not in self.db.res.set:
            return None
        return v.active

    async def pick(self):
        path = await file_picker(self.base, pattern=(".jks", ".sh"))
        if path:
            ui.navigate.to(url(path))

    def new_flow(self):
        # a flow file with this database as its source
        stem = os.path.splitext(os.path.basename(self.file))[0]
        with ui.dialog() as dlg, ui.card().classes("w-[36rem]"):
            ui.label("New flow starting from %s" % self.file).classes("text-sm break-all")
            path = ui.input("flow file", value=os.path.join(self.base, stem + ".flow.sh")).classes("w-full").style(MONO)

            def go():
                p = os.path.abspath(os.path.expanduser(path.value))
                if os.path.exists(p):
                    ui.notify("%s exists" % p, type="negative")
                    return
                fl = core.flow(p)
                src = os.path.relpath(self.file, os.path.dirname(p))
                sid = re.sub(r"[^A-Za-z0-9_.-]", "_", stem) or "source"
                fl.add(core.node(sid if core.ID.match(sid) else "source", "source", source=src))
                fl.save()
                remember(p)
                ui.navigate.to(url(p))
            with ui.row():
                ui.button("Create", on_click=go)
                ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()

    def toggle_dark(self):
        self.dark.value = not self.dark.value
        if self.view is not None:
            self.view.refresh_theme()

    async def load(self, force=False):
        self.body.clear()
        with self.body, ui.row().classes("m-8 items-center"):
            ui.spinner(size="lg")
            ui.label("loading %s ..." % self.file)
        try:
            self.db = await run.io_bound(database.load, self.file, force)
        except Exception as e:
            self.body.clear()
            with self.body:
                ui.label("ERROR: cannot read %s: %s" % (self.file, e)).classes("m-8 text-negative")
            return
        remember(self.db.path)
        self.title.text = self.file
        self.reload_btn.props("color=white")
        self.show_current()

    def show_current(self):
        self.body.clear()
        if self.db is None:
            return
        with self.body:
            self.view = database_view(self.db, self.dark, fit_source=self.fit_source, on_delete=self.delete_tags)

    def show_preview(self, panel):
        self.body.clear()
        with self.body:
            self.view = preview_view(panel.result, self.dark, self.fit_source, panel.commit_controls)

    async def after_commit(self, path):
        if self.db is not None and path == self.db.path:
            await self.load(True)
        else:
            remember(path)
            self.show_current()
            with self.body, ui.dialog() as dlg, ui.card():
                ui.label("saved %s" % path)
                with ui.row():
                    ui.button("Open it", on_click=lambda: ui.navigate.to(url(path)))
                    ui.button("Stay", on_click=dlg.close).props("flat")
            dlg.open()

    async def delete_tags(self, tags):
        # jks_rm with the tag names escaped for fnmatch; commit only if exactly these tags go
        st = runner.step("jks_rm", [os.path.basename(self.db.path)] + [glob.escape(t) for t in tags], {}, self.base)
        n = ui.notification("deleting %d tags ..." % len(tags), spinner=True, timeout=None)
        try:
            m = await self.work.run(st)
            if not m["ok"]:
                raise RuntimeError(m["error"])
            child = await run.io_bound(database.load, self.work.node(m["key"]))
            d = runner.diff(self.db.res, child.res)
            if sorted(d["removed"]) != sorted(tags) or d["added"] or d["modified"]:
                raise RuntimeError("jks_rm did not remove exactly the selected tags; nothing changed")
            self.work.commit(m)
        except Exception as e:
            n.dismiss()
            ui.notify("ERROR: %s" % e, type="negative", multi_line=True)
            return
        n.dismiss()
        ui.notify("deleted %d tags (%s)" % (len(tags), m["command"][:120]), type="positive")
        await self.load(True)

    def fit_source(self, fit):
        return runner.find_fit(self.work, fit)

    def check_disk(self):
        if self.db is not None and self.db.changed_on_disk():
            self.reload_btn.props("color=warning")
            self.title.text = self.file + "  (changed on disk)"


@app.get("/jks_figure/{key}.pdf")
def figure(key: str):
    # figures of plot nodes (behind the token middleware like everything else)
    from fastapi.responses import FileResponse, Response
    p = flowview.FIGURES.get(key)
    if not p or not os.path.exists(p):
        return Response(status_code=404)
    return FileResponse(p, media_type="application/pdf")


@ui.page("/")
async def index(file: str = ""):
    if file and flowview.is_flow(file):
        try:
            p = flowview.flow_page(file, ui.dark_mode(False), inputs, jobs)
        except (core.FlowError, OSError) as e:
            ui.label("ERROR: cannot open the flow %s: %s" % (file, e)).classes("m-8 text-negative whitespace-pre-wrap")
            return
        remember(file)
        await p.build()
        return
    await db_page(file).build()


def main(argv=None):
    p = argparse.ArgumentParser(prog="jks_gui", description="Graphical browser for jks databases.")
    p.add_argument("files", nargs="*", help="databases or flow files to offer (the first one is opened)")
    p.add_argument("--jobs", type=int, default=2, help="parallel steps when running flows (default: 2)")
    p.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--no-token", action="store_true", help="do not require an access token")
    p.add_argument("--native", action="store_true", help="open in a desktop window (needs pywebview)")
    p.add_argument("--browser", action="store_true", help="open a browser even over ssh")
    p.add_argument("--history", default=None,
                   help="file with the step panel's input history (default: %s)" % history.default_path())
    p.add_argument("--work", default=".jks_work",
                   help="work directory for step results, relative to each database (default: .jks_work)")
    a = p.parse_args(argv)
    global work_name, inputs, jobs
    work_name = a.work
    jobs = a.jobs
    inputs = history.history(a.history)

    for f in reversed(a.files):
        if not os.path.isfile(f):
            print("ERROR: no such file: %s" % f)
            sys.exit(1)
        remember(f)

    path = "/" + ("?" + urllib.parse.urlencode({"file": recent[0]}) if recent else "")
    url = "http://%s:%d%s" % ("localhost" if a.host in ("127.0.0.1", "0.0.0.0") else a.host, a.port, path)
    if not a.no_token and not a.native:
        token = secrets.token_urlsafe(24)
        app.add_middleware(token_middleware, token=token, cookie="jks_gui_%d" % a.port)
        url += ("&" if "?" in url else "?") + "token=" + token

    print("jks_gui: %s" % url, flush=True)
    if "SSH_CONNECTION" in os.environ:
        print("jks_gui: from your workstation: ssh -L %d:localhost:%d %s" % (a.port, a.port, os.uname().nodename), flush=True)
    local_display = sys.platform == "darwin" or "DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ
    show = url if (a.browser or (local_display and "SSH_CONNECTION" not in os.environ)) else False
    ui.run(host=a.host, port=a.port, title="jks", reload=False, show=show, native=a.native,
           show_welcome_message=False, favicon="📊")
