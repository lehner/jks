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
# Step panel: compose one jks_* command from its signature (or paste one),
# preview its result on a copy, then commit or discard it.  What the step
# applies to is a target: db_target (a database file, below) or a flow node
# (flowview.flow_target); the panel only talks to its target.
#
import os
from nicegui import run, ui
import jks
from jks.flow import registry, runner
from jks.gui import database
from jks.gui.filepicker import file_picker

MONO = "font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem"


def preview_view(r, dark, fit_source, controls, height="calc(100vh - 8rem)", title="PREVIEW"):
    # banner with the command and the commit buttons, then the result with its diff
    from jks.gui.browser import database_view
    with ui.row().classes("w-full items-center gap-2 px-3 py-1 bg-amber-100 dark:bg-amber-900 rounded"):
        ui.icon("visibility")
        ui.label(title).classes("font-bold")
        ui.label(r["command"]).classes("grow truncate text-xs").style(MONO)
        controls()
    spec = registry.BY_NAME[r["name"]]
    v = spec.parse(r["argv"])
    fit = v["tail"][1] if r["name"] in ("jks_fit", "jks_slow_fit") else None
    return database_view(r["child"], dark, diff=r["diff"], ref=r["ref"], fit_source=fit_source,
                         inputs=spec.tags_in(v), fit=fit, height=height)


def rel(base, p):
    # paths below base as the user would type them there
    p = os.path.abspath(p)
    r = os.path.relpath(p, base)
    return p if r.startswith("..") else r


class db_target:
    # steps on the database file open in a db_page: preview in the work directory,
    # commit replaces the file (or saves a new one)
    def __init__(self, page):
        self.page = page

    @property
    def db(self):
        return self.page.db

    def where(self):
        return "work directory: %s" % self.page.work.root

    def primary_default(self, spec):
        if spec.primary_kind() in ("db", "db_maybe"):
            return rel(self.page.base, self.db.path) if self.db is not None else ""
        return "new.jks"

    def input_default(self):
        return rel(self.page.base, self.db.path) if self.db is not None else ""

    def inputs(self):
        return []

    def primary_label(self, x):
        return x or "(no database open)"

    def check(self, name, argv, env):
        return runner.step(name, argv, env, self.page.base).check(self.db)

    def normalize(self, spec, values):
        if spec.primary_kind() in ("db", "db_maybe") and self.db is not None and \
                os.path.abspath(os.path.join(self.page.base, spec.get_primary(values))) != self.db.path:
            ui.notify("the step applies to the open database %s" % rel(self.page.base, self.db.path), type="info")
            values = spec.set_primary(values, rel(self.page.base, self.db.path))
        return values

    def render_extra(self, panel):
        pass

    async def run(self, name, argv, env, log, procs):
        st = runner.step(name, argv, env, self.page.base)
        m = await self.page.work.run(st, log=log, procs=procs)
        if not m["ok"]:
            return m
        child = await run.io_bound(database.load, self.page.work.node(m["key"]))
        ref = await run.io_bound(database.load, m["reference"]) if m["reference"] else None
        d = await run.io_bound(runner.diff, ref.res if ref else None, child.res)
        return {"ok": True, "meta": m, "child": child, "ref": ref, "diff": d, "name": name, "argv": argv,
                "env": env, "command": m["command"], "seconds": m["seconds"], "cached": m.get("cached"),
                "log": m["log"]}

    def show(self, panel):
        self.page.show_preview(panel)

    def commit_controls(self, panel):
        m = panel.result["meta"]
        if m["kind"] in ("db", "db_maybe") and self.db is not None and m["primary"] == self.db.path:
            ui.button("Commit to %s" % os.path.basename(m["primary"]), icon="check",
                      on_click=lambda: self.commit(panel, None)).props("color=positive")
        else:
            target = ui.input("save as", value=rel(self.page.base, m["primary"])).props("dense").style(MONO)
            ui.button("Save", icon="save", on_click=lambda: self.commit(panel, target.value)).props("color=positive")
        ui.button("Discard", icon="close", on_click=panel.discard).props("flat")

    async def commit(self, panel, target):
        m = panel.result["meta"]
        try:
            path = self.page.work.commit(m, target)
        except (RuntimeError, FileExistsError) as e:
            ui.notify(str(e), type="negative")
            return
        ui.notify("committed: %s" % m["command"], type="positive")
        panel.done()
        await self.page.after_commit(path)
        panel.render()  # tag lists and checks against the new state

    def discard(self, panel):
        self.page.show_current()


class step_panel:
    def __init__(self, page, target=None):
        self.page = page
        self.target = target or db_target(page)
        self.name = "jks_add"
        self.env = {}
        self.values = self.defaults(self.name)
        self.result = None
        self.procs = []
        self.running = False
        self.build()

    # ---- state ----
    def rel(self, p):
        return rel(self.page.base, p)

    def defaults(self, name):
        spec = registry.BY_NAME[name]
        v = spec.set_primary(spec.empty(), self.target.primary_default(spec))
        cur = self.target.input_default()
        if spec.primary_kind() == "db_new":
            for a, x, (sec, i, j) in spec.items(v):
                if a.kind == "db_in":
                    if j is None:
                        v[sec][i] = cur
                    else:
                        v[sec][i][j] = cur
                    break
        self.fill_tag_in(spec, v)
        return v

    def fill_tag_in(self, spec, v):
        # an empty first input tag defaults to the tag being inspected (jks_fit: tag of #1)
        tag = self.page.active_tag()
        if tag is None:
            return False
        for a, x, (sec, i, j) in spec.items(v):
            if a.kind == "tag_in":
                if x:
                    return False
                if j is None:
                    v[sec][i] = tag
                else:
                    v[sec][i][j] = tag
                return True
        return False

    def fill_active(self):
        if self.fill_tag_in(self.spec(), self.values):
            self.render()

    def spec(self):
        return registry.BY_NAME[self.name]

    def argv(self):
        return self.spec().build(self.values)

    def command(self):
        # in a loop, arguments with $var are double quoted (as in the flow file)
        q = getattr(self.target, "quote", None)
        return registry.join_command(self.env, self.name, self.argv(), q() if q else None)

    def load_command(self, name, argv, env):
        # fill the form from an existing command (editing a flow node)
        self.name, self.values, self.env = name, registry.BY_NAME[name].parse(argv), dict(env)
        self.script_sel.value = name
        self.render()

    # ---- layout ----
    def build(self):
        with ui.column().classes("w-full gap-2"):
            with ui.row().classes("w-full items-center no-wrap"):
                opts = dict((s.name, "%s · %s" % (s.group, s.name))
                            for g in registry.GROUPS for s in registry.SCRIPTS if s.group == g)
                self.script_sel = ui.select(opts, value=self.name, label="script", with_input=True,
                                            on_change=lambda e: self.set_script(e.value)).classes("grow")
            self.help = ui.label().classes("text-xs opacity-70")
            self.extra = ui.column().classes("w-full gap-1")
            self.form = ui.column().classes("w-full gap-1")
            self.env_box = ui.column().classes("w-full gap-1")
            with ui.row().classes("w-full items-center no-wrap mt-2"):
                ui.label("command (edit or paste, then Enter)").classes("text-xs opacity-70 grow")
                self.cmd_history = ui.row().classes("gap-0")
            self.cmd = ui.textarea().props("dense outlined autogrow").classes("w-full jks-cmd").style(MONO)
            self.cmd.on("keydown.enter.prevent", self.parse_command)
            self.checks = ui.column().classes("w-full gap-0")
            with ui.row().classes("items-center gap-2"):
                self.run_btn = ui.button("Preview", icon="play_arrow", on_click=self.preview)
                self.stop_btn = ui.button("Stop", icon="stop", on_click=self.stop).props("flat color=negative")
                self.stop_btn.set_visibility(False)
                self.spinner = ui.spinner(size="md")
                self.spinner.set_visibility(False)
            self.log = ui.log(max_lines=5000).classes("w-full h-48").style(MONO)
            self.outcome = ui.column().classes("w-full")
            self.where = ui.label(self.target.where()).classes("text-xs opacity-60 break-all")
        self.render()

    def set_script(self, name):
        if name == self.name:
            return
        self.name = name
        self.values = self.defaults(name)
        self.env = dict((k, v) for k, v in self.env.items() if k in dict(self.spec().env))
        self.render()

    def render(self):
        spec = self.spec()
        self.help.text = spec.help
        self.extra.clear()
        with self.extra:
            self.target.render_extra(self)
        self.where.text = self.target.where()
        self.form.clear()
        keys = self.target.db.keys() if self.target.db is not None else []
        with self.form:
            if spec.head:
                self.render_items([it for it in spec.items(self.values) if it[2][0] == "head"], keys)
            if spec.repeat:
                for k, r in enumerate(self.values["repeat"]):
                    with ui.card().classes("w-full p-2 gap-1").props("flat bordered"):
                        with ui.row().classes("w-full items-center no-wrap"):
                            ui.label("#%d" % (k + 1)).classes("text-xs opacity-70 grow")
                            if len(self.values["repeat"]) > 1:
                                ui.button(icon="close", on_click=lambda k=k: self.remove_group(k)) \
                                    .props("flat dense size=sm")
                        self.render_items([it for it in spec.items(self.values)
                                           if it[2][0] == "repeat" and it[2][1] == k], keys)
                ui.button("add %s" % " / ".join(a.name for a in spec.repeat), icon="add",
                          on_click=self.add_group).props("flat dense size=sm")
            self.render_items([it for it in spec.items(self.values) if it[2][0] == "tail"], keys)
            for i, a in enumerate(spec.optional):
                on = i < len(self.values["optional"])
                with ui.row().classes("w-full items-center no-wrap gap-1"):
                    ui.checkbox(value=on, on_change=lambda e, i=i: self.toggle_optional(i, e.value)).props("dense")
                    if on:
                        self.widget(a, self.values["optional"][i], ("optional", i, None), keys)
                    else:
                        ui.label("%s (optional, default %s)" % (a.name, a.default)).classes("text-sm opacity-60")
        self.cmd_history.clear()
        with self.cmd_history:
            self.history_button("command", self.put_command)
        self.env_box.clear()
        if spec.env:
            with self.env_box, ui.expansion("environment", icon="tune").classes("w-full").props("dense"):
                for var, help in spec.env:
                    with ui.row().classes("w-full items-center no-wrap gap-1"):
                        ui.checkbox(value=var in self.env,
                                    on_change=lambda e, var=var: self.toggle_env(var, e.value)).props("dense")
                        inp = ui.input(var, value=self.env.get(var, "")).props("dense").classes("grow").style(MONO)
                        inp.tooltip(help)
                        inp.on_value_change(lambda e, var=var: self.set_env(var, e.value))
                        self.history_button("env:" + var, lambda v, inp=inp: inp.set_value(v))
        self.refresh_command()

    def render_items(self, items, keys):
        for a, x, loc in items:
            self.widget(a, x, loc, keys)

    def widget(self, a, x, loc, keys):
        label = a.name
        cb = lambda e, loc=loc: self.set_value(loc, e.value)
        if a.kind in ("db", "db_maybe"):
            ui.label("%s: %s%s" % (label, self.target.primary_label(x),
                                    "  (created if missing)" if a.kind == "db_maybe" else "")).classes("text-sm")
            return
        with ui.row().classes("w-full items-center no-wrap gap-1"):
            nodes = self.target.inputs()
            if a.kind == "db_in" and nodes:
                # a flow node (@id) or a database file
                w = ui.select(sorted(set(nodes) | ({x} if x else set())), value=x or None, label=label,
                              with_input=True, new_value_mode="add-unique",
                              on_change=lambda e, loc=loc: self.set_value(loc, e.value or "")) \
                    .props("dense").classes("grow")

                def put(v, w=w):
                    w.options = sorted(set(w.options) | {v})
                    w.value = v
            elif a.kind == "tag_in" and keys:
                opts = sorted(set(keys) | ({x} if x else set()))
                w = ui.select(opts, value=x or None, label=label, with_input=True, new_value_mode="add-unique",
                              on_change=lambda e, loc=loc: self.set_value(loc, e.value or "")) \
                    .props("dense").classes("grow")

                def put(v, w=w):
                    w.options = sorted(set(w.options) | {v})
                    w.value = v
            else:
                if a.kind == "expr":
                    w = ui.textarea(label, value=x).props("dense autogrow")
                else:
                    w = ui.input(label + (" (new file)" if a.kind == "db_new" else ""), value=x).props("dense")
                w.classes("grow").style(MONO)
                w.on_value_change(cb)
                if a.kind == "tag_out" and keys:
                    w.validation = {"exists already": lambda v, k=set(keys): v not in k}

                def put(v, w=w):
                    w.value = v
            if a.kind == "db_in":
                ui.button(icon="folder_open", on_click=lambda w=w: self.pick(w)).props("flat dense")
            self.history_button("%s:%s" % (self.name, a.name), put)
        if a.help:
            w.tooltip(a.help)

    def history_button(self, key, put):
        # recently used values of this field, newest first
        vals = self.page.history.get(key)
        if not vals:
            return
        with ui.button(icon="history").props("flat dense size=sm").tooltip("recent values"):
            with ui.menu():
                for v in vals:
                    ui.menu_item(v if len(v) <= 90 else v[:87] + "...", on_click=lambda v=v: put(v)).style(MONO)

    def remember(self, name, argv, env):
        spec = registry.BY_NAME[name]
        e = [("%s:%s" % (name, a.name), x) for a, x, _ in reversed(list(spec.items(spec.parse(argv))))
             if a.kind not in ("db", "db_maybe")]
        e += [("env:" + k, v) for k, v in env.items()]
        e.append(("command", registry.join_command(env, name, argv)))
        try:
            self.page.history.add(e)
        except OSError as err:
            ui.notify("cannot save the input history: %s" % err, type="warning")

    async def pick(self, w):
        path = await file_picker(self.page.base)
        if path:
            if isinstance(w, ui.select):
                w.options = sorted(set(w.options) | {self.rel(path)})
            w.value = self.rel(path)

    # ---- edits ----
    def set_value(self, loc, x):
        sec, i, j = loc
        if j is None:
            self.values[sec][i] = x
        else:
            self.values[sec][i][j] = x
        self.refresh_command()

    def add_group(self):
        self.values["repeat"].append([a.default or "" for a in self.spec().repeat])
        self.render()

    def remove_group(self, k):
        del self.values["repeat"][k]
        self.render()

    def toggle_optional(self, i, on):
        opt = self.spec().optional
        if on:
            while len(self.values["optional"]) <= i:
                self.values["optional"].append(opt[len(self.values["optional"])].default or "")
        else:
            del self.values["optional"][i:]
        self.render()

    def toggle_env(self, var, on):
        if on:
            self.env[var] = self.env.get(var, "")
        else:
            self.env.pop(var, None)
        self.refresh_command()

    def set_env(self, var, v):
        if var in self.env or v:
            self.env[var] = v
        self.refresh_command()

    def refresh_command(self):
        self.cmd.value = self.command()
        self.checks.clear()
        try:
            msgs = self.target.check(self.name, self.argv(), self.env)
        except Exception as e:
            msgs = [str(e)]
        with self.checks:
            for m in msgs:
                ui.label("⚠ " + m).classes("text-xs text-warning")

    def put_command(self, v):
        self.cmd.value = v
        self.parse_command()

    def parse_command(self):
        try:
            env, name, argv = registry.split_command(self.cmd.value)
            values = registry.BY_NAME[name].parse(argv)
        except ValueError as e:
            ui.notify(str(e), type="warning")
            return
        values = self.target.normalize(registry.BY_NAME[name], values)
        self.name, self.values, self.env = name, values, env
        self.script_sel.value = name
        self.render()

    # ---- run ----
    async def preview(self):
        if self.running:
            return
        name, env = self.name, dict(self.env)
        try:
            argv = self.argv()
            self.spec().parse(argv)
        except (ValueError, AssertionError) as e:
            ui.notify(str(e), type="warning")
            return
        self.running = True
        self.run_btn.disable()
        self.stop_btn.set_visibility(True)
        self.spinner.set_visibility(True)
        self.log.clear()
        self.outcome.clear()
        self.log.push("$ " + registry.join_command(env, name, argv))
        self.remember(name, argv, env)
        try:
            m = await self.target.run(name, argv, env, self.log.push, self.procs)
        except Exception as e:
            m = {"ok": False, "error": str(e)}
        finally:
            self.running = False
            self.run_btn.enable()
            self.stop_btn.set_visibility(False)
            self.spinner.set_visibility(False)
            self.render()  # new history entries
        if not m["ok"]:
            with self.outcome:
                ui.label("ERROR: " + m["error"]).classes("text-negative text-sm")
            return
        self.show_result(m)

    def stop(self):
        for p in list(self.procs):
            try:
                p.kill()
            except ProcessLookupError:
                pass

    def show_result(self, m):
        # m: result of target.run (child, ref, diff, ...)
        self.result = m
        d = m["diff"]
        self.outcome.clear()
        with self.outcome:
            with ui.row().classes("items-center gap-1"):
                ui.label("%s in %.2fs%s" % ("result", m["seconds"], ", cached" if m.get("cached") else "")) \
                    .classes("text-sm")
                for k, c, lab in [("added", "positive", "new"), ("modified", "warning", "modified"),
                                  ("removed", "negative", "removed")]:
                    if d[k]:
                        ui.badge("%d %s" % (len(d[k]), lab), color=c)
                for k, lab in [("variations_added", "+var"), ("variations_removed", "-var"),
                               ("configs_added", "+cfg"), ("configs_removed", "-cfg")]:
                    if d[k]:
                        ui.badge("%s %s" % (lab, ", ".join(d[k][:3]) + ("..." if len(d[k]) > 3 else "")),
                                 color="grey")
            bad = d["nonfinite"]
            if m["name"] in ("jks_fit", "jks_slow_fit"):
                # nan marks the points outside the fit range in <fit>.<tag>.input.<j>
                fit = registry.BY_NAME[m["name"]].parse(m["argv"])["tail"][1]
                bad = [t for t in bad if not (t.startswith(fit + ".") and ".input." in t)]
            if bad:
                ui.label("⚠ non-finite numbers in %s" % ", ".join(bad[:5])).classes("text-xs text-warning")
            if any("ERROR" in l for l in m["log"].splitlines()):
                ui.label("⚠ the script printed ERROR").classes("text-xs text-warning")
        self.target.show(self)

    def commit_controls(self):
        # buttons for the preview banner
        self.target.commit_controls(self)

    def done(self):
        self.result = None
        self.outcome.clear()

    def discard(self):
        self.done()
        self.target.discard(self)
