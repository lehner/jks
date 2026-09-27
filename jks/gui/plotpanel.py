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
# Plot panel: the commands of a jks_plot2 figure of a flow node, as rows with
# fields or as text (one command per line), previewed before it is added.
#
import os, re
from nicegui import ui
from jks.flow import core

MONO = "font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem"

# command types of jks_plot2: (label, prefix, fields); a field is (name, kind)
TYPES = {
    "c": ("correlator (stat and total errors)", "c", [("lt", "lt"), ("tag", "tag"), ("title", "text")]),
    "e": ("errors only", "e", [("lt", "lt"), ("tag", "tag"), ("title", "text")]),
    "f": ("fit band", "f", [("lt", "lt"), ("fit", "tag"), ("function of x, p", "text"), ("from", "num"),
                           ("to", "num"), ("title", "text")]),
    "p": ("x-y (tags)", "p", [("lt", "lt"), ("x tag", "tag"), ("y tag", "tag"), ("title", "text")]),
    "l": ("function line", "l", [("lt", "lt"), ("function of x", "text"), ("title", "text")]),
    "d": ("data point", "d", [("lt", "lt"), ("x", "num"), ("y", "num"), ("error", "num"), ("title", "text")]),
    "xr": ("x range", "xr", [("from", "num"), ("to", "num")]),
    "yr": ("y range", "yr", [("from", "num"), ("to", "num")]),
    "xl": ("x label", "xl", [("label", "text")]),
    "yl": ("y label", "yl", [("label", "text")]),
    "ls": ("log scale", "ls", [("axes (x, y, xy; empty: linear)", "text")]),
    "k": ("key position", "k", [("e.g. top left", "text")]),
    "vl": ("vertical line", "vl", [("x", "num")]),
    "newpage": ("new page", "newpage", []),
    "raw": ("other (as typed)", "", [("command", "text")]),
}


def parse(cmd):
    # command string -> (type, [field values]); unknown forms stay raw
    if cmd == "newpage":
        return "newpage", []
    for t in ("xr", "yr", "xl", "yl", "ls", "vl", "k"):
        if cmd == t or cmd.startswith(t + ":"):
            a = cmd.split(":")[1:]
            n = len(TYPES[t][2])
            if len(a) <= n:
                return t, a + [""] * (n - len(a))
    m = re.match(r"^([cefpld])(\d+):(.*)$", cmd)
    if m and not cmd.startswith(("xl", "xr")):
        t, a = m.group(1), [m.group(2)] + m.group(3).split(":")
        n = len(TYPES[t][2])
        if len(a) <= n:
            return t, a + [""] * (n - len(a))
    return "raw", [cmd]


def build(t, vals):
    if t == "raw":
        return vals[0]
    if t == "newpage":
        return "newpage"
    prefix = TYPES[t][1]
    vals = list(vals)
    while vals and vals[-1] == "" and len(vals) > 1:
        vals.pop()  # optional trailing fields (titles)
    if t in ("c", "e", "f", "p", "l", "d"):
        return "%s%s:%s" % (prefix, vals[0] or "1", ":".join(vals[1:]))
    return ":".join([prefix] + vals) if vals and vals != [""] else prefix


class plot_panel:
    def __init__(self, page):
        self.page = page
        self.edit = None
        self.rows = []  # [type, [values]]
        self.node_id, self.label = None, ""
        self.script, self.save, self.out = "jks_plot2", False, ""
        self.result = None
        with ui.column().classes("w-full gap-2") as self.box:
            self.head = ui.column().classes("w-full gap-1")
            self.list = ui.column().classes("w-full gap-1")
            with ui.row().classes("items-center gap-1"):
                with ui.button("add", icon="add").props("flat dense size=sm"):
                    with ui.menu():
                        for t, (lab, _, _) in TYPES.items():
                            ui.menu_item(lab, on_click=lambda t=t: self.add(t))
            ui.label("commands, one per line (edit or paste, then leave the field)").classes("text-xs opacity-70")
            self.text = ui.textarea().props("dense outlined autogrow").classes("w-full jks-plot-cmds").style(MONO)
            self.text.on("blur", self.parse_text)
            self.checks = ui.column().classes("w-full gap-0")
            with ui.row().classes("items-center gap-2"):
                self.run_btn = ui.button("Preview", icon="play_arrow", on_click=self.preview)
                self.spinner = ui.spinner(size="md")
                self.spinner.set_visibility(False)
            self.log = ui.log(max_lines=500).classes("w-full h-32").style(MONO)

    # ---- state ----
    def input(self):
        if self.edit:
            return self.page.fl.nodes[self.edit].parent
        s = self.page.selected
        return s if s and self.page.fl.nodes[s].has_db() else None

    def start(self, cmds=(), edit=None):
        self.edit = edit
        if edit:
            n = self.page.fl.nodes[edit]
            cmds = n.plot["cmds"]
            self.script, self.out = n.plot["script"], n.plot["out"]
            self.save = self.out != "-"
            self.node_id, self.label = edit, n.meta.get("label", "")
        else:
            self.node_id, self.label, self.script = None, "", "jks_plot2"
            self.save, self.out = False, ""
        self.rows = [list(parse(c)) for c in cmds]
        self.result = None
        self.render()

    def cmds(self):
        return [build(t, v) for t, v in self.rows if build(t, v)]

    def default_id(self):
        base = "plot.%s" % (self.input() or "x")
        i, k = base, 2
        while i in self.page.fl.nodes:
            i, k = "%s.%d" % (base, k), k + 1
        return i

    def node(self):
        i = self.edit or self.node_id or self.default_id()
        out = (self.out or "plots/%s.pdf" % i) if self.save else "-"
        meta = dict(self.page.fl.nodes[self.edit].meta) if self.edit else {}
        if self.label:
            meta["label"] = self.label
        return core.node(i, "plot", self.input(), meta=meta,
                         plot={"script": self.script, "out": out, "cmds": self.cmds()})

    def candidate(self):
        n = self.node()
        fl = self.page.fl.copy()
        if self.edit:
            fl.replace(n)
        else:
            fl.add(n)
        return fl, n

    # ---- layout ----
    def render(self):
        self.head.clear()
        with self.head:
            inp = self.input()
            ui.label(("editing plot %s" % self.edit) if self.edit else
                     ("new plot of %s" % inp if inp else "new plot (select a database node)")).classes("text-sm font-bold")
            with ui.row().classes("w-full items-center no-wrap gap-1"):
                if not self.edit:
                    ui.input("node id", value=self.node_id or "", placeholder=self.default_id(),
                             on_change=lambda e: setattr(self, "node_id", e.value.strip() or None)) \
                        .props("dense").classes("grow").style(MONO)
                ui.input("label", value=self.label, on_change=lambda e: setattr(self, "label", e.value)) \
                    .props("dense").classes("grow")
                ui.select(list(core.PLOTTERS), value=self.script, on_change=lambda e: setattr(self, "script", e.value)) \
                    .props("dense").classes("w-28")
            with ui.row().classes("w-full items-center no-wrap gap-1"):
                ui.checkbox("save to disk", value=self.save, on_change=lambda e: self.set_save(e.value)).props("dense")
                self.out_in = ui.input("file (relative to the flow)", value=self.out,
                                       placeholder="plots/%s.pdf" % (self.edit or self.node_id or self.default_id()),
                                       on_change=lambda e: setattr(self, "out", e.value.strip())) \
                    .props("dense").classes("grow").style(MONO)
                self.out_in.set_visibility(self.save)
        self.render_rows()

    def set_save(self, v):
        self.save = v
        self.out_in.set_visibility(v)

    def render_rows(self):
        self.list.clear()
        db = self.page.parent_db_for(self.input())
        tags = db.keys() if db is not None else []
        with self.list:
            for k, (t, vals) in enumerate(self.rows):
                with ui.card().classes("w-full p-1 gap-0").props("flat bordered"):
                    with ui.row().classes("w-full items-center no-wrap gap-1"):
                        ui.select(dict((x, TYPES[x][0]) for x in TYPES), value=t,
                                  on_change=lambda e, k=k: self.set_type(k, e.value)).props("dense").classes("w-44")
                        ui.space()
                        ui.button(icon="arrow_upward", on_click=lambda k=k: self.move(k, -1)).props("flat dense size=xs")
                        ui.button(icon="close", on_click=lambda k=k: self.remove(k)).props("flat dense size=xs")
                    with ui.row().classes("w-full items-center gap-1"):
                        for j, (name, kind) in enumerate(TYPES[t][2]):
                            cb = lambda e, k=k, j=j: self.set_value(k, j, e.value)
                            if kind == "tag" and tags:
                                opts = sorted(set(tags) | ({vals[j]} if vals[j] else set()))
                                ui.select(opts, value=vals[j] or None, label=name, with_input=True,
                                          new_value_mode="add-unique",
                                          on_change=lambda e, k=k, j=j: self.set_value(k, j, e.value or "")) \
                                    .props("dense").classes("w-40")
                            else:
                                w = {"lt": "w-12", "num": "w-20"}.get(kind, "grow")
                                ui.input(name, value=vals[j], on_change=cb).props("dense").classes(w).style(MONO)
        self.sync_text()

    def sync_text(self):
        self.text.value = "\n".join(self.cmds())
        self.checks.clear()
        try:
            self.candidate()
            msgs = []
        except core.FlowError as e:
            msgs = [str(e)]
        with self.checks:
            for m in msgs:
                ui.label("⚠ " + m).classes("text-xs text-warning")

    # ---- edits ----
    def add(self, t):
        n = len(TYPES[t][2])
        lts = [int(v[0]) for tt, v in self.rows if tt in ("c", "e", "f", "p", "l", "d") and v and v[0].isdigit()]
        vals = [""] * n
        if t in ("c", "e", "f", "p", "l", "d"):
            vals[0] = str(max(lts, default=0) + 1)
        self.rows.append([t, vals])
        self.render_rows()

    def set_type(self, k, t):
        self.rows[k] = [t, [""] * len(TYPES[t][2])]
        self.render_rows()

    def set_value(self, k, j, v):
        self.rows[k][1][j] = v
        self.sync_text()

    def move(self, k, d):
        if 0 <= k + d < len(self.rows):
            self.rows[k], self.rows[k + d] = self.rows[k + d], self.rows[k]
            self.render_rows()

    def remove(self, k):
        del self.rows[k]
        self.render_rows()

    def parse_text(self):
        cmds = [l.strip() for l in (self.text.value or "").split("\n") if l.strip()]
        if cmds != self.cmds():
            self.rows = [list(parse(c)) for c in cmds]
            self.render_rows()

    # ---- run ----
    async def preview(self):
        self.parse_text()
        try:
            fl, n = self.candidate()
        except core.FlowError as e:
            self.page.notify(str(e), type="negative")
            return
        self.run_btn.disable()
        self.spinner.set_visibility(True)
        self.log.clear()
        try:
            res = await self.page.engine_run(fl, [n.id], log=lambda i, line: self.log.push(line) if i == n.id else None)
        finally:
            self.run_btn.enable()
            self.spinner.set_visibility(False)
        r = res.get(n.id, {"ok": True})
        if not r["ok"]:
            self.log.push("ERROR: %s" % r["error"])
            self.page.notify("the plot failed: %s" % r["error"], type="negative", multi_line=True)
            return
        key = core.engine(fl, self.page.en.work).keys()[n.id]
        self.result = n
        self.page.show_figure(n, key, preview=self)

    def controls(self):
        n = self.result
        lab = ("Save change to %s" % n.id) if self.edit else ("Add %s to the flow" % n.id)
        ui.button(lab, icon="check", on_click=self.commit).props("color=positive")
        ui.button("Discard", icon="close", on_click=self.discard).props("flat")

    async def commit(self):
        n = self.result
        try:
            if self.edit:
                self.page.fl.replace(n)
            else:
                self.page.fl.add(n)
            self.page.save()
        except (core.FlowError, OSError) as e:
            self.page.notify(str(e), type="negative")
            return
        self.result = None
        edited = self.edit is not None
        self.edit = None
        await self.page.after_change(n.id, edited)
        if n.plot["out"] != "-":
            await self.page.run_nodes([n.id])  # the stored figure to its file

    def discard(self):
        self.result = None
        self.page.show_node()
