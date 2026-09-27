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
# File picker for the filesystem of the host running jks_gui (not the browser's).
#
import os
from nicegui import ui
from jks.flow import core


def _kind(e):
    # what the picker says a file is
    if e.name.endswith(".jks"):
        return "database"
    try:
        with open(e.path, "rb") as f:
            return "flow" if core.FORMAT.encode() in f.read(200) else ""
    except OSError:
        return ""


def _size(n):
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024 or u == "GB":
            return "%.0f %s" % (n, u) if u == "B" else "%.1f %s" % (n, u)
        n /= 1024.0


class file_picker(ui.dialog):
    def __init__(self, directory, pattern=".jks"):
        super().__init__()
        self.directory = os.path.abspath(os.path.expanduser(directory))
        self.pattern = pattern
        with self, ui.card().classes("w-[44rem] max-w-full"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.button(icon="arrow_upward", on_click=self._up).props("flat dense")
                ui.button(icon="home", on_click=lambda: self._go("~")).props("flat dense")
                self.path = ui.input().classes("grow").props("dense")
                self.path.on("keydown.enter", lambda: self._typed())
            self.all = ui.checkbox("show all files", on_change=self._refresh)
            self.table = ui.table(
                columns=[
                    {"name": "name", "label": "Name", "field": "name", "align": "left", "sortable": True},
                    {"name": "kind", "label": "Type", "field": "kind", "align": "left", "sortable": True},
                    {"name": "size", "label": "Size", "field": "size", "align": "right"},
                ],
                rows=[],
                row_key="path",
                pagination={"rowsPerPage": 0},
            ).props("dense flat virtual-scroll").classes("w-full h-96")
            self.table.on("rowClick", lambda e: self._click(e.args[1]))
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: self.submit(None)).props("flat")
        self._refresh()

    def _go(self, d):
        d = os.path.abspath(os.path.expanduser(d))
        if os.path.isdir(d):
            self.directory = d
            self._refresh()

    def _up(self):
        self._go(os.path.dirname(self.directory))

    def _typed(self):
        p = os.path.abspath(os.path.expanduser(self.path.value))
        if os.path.isdir(p):
            self._go(p)
        elif os.path.isfile(p):
            self.submit(p)
        else:
            ui.notify("no such file or directory: %s" % p, type="warning")

    def _click(self, row):
        if row["dir"]:
            self._go(row["path"])
        else:
            self.submit(row["path"])

    def _refresh(self):
        self.path.value = self.directory
        rows = []
        try:
            entries = sorted(os.scandir(self.directory), key=lambda e: e.name.lower())
        except OSError as e:
            ui.notify(str(e), type="negative")
            entries = []
        for e in entries:
            if e.name.startswith("."):
                continue
            try:
                is_dir = e.is_dir()
                if not is_dir and not self.all.value and not e.name.endswith(self.pattern):
                    continue
                kind = "folder" if is_dir else _kind(e)
                # shell scripts only if they are flows
                if e.name.endswith(".sh") and kind != "flow" and not self.all.value:
                    continue
                size = "" if is_dir else _size(e.stat().st_size)
            except OSError:
                continue
            rows.append(
                {"name": ("📁 " if is_dir else "") + e.name, "size": size, "path": e.path, "dir": is_dir,
                 "kind": kind}
            )
        rows.sort(key=lambda r: not r["dir"])
        self.table.rows = rows
