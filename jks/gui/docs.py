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
# The documentation of the scripts (jks/doc/<script>.md) in dialogs.
#
import glob, os, re
from nicegui import ui
import jks

DOC = os.path.join(os.path.dirname(os.path.abspath(jks.__file__)), "doc")


def names():
    return sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(DOC, "*.md")) if not p.endswith("index.md"))


def text(name):
    try:
        with open(os.path.join(DOC, name + ".md")) as f:
            return f.read()
    except OSError:
        return None


def summary(name):
    # the sentence after the title
    t = text(name) or ""
    for line in t.split("\n")[1:]:
        if line.strip():
            return line.strip().replace("`", "")
    return ""


def see_also(t):
    m = re.search(r"^## See also\s*\n(.*?)(^## |\Z)", t, re.S | re.M)
    return [n for n in re.findall(r"`(jks_[A-Za-z0-9_]+|dump-corrs|list-corrs)`", m.group(1)) if text(n)] if m else []


CSS = (".jks-doc h1 {font-size: 1.6rem; margin: 0.2rem 0} .jks-doc h2 {font-size: 1.15rem; margin: 0.9rem 0 0.3rem} "
       ".jks-doc pre {background: rgba(127,127,127,0.12); padding: 0.4rem 0.6rem; border-radius: 4px} "
       ".jks-doc table {font-size: 0.85rem}")


def show(name):
    # a page in a dialog; "See also" entries open their pages
    ui.add_css(CSS)
    with ui.dialog() as dlg, ui.card().classes("w-[64rem] max-w-full"):
        body = ui.column().classes("w-full max-h-[75vh] overflow-auto")

        def page(n):
            body.clear()
            t = text(n)
            with body:
                if t is None:
                    ui.label("%s has no documentation page yet." % n).classes("m-4")
                    return
                ui.markdown(t).classes("w-full jks-doc")
                links = see_also(t)
                if links:
                    with ui.row().classes("gap-1"):
                        for l in links:
                            ui.button(l, on_click=lambda l=l: page(l)).props("flat dense no-caps size=sm")
        page(name)
        with ui.row().classes("w-full"):
            ui.button("all scripts", icon="list", on_click=lambda: (dlg.close(), index())).props("flat dense")
            ui.space()
            ui.button("Close", on_click=dlg.close).props("flat")
    dlg.open()


def index():
    with ui.dialog() as dlg, ui.card().classes("w-[56rem] max-w-full"):
        ui.label("jks scripts").classes("text-lg font-bold")
        rows = [{"name": n, "summary": summary(n)} for n in names()]
        t = ui.table(columns=[{"name": "name", "label": "script", "field": "name", "align": "left", "sortable": True},
                              {"name": "summary", "label": "", "field": "summary", "align": "left"}],
                     rows=rows, row_key="name", pagination={"rowsPerPage": 0}) \
            .props("dense flat virtual-scroll").classes("w-full max-h-[65vh]")
        t.on("rowClick", lambda e: (dlg.close(), show(e.args[1]["name"])))
        ui.button("Close", on_click=dlg.close).props("flat")
    dlg.open()
