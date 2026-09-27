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
# Flow page: the graph of a flow file, the database of the selected node, and
# the step panel adding or editing nodes.  The engine runs in a worker thread
# (its own event loop); log lines and node states come back through a queue.
# Editing a node recomputes everything after it; changed input files are only
# flagged (Run stale).
#
import asyncio, glob, os, queue, re, threading, time
from nicegui import run, ui
import jks
from jks.flow import core, registry, runner
from jks.gui import database, stats
from jks.gui.browser import database_view
from jks.gui.filepicker import file_picker
from jks.gui.step import MONO, preview_view, step_panel

STATUS = {  # color, text; status colors are reserved for states and always come with the text
    "ok": ("#0ca30c", "ok"), "stale": ("#fab219", "stale"), "failed": ("#d03b3b", "failed"),
    "missing": ("#ec835a", "input missing"), "new": ("#8f8d86", "not computed"),
    "running": ("#2a78d6", "running"),
}
SYMBOL = {"source": "rect", "list": "diamond", "step": "circle", "loop": "roundRect"}


def is_flow(path):
    try:
        with open(path, "rb") as f:
            head = f.read(200)
    except OSError:
        return path.endswith(".sh")
    return core.FORMAT.encode() in head


def layout(fl):
    # layers by longest path from the inputs, order in a layer by the mean position of the inputs
    depth = {}
    for n in fl.nodes.values():
        depth[n.id] = 1 + max([depth[i] for i in n.inputs()], default=-1)
    layers = {}
    for i in fl.nodes:
        layers.setdefault(depth[i], []).append(i)
    pos = {}
    for d in sorted(layers):
        ids = layers[d]
        if d > 0:
            ids.sort(key=lambda i: sum(pos[r][1] for r in fl.nodes[i].inputs()) / max(len(fl.nodes[i].inputs()), 1))
        for k, i in enumerate(ids):
            pos[i] = (d * 160, k * 80)
    return pos


def new_id(fl, name, argv):
    # the first output tag if it makes a readable id, else the script name
    spec = registry.BY_NAME[name]
    try:
        outs = [t for t in spec.tags_out(spec.parse(argv)) if "*" not in t]
    except ValueError:
        outs = []
    base = outs[0] if outs and core.ID.match(outs[0]) else name.replace("jks_", "")
    i, k = base, 2
    while i in fl.nodes:
        i, k = "%s.%d" % (base, k), k + 1
    return i


class flow_target:
    # the step panel adds a node after the selected one, or edits a node
    def __init__(self, page):
        self.page = page
        self.edit = None  # id of the node being edited
        self.node_id = None
        self.label = ""

    @property
    def db(self):
        # tags offered in the form: the database the step starts from
        return self.page.parent_db()

    def where(self):
        return "flow %s, work directory %s" % (os.path.basename(self.page.fl.path), self.page.en.work)

    def primary_default(self, spec):
        return "@"

    def input_default(self):
        s = self.page.selected
        return "@" + s if s and self.page.fl.nodes[s].has_db() else ""

    def inputs(self):
        return ["@" + i for i, n in self.page.fl.nodes.items() if n.has_db() and i != self.edit]

    def primary_label(self, x):
        p = self.parent()
        return "this node (a copy of %s)" % p if p else "this node (a new database)"

    def parent(self, name=None):
        if self.edit:
            return self.page.fl.nodes[self.edit].parent
        s = self.page.selected
        return s if s and self.page.fl.nodes[s].has_db() else None

    def node(self, name, argv, env):
        spec = registry.BY_NAME[name]
        parent = self.parent() if spec.primary_kind() in ("db", "db_maybe") else None
        if self.edit:
            old = self.page.fl.nodes[self.edit]
            return core.node(self.edit, "step", parent, core.command(name, argv, env), meta=old.meta, notes=old.notes)
        i = self.node_id or new_id(self.page.fl, name, argv)
        meta = {"label": self.label} if self.label else {}
        return core.node(i, "step", parent, core.command(name, argv, env), meta=meta)

    def candidate(self, name, argv, env):
        # the flow with the new or edited node (raises FlowError)
        n = self.node(name, argv, env)
        fl = self.page.fl.copy()
        if self.edit:
            fl.replace(n)
        else:
            fl.add(n)
        return fl, n

    def check(self, name, argv, env):
        try:
            fl, n = self.candidate(name, argv, env)
        except core.FlowError as e:
            return [str(e)]
        db = self.db
        msgs = []
        spec = registry.BY_NAME[name]
        v = spec.parse(argv)
        if db is not None and spec.primary_kind() in ("db", "db_maybe"):
            have = set(db.keys())
            out = [t for t in spec.tags_out(v) if "*" not in t]
            msgs += ["tag %s exists already" % t for t in out if t in have]
            msgs += ["tag %s not found" % t for t in spec.tags_in(v) if t not in have and t not in out]
        return msgs

    def normalize(self, spec, values):
        if spec.get_primary(values) != "@":
            self.page.notify("in a flow the step writes the database of its own node (@)", type="info")
            values = spec.set_primary(values, "@")
        return values

    def render_extra(self, panel):
        if self.edit:
            with ui.row().classes("w-full items-center no-wrap"):
                ui.label("editing node %s" % self.edit).classes("text-sm font-bold grow")
                ui.button("new node instead", on_click=lambda: self.page.start_add()).props("flat dense size=sm")
            return
        p = self.parent()
        ui.label("new node after %s" % p if p else "new node (select a node to start from it)") \
            .classes("text-sm font-bold")
        with ui.row().classes("w-full items-center no-wrap gap-1"):
            ui.input("node id (default from the output)", value=self.node_id or "",
                     on_change=lambda e: self.set_id(e.value)).props("dense").classes("grow").style(MONO)
            ui.input("label", value=self.label, on_change=lambda e: setattr(self, "label", e.value)) \
                .props("dense").classes("grow")

    def set_id(self, v):
        self.node_id = v.strip() or None

    async def run(self, name, argv, env, log, procs):
        try:
            fl, n = self.candidate(name, argv, env)
        except core.FlowError as e:
            return {"ok": False, "error": str(e)}
        res = await self.page.engine_run(fl, [n.id], log=lambda i, line: log(line) if i == n.id else None)
        r = res.get(n.id)
        if r is None:  # cached
            r = {"ok": True, "seconds": 0.0, "cached": True, "log": "(cached)"}
        if not r["ok"]:
            return r
        child = await self.page.node_db(fl, n.id)
        refs = n.inputs()
        ref = await self.page.node_db(fl, refs[0]) if refs else None
        d = await run.io_bound(runner.diff, ref.res if ref else None, child.res)
        return {"ok": True, "child": child, "ref": ref, "diff": d, "name": name, "argv": argv, "env": env,
                "command": " ".join(n.lines()), "seconds": r.get("seconds", 0.0), "cached": r.get("cached"),
                "log": r.get("log", ""), "node": n}

    def show(self, panel):
        self.page.show_preview(panel)

    def commit_controls(self, panel):
        n = panel.result["node"]
        if self.edit:
            ui.button("Save change to %s" % n.id, icon="check", on_click=lambda: self.commit(panel)) \
                .props("color=positive")
        else:
            ui.button("Add %s to the flow" % n.id, icon="check", on_click=lambda: self.commit(panel)) \
                .props("color=positive")
        ui.button("Discard", icon="close", on_click=panel.discard).props("flat")

    async def commit(self, panel):
        n = panel.result["node"]
        try:
            if self.edit:
                self.page.fl.replace(n)
            else:
                self.page.fl.add(n)
            self.page.save()
        except (core.FlowError, OSError) as e:
            self.page.notify(str(e), type="negative")
            return
        edited = self.edit is not None
        panel.done()
        self.node_id, self.label = None, ""
        await self.page.after_change(n.id, edited)
        panel.render()

    def discard(self, panel):
        self.page.show_node()


class flow_page:
    def __init__(self, file, dark, history, jobs=2):
        self.file = os.path.abspath(file)
        self.dark = dark
        self.history = history
        self.jobs = jobs
        self.fl = core.flow.load(self.file)
        self.mtime = os.stat(self.file).st_mtime_ns
        self.en = core.engine(self.fl)
        self.lock = threading.Lock()  # one loader at a time
        self.selected = None
        self.states = {}  # id -> running/ok/failed during a run
        self.status = {}
        self.dbs = {}  # key -> database (a few)
        self.q = queue.Queue()
        self.busy = False
        self.procs = []
        self.view = None
        self.panel = None
        self.target = flow_target(self)
        self.base = self.fl.base

    def notify(self, msg, **kw):
        # from a persistent element: the element that triggered an action may be gone by now
        with self.summary:
            ui.notify(msg, **kw)

    # ---- engine in a worker thread ----
    async def engine_run(self, fl, targets=None, log=None):
        def work():
            en = core.engine(fl, self.en.work)
            return asyncio.run(en.run(targets, jobs=self.jobs, procs=self.procs,
                                      log=lambda i, line: self.q.put(("log", i, line)),
                                      state=lambda i, s: self.q.put(("state", i, s))))
        self.log_sink = log
        try:
            return await run.io_bound(work)
        except core.FlowError as e:
            self.notify(str(e), type="negative", multi_line=True)
            return {}
        finally:
            self.log_sink = None

    def drain(self):
        changed = False
        while True:
            try:
                kind, i, x = self.q.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                if self.log_sink:
                    self.log_sink(i, x)
                self.run_log.push("%s| %s" % (i, x))
            else:
                self.states[i] = x
                changed = True
        if changed:
            self.draw()

    async def node_db(self, fl, id, key=None):
        # database of a node (sources from their file, others reconstructed from the store)
        def load():
            with self.lock:
                en = core.engine(fl, self.en.work)
                k = key or en.keys()[id]
                if k in self.dbs:
                    return self.dbs[k]
                n = fl.nodes[id]
                res = jks.resamples(en.path(n.source)) if n.is_source() else en.load(k)
                db = database.database("%s (%s)" % (id, os.path.basename(fl.path)), res=res)
                db.rows()
                self.dbs = dict(list(self.dbs.items())[-3:])
                self.dbs[k] = db
                return db
        return await run.io_bound(load)

    def parent_db(self):
        # database the step panel's form offers tags of (loaded when a node is shown)
        p = self.target.parent()
        return self.shown_db if p and p == getattr(self, "shown_id", None) else None

    # ---- layout ----
    async def build(self):
        with ui.header().classes("items-center gap-2 py-1"):
            ui.label("jks flow").classes("text-lg font-bold")
            ui.button(icon="folder_open", on_click=self.pick).props("flat dense color=white").tooltip("open")
            ui.label(self.file).classes("text-sm opacity-80 grow truncate")
            self.summary = ui.label().classes("text-sm")
            self.run_btn = ui.button("Run stale", icon="play_arrow", on_click=self.run_stale) \
                .props("flat dense color=white").tooltip("compute every node that is not up to date")
            self.stop_btn = ui.button(icon="stop", on_click=self.stop).props("flat dense color=white").tooltip("stop")
            self.stop_btn.set_visibility(False)
            ui.button(icon="add_box", on_click=self.add_source).props("flat dense color=white").tooltip("add source database")
            ui.button(icon="list", on_click=self.add_list).props("flat dense color=white").tooltip("add list of words")
            ui.button(icon="add_task", on_click=self.start_add).props("flat dense color=white").tooltip("new step")
            ui.button(icon="dark_mode", on_click=self.toggle_dark).props("flat dense color=white").tooltip("dark mode")
        self.drawer = ui.right_drawer(value=False).props("width=520 bordered").classes("p-3")
        with ui.column().classes("w-full gap-1"):
            with ui.card().classes("w-full p-0").props("flat bordered"):
                self.chart = ui.echart({"series": []}, on_point_click=self.clicked).classes("w-full h-[30vh]")
            with ui.expansion("run log", icon="terminal").classes("w-full").props("dense"):
                self.run_log = ui.log(max_lines=5000).classes("w-full h-40").style(MONO)
            self.toolbar = ui.row().classes("w-full items-center gap-2")
            self.body = ui.column().classes("w-full")
        with self.drawer:
            self.panel = step_panel(self, self.target)
        ui.timer(0.2, self.drain)
        ui.timer(3.0, self.poll)
        await self.refresh()
        first = next((i for i in reversed(list(self.fl.nodes)) if self.fl.nodes[i].has_db()), None)
        if first:
            await self.select(first)

    def toggle_dark(self):
        self.dark.value = not self.dark.value
        self.draw()
        if self.view is not None:
            self.view.refresh_theme()

    async def pick(self):
        path = await file_picker(self.base, pattern=(".jks", ".sh"))
        if path:
            ui.navigate.to("/?file=" + path)

    # ---- graph ----
    async def refresh(self):
        self.status = dict((r["id"], r) for r in await run.io_bound(self.en.status))
        self.draw()

    def draw(self):
        pos = layout(self.fl)
        text = "#e4e4e0" if self.dark.value else "#2b2b28"
        data, links = [], []
        for i, n in self.fl.nodes.items():
            st = (self.states.get(i) if self.busy else None) or self.status.get(i, {}).get("status", "new")
            color, word = STATUS.get(st, STATUS["new"])
            info = self.status.get(i, {})
            desc = {"source": "source %s" % n.source, "list": "list %s" % " ".join(n.values),
                    "step": " ".join(n.lines()), "loop": "loop over %s: %s" % (", ".join(n.loop_vars()),
                                                                              ", ".join(c.name for c in n.body))}[n.kind]
            tip = "%s — %s%s<br>%s" % (i, word, (" (%s)" % info["reason"]) if info.get("reason") else "",
                                        desc.replace("<", "&lt;")[:300])
            if n.kind == "loop" and info.get("detail"):
                tip += "<br>" + info["detail"]
            sel = i == self.selected
            data.append({"name": i, "x": pos[i][0], "y": pos[i][1], "symbol": SYMBOL[n.kind],
                         "symbolSize": 22 if n.kind != "list" else 18, "value": word,
                         "itemStyle": {"color": color, "borderColor": text if sel else color, "borderWidth": 3 if sel else 1},
                         "label": {"show": True, "position": "bottom", "color": text, "fontWeight": "bold" if sel else "normal",
                                   "formatter": "%s\n%s" % (n.meta.get("label") or i, word)},
                         "tooltip": {"formatter": tip}})
            for r in n.inputs():
                dashed = r != n.parent
                links.append({"source": r, "target": i,
                              "lineStyle": {"type": "dashed" if dashed else "solid", "width": 1.5, "curveness": 0.15}})
        self.chart.options.clear()
        self.chart.options.update({
            "tooltip": {"trigger": "item", "confine": True},
            "animation": False,
            "series": [{"type": "graph", "layout": "none", "roam": True, "data": data, "links": links,
                        "top": 30, "bottom": 45, "left": 50, "right": 70,
                        "edgeSymbol": ["none", "arrow"], "edgeSymbolSize": 8,
                        "lineStyle": {"color": "#8f8d86", "opacity": 0.9},
                        "emphasis": {"focus": "adjacency"}}]})
        self.chart.update()
        counts = {}
        for r in self.status.values():
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        self.summary.text = ", ".join("%d %s" % (v, STATUS.get(k, ("", k))[1]) for k, v in sorted(counts.items()))

    async def clicked(self, e):
        if e.data_type == "node" and e.name in self.fl.nodes:
            await self.select(e.name)

    async def poll(self):
        # the flow file edited elsewhere, or inputs changed
        try:
            m = os.stat(self.file).st_mtime_ns
        except OSError:
            return
        if m != self.mtime:
            try:
                fl = core.flow.load(self.file)
            except core.FlowError as e:
                self.notify("the flow file has an error: %s" % e, type="negative", multi_line=True)
                self.mtime = m
                return
            self.fl, self.mtime = fl, m
            self.en = core.engine(fl, self.en.work)
            if self.selected not in fl.nodes:
                self.selected = None
            self.notify("reloaded %s" % os.path.basename(self.file))
            await self.refresh()
            await self.select(self.selected)
        elif not self.busy:
            old = dict((i, r["status"]) for i, r in self.status.items())
            await self.refresh()
            new = dict((i, r["status"]) for i, r in self.status.items())
            if new != old and self.selected:
                self.show_toolbar()
                if new.get(self.selected) != old.get(self.selected) and self.panel.result is None:
                    await self.show_node_async()

    def save(self):
        self.fl.save()
        self.mtime = os.stat(self.file).st_mtime_ns

    # ---- selection ----
    async def select(self, id):
        self.selected = id
        self.draw()
        self.show_toolbar()
        await self.show_node_async()
        if self.panel is not None and not self.target.edit:
            self.panel.render()

    def show_toolbar(self):
        self.toolbar.clear()
        id = self.selected
        if id is None:
            return
        n, info = self.fl.nodes[id], self.status.get(id, {})
        st = info.get("status", "new")
        color, word = STATUS.get(st, STATUS["new"])
        with self.toolbar:
            ui.label(id).classes("text-lg font-bold").style(MONO)
            ui.badge(n.kind, color="grey")
            ui.badge(word + (" (%s)" % info["reason"] if info.get("reason") else "")) \
                .style("background-color: %s !important; color: #111" % color)
            if info.get("detail"):
                ui.label(info["detail"]).classes("text-xs opacity-70")
            ui.space()
            if n.has_db():
                ui.button("Add step", icon="add", on_click=self.start_add).props("flat dense")
            if n.kind == "step":
                ui.button("Edit", icon="edit", on_click=lambda: self.start_edit(id)).props("flat dense")
            elif n.kind == "loop":
                ui.button("Edit", icon="edit").props("flat dense").disable()
                ui.label("(loops: edit the file for now)").classes("text-xs opacity-60")
            if st != "ok" and n.kind in ("step", "loop"):
                ui.button("Run", icon="play_arrow", on_click=lambda: self.run_nodes([id])).props("flat dense")
            if n.kind in ("step", "loop"):
                ui.button("Log", icon="article", on_click=lambda: self.show_log(id)).props("flat dense")
            if n.has_db() and st in ("ok", "stale"):
                ui.button("Export", icon="save_alt", on_click=lambda: self.export(id)).props("flat dense")
            if not self.fl.children(id):
                ui.button("Delete node", icon="delete", on_click=lambda: self.confirm_remove(id)) \
                    .props("flat dense color=negative")

    def show_node(self):
        asyncio.ensure_future(self.show_node_async())

    async def show_node_async(self):
        self.body.clear()
        self.view = None
        id = self.selected
        if id is None:
            with self.body:
                ui.label("Select a node in the graph.").classes("m-4")
            return
        n, info = self.fl.nodes[id], self.status.get(id, {})
        if n.kind == "list":
            with self.body:
                ui.label("list %s: %s" % (id, " ".join(n.values))).classes("m-4").style(MONO)
            return
        key = info.get("key") if info.get("status") == "ok" or n.is_source() else \
            info.get("built") if info.get("status") == "stale" else None
        if key is None:
            with self.body, ui.row().classes("m-4 items-center gap-2"):
                ui.label("%s is %s." % (id, STATUS.get(info.get("status", "new"), ("", "not computed"))[1]))
                if info.get("reason"):
                    ui.label(info["reason"]).classes("opacity-70")
                if n.kind in ("step", "loop"):
                    ui.button("Run", icon="play_arrow", on_click=lambda: self.run_nodes([id]))
            return
        with self.body, ui.row().classes("m-4 items-center"):
            ui.spinner()
            ui.label("loading %s ..." % id)
        try:
            db = await self.node_db(self.fl, id, key)
        except Exception as e:
            self.body.clear()
            with self.body:
                ui.label("ERROR: %s" % e).classes("m-4 text-negative")
            return
        if self.selected != id:
            return
        self.shown_id, self.shown_db = id, db
        self.body.clear()
        with self.body:
            if info.get("status") == "stale":
                with ui.row().classes("w-full items-center gap-2 px-3 py-1 bg-amber-100 dark:bg-amber-900 rounded"):
                    ui.icon("history")
                    ui.label("stale (%s): showing the last computed result" % info.get("reason", "")).classes("text-sm grow")
                    ui.button("Run", icon="play_arrow", on_click=lambda: self.run_nodes([id])).props("flat dense")
            self.view = database_view(db, self.dark, fit_source=self.fit_source, on_delete=self.propose_rm,
                                      height="calc(70vh - 7rem)")
        if self.panel is not None and not self.target.edit and self.panel.result is None:
            self.panel.render()

    def active_tag(self):
        v = self.view
        return v.active if v is not None and v.active is not None else None

    # ---- actions ----
    def start_add(self):
        self.target.edit = None
        self.drawer.value = True
        self.panel.render()
        self.panel.fill_active()

    def start_edit(self, id):
        n = self.fl.nodes[id]
        self.target.edit = id
        self.drawer.value = True
        self.panel.load_command(n.cmd.name, n.cmd.argv, n.cmd.env)

    def propose_rm(self, tags):
        # deleting tags in a flow is a jks_rm node after the selected one
        async def go():
            self.target.edit = None
            self.drawer.value = True
            self.panel.load_command("jks_rm", ["@"] + [glob.escape(t) for t in tags], {})
            self.notify("jks_rm prepared in the step panel: Preview, then add it to the flow", type="info")
        return go()

    def show_preview(self, panel):
        self.body.clear()
        with self.body:
            title = "PREVIEW of the change to %s" % self.target.edit if self.target.edit else "PREVIEW of a new node"
            self.view = preview_view(panel.result, self.dark, self.fit_source, panel.commit_controls,
                                     height="calc(70vh - 9rem)", title=title)

    async def after_change(self, id, edited):
        self.target.edit = None
        await self.refresh()
        await self.select(id)
        if edited:
            after = sorted(self.fl.descendants(id), key=list(self.fl.nodes).index)
            if after:
                self.notify("%s changed: recomputing %s" % (id, ", ".join(after)))
                await self.run_nodes(after)

    async def run_nodes(self, ids):
        if self.busy:
            self.notify("a run is in progress", type="warning")
            return
        self.busy = True
        self.run_btn.disable()
        self.stop_btn.set_visibility(True)
        try:
            res = await self.engine_run(self.fl, ids)
        finally:
            self.drain()  # state events still in the queue belong to this run
            self.busy = False
            self.states = {}
            self.run_btn.enable()
            self.stop_btn.set_visibility(False)
        bad = [i for i, r in res.items() if not r["ok"]]
        if bad:
            self.notify("failed: %s" % ", ".join("%s (%s)" % (i, res[i]["error"].splitlines()[0]) for i in bad),
                      type="negative", multi_line=True)
        elif res:
            self.notify("computed %d node%s" % (len(res), "" if len(res) == 1 else "s"), type="positive")
        else:
            self.notify("nothing to compute: %s up to date (cached)" % ", ".join(ids[:6]), type="positive")
        await self.refresh()
        self.show_toolbar()
        await self.show_node_async()

    async def run_stale(self):
        todo = [i for i, r in self.status.items() if r["status"] not in ("ok", "missing")]
        if not todo:
            self.notify("everything is up to date")
            return
        await self.run_nodes(todo)

    def stop(self):
        for p in list(self.procs):
            try:
                p.kill()
            except (ProcessLookupError, RuntimeError):
                pass

    def show_log(self, id):
        info = self.status.get(id, {})
        st = self.en._read_json("state.json")
        f = st.get("failed", {}).get(id, {})
        m = self.en.meta(info.get("key") or "") or self.en.meta(info.get("built") or "")
        text = f.get("log") if f and f.get("key") == info.get("key") else (m or {}).get("log", "")
        with ui.dialog() as dlg, ui.card().classes("w-[60rem] max-w-full"):
            ui.label("log of %s" % id).classes("text-lg font-bold")
            if f and f.get("key") == info.get("key"):
                ui.label("failed: %s" % f.get("error", "")).classes("text-negative text-sm whitespace-pre-wrap")
            ui.code(text or "(no output)").classes("w-full max-h-[60vh] overflow-auto")
            ui.button("Close", on_click=dlg.close).props("flat")
        dlg.open()

    async def export(self, id):
        with ui.dialog() as dlg, ui.card().classes("w-[36rem]"):
            ui.label("Export the database of %s" % id).classes("font-bold")
            path = ui.input("file", value=os.path.join(self.base, id + ".jks")).classes("w-full").style(MONO)

            async def go():
                p = os.path.abspath(os.path.expanduser(path.value))
                if os.path.exists(p):
                    self.notify("%s exists" % p, type="negative")
                    return
                dlg.close()
                await run.io_bound(core.engine(self.fl, self.en.work).export, id, p)
                self.notify("wrote %s" % p, type="positive")
            with ui.row():
                ui.button("Export", on_click=go)
                ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()

    def confirm_remove(self, id):
        with ui.dialog() as dlg, ui.card():
            ui.label("Remove node %s from the flow?" % id).classes("font-bold")
            ui.label("Its stored result stays in the work directory until jks_flow gc.").classes("text-xs opacity-70")

            async def go():
                dlg.close()
                self.fl.remove(id)
                self.save()
                await self.refresh()
                await self.select(None)
            with ui.row():
                ui.button("Remove", on_click=go).props("color=negative")
                ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()

    def unique(self, base):
        base = re.sub(r"[^A-Za-z0-9_.-]", "_", base) or "node"
        if not core.ID.match(base):
            base = "n" + base
        i, k = base, 2
        while i in self.fl.nodes:
            i, k = "%s.%d" % (base, k), k + 1
        return i

    async def add_source(self):
        path = await file_picker(self.base)
        if not path:
            return
        with ui.dialog() as dlg, ui.card():
            ui.label("source %s" % path).classes("text-sm break-all")
            nid = ui.input("node id", value=self.unique(os.path.splitext(os.path.basename(path))[0])).style(MONO)

            async def go():
                p = os.path.relpath(path, self.base)
                try:
                    self.fl.add(core.node(nid.value, "source", source=path if p.startswith("..") else p))
                    self.save()
                except core.FlowError as e:
                    self.notify(str(e), type="negative")
                    return
                dlg.close()
                await self.refresh()
                await self.select(nid.value)
            with ui.row():
                ui.button("Add", on_click=go)
                ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()

    def add_list(self):
        with ui.dialog() as dlg, ui.card().classes("w-[30rem]"):
            ui.label("A list of words for loops ($(jks_list_values id))").classes("text-sm")
            nid = ui.input("node id", value=self.unique("list")).style(MONO)
            words = ui.input("words, separated by spaces").classes("w-full").style(MONO)

            async def go():
                try:
                    self.fl.add(core.node(nid.value, "list", values=words.value.split()))
                    self.save()
                except core.FlowError as e:
                    self.notify(str(e), type="negative")
                    return
                dlg.close()
                await self.refresh()
                await self.select(nid.value)
            with ui.row():
                ui.button("Add", on_click=go)
                ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()

    def fit_source(self, fit):
        # the jks_fit step of the flow that wrote the tag fit
        for n in self.fl.nodes.values():
            if n.kind == "step" and n.cmd.name in ("jks_fit", "jks_slow_fit"):
                v = n.cmd.values()
                if v["tail"][1] == fit:
                    return {"functions": dict((r[0], r[2]) for r in v["repeat"]),
                            "ranges": dict((r[0], r[1]) for r in v["repeat"]), "env": n.cmd.env,
                            "command": " ".join(n.lines())}
        return None
