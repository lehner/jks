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
# Database browser: tag list with fnmatch filter, plots, error table,
# correlations and per-configuration outlier view of one database.
# Built as a component on a `database` so it can serve as a node inspector.
#
import numpy as np
import plotly.graph_objects as go
from nicegui import ui
import jks
from jks.gui import stats

QUANTITIES = {
    "value": "value",
    "abs": "|value| (log scale)",
    "meff": "effective mass log(c(t)/c(t+1))",
    "relerr": "relative error",
    "budget": "error budget (active tag)",
}
CONVENTIONS = {"info": "bias-free (jks_info)", "cov": "cov() convention (fits)"}
CORRELATIONS = ["total", "stat", "sys"]
# validated categorical slots (light, dark); more tags than slots reuse them
SERIES = [("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70"),
          ("#eda100", "#c98500"), ("#e87ba4", "#d55181"), ("#008300", "#008300"),
          ("#4a3aa7", "#9085e9"), ("#e34948", "#e66767")]


def _fmt(x):
    return "" if not np.isfinite(x) else "%.10g" % x


def _figure(fig):
    # no lasso/box select: a selection has no meaning (yet)
    d = fig.to_plotly_json()
    d["config"] = {"modeBarButtonsToRemove": ["select2d", "lasso2d"], "displaylogo": False}
    return d


def _rgba(c, a):
    return "rgba(%d,%d,%d,%.3f)" % (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16), a)


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _nz(y):
    # zeros and non-finite values become gaps on log axes
    y = np.array(y, dtype=np.float64)
    y[~(np.isfinite(y) & (y > 0))] = np.nan
    return y


def _human(m, errs, etags):
    # jks_info style value(err)(err), falls back to plain numbers
    try:
        return jks.gformat(m, errs, etags, times="x")
    except (ValueError, OverflowError):
        return "%.6g" % m


class database_view:
    def __init__(self, db, dark, diff=None, ref=None, fit_source=None, inputs=(), fit=None, on_delete=None,
                 height="calc(100vh - 5rem)", scan=None):
        # scan: {"var": name, "values": [...], "series": {template: [tag per value]}} of a loop node
        # diff, ref: preview of a step, compared with the database ref
        # inputs: tags the step read; fit: fit tag the step wrote (shown in the fit overlay)
        # fit_source: fit tag -> step that wrote it (functions of the fit), or None
        self.db = db
        self.fit_source = fit_source
        self.on_delete = on_delete  # async callback(tags) removing tags from the database
        self.height = height
        self.scan = scan
        self.dark = dark
        self.diff, self.ref = diff, ref
        self.change = {}
        if diff is not None:
            self.change.update((t, "new") for t in diff["added"])
            self.change.update((t, "modified") for t in diff["modified"])
            self.change.update((t, "input") for t in inputs if t in db.res.set and t not in self.change)
        self.new_fit = fit if fit in db.res.set else None
        self.selected = []
        self.active = None
        self.convention = "cov"  # as jks_plot2 and fits
        self.quantity = "value"
        self.slots = {}
        self.tab = "Plot"
        self.build()

    # ---- layout ----
    def build(self):
        db = self.db
        with ui.splitter(value=28, limits=(15, 60)).classes("w-full").style("height: %s" % self.height) as sp:
            with sp.before, ui.column().classes("w-full h-full no-wrap gap-1 pr-2"):
                self.build_overview()
                with ui.row().classes("w-full items-center no-wrap gap-1"):
                    self.filter = ui.input(placeholder="filter tags (fnmatch, e.g. C.*.b)").props("dense clearable").classes("grow")
                    self.filter.on_value_change(self.apply_filter)
                self.var_filter = ui.select(
                    ["(any)"] + db.variations, value="(any)", label="shifted by variation"
                ).props("dense").classes("w-full")
                self.var_filter.on_value_change(self.apply_filter)
                self.only_changes = ui.checkbox("changed and input tags only", value=bool(self.change),
                                                on_change=self.apply_filter).props("dense")
                self.only_changes.set_visibility(self.diff is not None)
                with ui.row().classes("w-full items-center no-wrap"):
                    self.count = ui.label().classes("text-xs opacity-70 grow")
                    self.delete_btn = ui.button("delete selected", icon="delete", on_click=self.confirm_delete) \
                        .props("flat dense size=sm color=negative")
                    self.delete_btn.set_visibility(False)
                self.table = ui.table(
                    columns=[
                        {"name": "tag", "label": "tag", "field": "tag", "align": "left", "sortable": True},
                        {"name": "change", "label": "step", "field": "change", "align": "left", "sortable": True},
                        {"name": "shape", "label": "shape", "field": "shape", "align": "right"},
                        {"name": "vars", "label": "variations", "field": "vars", "align": "left"},
                        {"name": "relerr", "label": "max rel.err", "field": "relerr", "align": "right", "sortable": True},
                    ],
                    rows=[],
                    row_key="tag",
                    selection="multiple",
                    pagination={"rowsPerPage": 0},
                    on_select=self.on_select,
                ).props("dense flat virtual-scroll").classes("w-full grow")
                if self.diff is None:
                    self.table.columns = [c for c in self.table.columns if c["name"] != "change"]
                self.table.on("rowClick", lambda e: self.click_row(e.args[1]))
            with sp.after, ui.column().classes("w-full h-full no-wrap pl-2 overflow-auto"):
                with ui.row().classes("w-full items-center gap-2"):
                    self.active_sel = ui.select([], label="active tag").props("dense").classes("w-56")
                    self.active_sel.on_value_change(self.on_active)
                    ui.select(CONVENTIONS, value=self.convention, label="error convention",
                              on_change=lambda e: self.set_convention(e.value)).props("dense").classes("w-56")
                with ui.tabs().classes("w-full") as tabs:
                    t_plot = ui.tab("Plot")
                    t_table = ui.tab("Table")
                    t_cor = ui.tab("Correlation")
                    t_out = ui.tab("Configurations")
                    t_info = ui.tab("Info")
                    t_scan = ui.tab("Scan") if self.scan else None
                with ui.tab_panels(tabs, value=t_plot, keep_alive=False).classes("w-full grow"):
                    with ui.tab_panel(t_plot):
                        with ui.row().classes("items-center gap-4"):
                            ui.select(QUANTITIES, value=self.quantity, label="show",
                                      on_change=lambda e: self.set_quantity(e.value)).props("dense").classes("w-72")
                            self.dodge = ui.checkbox("offset tags in x", value=False, on_change=self.update_plot)
                            ui.label("error bars as jks_plot2: inner statistical, outer stat and sys in quadrature"
                                     ).classes("text-xs opacity-70")
                        self.build_fit_overlay()
                        self.plot = ui.plotly(go.Figure()).classes("w-full").style("height: calc(%s - 14rem)" % self.height)
                    with ui.tab_panel(t_table):
                        self.values = ui.table(columns=[], rows=[], row_key="t", pagination={"rowsPerPage": 0}) \
                            .props("dense flat virtual-scroll").classes("w-full").style("height: calc(%s - 10rem)" % self.height)
                    with ui.tab_panel(t_cor):
                        self.cor_which = ui.select(CORRELATIONS, value="total", label="covariance",
                                                   on_change=self.update_cor).props("dense").classes("w-56")
                        self.cor = ui.plotly(go.Figure()).classes("w-full").style("height: calc(%s - 14rem)" % self.height)
                    with ui.tab_panel(t_out):
                        ui.label("z-score of each configuration's pseudo-value, "
                                 "z = (N-1)(<b> - b_i) / s with s the single-configuration standard deviation"
                                 ).classes("text-xs opacity-70")
                        self.outliers = ui.plotly(go.Figure()).classes("w-full").style("height: calc(%s - 14rem)" % self.height)
                    with ui.tab_panel(t_info):
                        self.info = ui.column().classes("w-full")
                    if t_scan is not None:
                        with ui.tab_panel(t_scan):
                            self.build_scan()
                tabs.on_value_change(self.on_tab)
        self.apply_filter()
        if self.new_fit is not None:
            # a fit: its data (all indices) with the fit band
            self.fit_exp.open()
            self.fit_sel.value = self.new_fit
        elif self.change:
            # show what the step wrote
            first = [t for t in self.db.keys() if self.change.get(t) in ("new", "modified")][: len(SERIES)]
            self.table.selected = [r for r in self.table.rows if r["tag"] in first]
            self.set_selected(first)
        else:
            self.update_all()

    def build_fit_overlay(self):
        fits = stats.fit_tags(self.db.keys())
        with ui.expansion("fit overlay", icon="show_chart").classes("w-full").props("dense") as exp:
            self.fit_exp = exp
            with ui.row().classes("w-full items-center gap-2"):
                self.fit_sel = ui.select(["(none)"] + fits, value="(none)", label="fit",
                                         on_change=self.on_fit).props("dense").classes("w-40")
                self.fit_tag = ui.select([], label="data tag", on_change=self.on_fit_tag).props("dense").classes("w-40")
                self.fit_range = ui.select({}, label="range", on_change=self.update_plot).props("dense").classes("w-40")
                self.fit_method = ui.select({"jackknife": "jackknife per block", "linear": "linear (jks_plot2)"},
                                            value="jackknife", label="band",
                                            on_change=self.update_plot).props("dense").classes("w-48")
                self.fit_nested = ui.checkbox("stat band inside total band", value=True, on_change=self.update_plot)
            with ui.row().classes("w-full items-center gap-2"):
                # limits of the band, blank: whole plot (an extrapolation may be singular)
                self.fit_lo = ui.number("band from", on_change=self.update_plot).props("dense clearable").classes("w-32")
                self.fit_hi = ui.number("band to", on_change=self.update_plot).props("dense clearable").classes("w-32")
                ui.button("fit range only", on_click=self.band_fit_range).props("flat dense size=sm")
                ui.button("whole plot", on_click=self.band_clear).props("flat dense size=sm")
            self.fit_src = ui.input("fit function of x, p, r (Enter to apply)").props("dense").classes("w-full") \
                .style("font-family: ui-monospace, monospace")
            self.fit_src.on("keydown.enter", self.update_plot)
            self.fit_src.on("blur", self.update_plot)
            self.fit_info = ui.label().classes("text-xs whitespace-pre-wrap")
        exp.set_visibility(bool(fits))

    def on_fit(self, e=None):
        fit = self.fit_sel.value
        if fit == "(none)":
            self.fit_tag.options, self.fit_tag.value = [], None
            self.fit_tag.update()
            self.update_plot()
            return
        tags = list(stats.fit_inputs(self.db.keys(), fit))
        self.fit_tag.options = tags
        self.fit_tag.value = tags[0] if self.fit_tag.value not in tags else self.fit_tag.value
        self.fit_tag.update()
        self.on_fit_tag()

    def on_fit_tag(self, e=None):
        fit, tag = self.fit_sel.value, self.fit_tag.value
        if fit == "(none)" or tag is None:
            return
        js = stats.fit_inputs(self.db.keys(), fit)[tag]
        opts = {}
        for j in js:
            x = np.flatnonzero(np.isfinite(np.asarray(self.db.res.get("%s.%s.input.%d" % (fit, tag, j)).orig, dtype=np.float64)))
            opts[j] = "%d: t = %d..%d" % (j, x.min(), x.max()) if len(x) else str(j)
        self.fit_range.options = opts
        self.fit_range.value = js[0] if self.fit_range.value not in js else self.fit_range.value
        self.fit_range.update()
        src = self.fit_source(fit) if self.fit_source else None
        self.fit_origin = (src["command"], src["functions"][tag]) if src and tag in src["functions"] else None
        if src and tag in src["functions"]:
            self.fit_src.value = src["functions"][tag]
        if tag not in self.selected:
            self.table.selected = [r for r in self.table.rows if r["tag"] in self.selected + [tag]]
            self.set_selected(self.selected + [tag])
        else:
            self.update_plot()

    def fit_window(self, fit, tag, j, meff):
        # fitted x range from the .input tag; m_eff(t) needs t and t+1
        x = np.flatnonzero(np.isfinite(np.asarray(self.db.res.get("%s.%s.input.%d" % (fit, tag, j)).orig, dtype=np.float64)))
        return (int(x.min()), int(x.max()) - (1 if meff else 0)) if len(x) else None

    def band_fit_range(self):
        fit, tag, j = self.fit_sel.value, self.fit_tag.value, self.fit_range.value
        if fit == "(none)" or tag is None or j is None:
            return
        w = self.fit_window(fit, tag, j, self.quantity == "meff")
        if w is not None:
            self.fit_lo.value, self.fit_hi.value = w

    def band_clear(self):
        self.fit_lo.value = self.fit_hi.value = None

    def plot_fit(self, fig):
        fit, tag, j = self.fit_sel.value, self.fit_tag.value, self.fit_range.value
        src = (self.fit_src.value or "").strip()
        if fit == "(none)" or tag is None or j is None:
            self.fit_info.text = ""
            return
        if not src:
            self.fit_info.text = "type the fit function (the step that wrote %s is not known)" % fit
            return
        js = stats.fit_inputs(self.db.keys(), fit)[tag]
        meff = self.quantity == "meff"
        n = len(np.atleast_1d(self.db.res.get(tag).orig)) - (1 if meff else 0)
        w = self.fit_window(fit, tag, j, meff)
        x0, x1 = w if w is not None else (0, n - 1)
        lo = 0.0 if self.fit_lo.value is None else float(self.fit_lo.value)
        hi = n - 1.0 if self.fit_hi.value is None else float(self.fit_hi.value)
        if not lo < hi:
            self.fit_info.text = "band range is empty (from %g to %g)" % (lo, hi)
            return
        # about ten points per unit, with the edges of the fit range on the grid
        xs = np.linspace(lo, hi, int(min(600, 10 * (hi - lo) + 1)))
        xs = np.unique(np.concatenate([xs, [x for x in (x0, x1) if lo <= x <= hi]]))
        try:
            y, st, tot = stats.fit_band(self.db.res, fit, src, len(js), j, xs, self.convention,
                                        self.fit_method.value, meff=meff)
            P, pval = stats.fit_parameters(self.db.res, fit, len(js), j)
        except Exception as e:
            self.fit_info.text = "ERROR: %s" % e
            return
        if self.quantity == "abs":
            y = np.abs(y)
        c = self.color(tag)
        segments = [((xs >= x0) & (xs <= x1), 1.0, "solid"), (xs <= x0, 0.4, "dash"), (xs >= x1, 0.4, "dash")]
        name = "fit %s, range %s" % (fit, self.fit_range.options.get(j, j))
        for mask, a, dash in segments:
            if mask.sum() < 2:
                continue
            bands = [(tot, 0.18), (st, 0.35)] if self.fit_nested.value else [(tot, 0.25)]
            for e, alpha in bands:
                fig.add_trace(go.Scatter(
                    x=np.concatenate([xs[mask], xs[mask][::-1]]), y=np.concatenate([(y + e)[mask], (y - e)[mask][::-1]]),
                    fill="toself", fillcolor=_rgba(c, alpha * a), line=dict(width=0), hoverinfo="skip",
                    showlegend=False, legendgroup=name))
            fig.add_trace(go.Scatter(
                x=xs[mask], y=y[mask], mode="lines", line=dict(width=2, color=c, dash=dash), opacity=a if a < 1 else 1,
                name=name, legendgroup=name, showlegend=dash == "solid",
                customdata=np.stack([st[mask], tot[mask]], 1),
                hovertemplate="x=%{x:.2f}: %{y:.8g}<br>stat %{customdata[0]:.3g}<br>total %{customdata[1]:.3g}<extra>fit</extra>"))
        npar = P.shape[1] - (4 if pval else 0)
        ps = stats.tag_stats(P[0, :npar], P[1:, :npar], self.db.tags, self.convention)
        pe = ps.tot_err()
        lines = ["p = [%s]" % ", ".join(_human(m, {"": e}, [""]) for m, e in zip(ps.mean, pe))]
        if pval:
            lines.append("chi2/dof = %.4g/%d, p-value %.3g" % (P[0, -3], int(P[0, -2]), P[0, -4]))
        origin = getattr(self, "fit_origin", None)
        if origin is None:
            lines.append("function entered here (the step that wrote %s is not known)" % fit)
        elif origin[1] == src:
            lines.append("function from: %s" % origin[0])
        else:
            lines.append("function edited here; fitted with %s" % origin[1])
        self.fit_info.text = "\n".join(lines)

    def build_overview(self):
        db = self.db
        with ui.expansion("Database", icon="storage").classes("w-full").props("dense"):
            ui.label(db.path).classes("text-xs break-all")
            ui.label("%d tags, %d configurations, %d variations, loaded in %.2fs" % (
                len(db.keys()), len(db.configs), len(db.variations), db.load_time)).classes("text-xs")
            with ui.expansion("Configurations").classes("w-full").props("dense"):
                ui.label(", ".join(db.configs)).classes("text-xs break-all")
            if db.variations:
                with ui.expansion("Variations").classes("w-full").props("dense"):
                    for v in db.variations:
                        ui.label("!" + v).classes("text-sm font-bold")
                        ui.label(db.info.get(v, "(no description)")).classes("text-xs whitespace-pre-wrap")
            if db.origin:
                with ui.expansion("Origin (last write)").classes("w-full").props("dense"):
                    for k, v in db.origin.items():
                        ui.label("%s: %s" % (k, v)).classes("text-xs break-all")

    # ---- tag list ----
    def apply_filter(self):
        keys = set(stats.match(self.db.keys(), self.filter.value or ""))
        v = self.var_filter.value
        only = self.diff is not None and self.only_changes.value
        rows = [dict(r, change=self.change.get(r["tag"], "")) for r in self.db.rows() if r["tag"] in keys
                and (v == "(any)" or v in r["vars"].split(", ")) and (not only or r["tag"] in self.change)]
        self.table.rows = rows
        self.count.text = "%d of %d tags" % (len(rows), len(self.db.keys()))

    def click_row(self, row):
        self.table.selected = [row]
        self.set_selected([row["tag"]])

    def on_select(self, e):
        self.set_selected([r["tag"] for r in self.table.selected])

    def set_selected(self, tags):
        self.selected = tags
        self.delete_btn.set_visibility(self.on_delete is not None and bool(tags))
        self.active_sel.options = tags
        if self.active not in tags:
            self.active = tags[-1] if tags else None
        self.active_sel.value = self.active
        self.active_sel.update()
        self.update_all()

    def confirm_delete(self):
        tags = list(self.selected)
        if not tags or self.on_delete is None:
            return
        with ui.dialog() as dlg, ui.card().classes("w-[36rem] max-w-full"):
            ui.label("Delete %d tag%s from %s?" % (len(tags), "" if len(tags) == 1 else "s",
                                                   self.db.path)).classes("text-lg font-bold break-all")
            shown = ", ".join(tags[:40]) + (" and %d more" % (len(tags) - 40) if len(tags) > 40 else "")
            ui.label(shown).classes("text-sm break-all").style("font-family: ui-monospace, monospace")
            ui.label("This runs jks_rm on the database. The previous version is kept in the backup "
                     "folder of the work directory.").classes("text-xs opacity-70")
            sure = ui.checkbox("I understand, delete these tags")
            with ui.row():
                async def go():
                    dlg.close()
                    await self.on_delete(tags)
                ui.button("Delete", icon="delete", on_click=go).props("color=negative").bind_enabled_from(sure, "value")
                ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()

    def on_active(self, e):
        if e.value and e.value != self.active:
            self.active = e.value
            self.update_all()

    def set_convention(self, c):
        self.convention = c
        self.update_all()

    def set_quantity(self, q):
        self.quantity = q
        self.update_plot()

    def refresh_theme(self):
        self.update_all()

    # ---- views ----
    def layout(self, **kw):
        tpl = "plotly_dark" if self.dark.value else "plotly_white"
        d = dict(template=tpl, margin=dict(l=60, r=20, t=60, b=50),
                 legend=dict(orientation="h", x=1, xanchor="right", y=1.02, yanchor="bottom"),
                 title=dict(x=0, xanchor="left", y=0.98, yanchor="top"), hovermode="closest")
        if self.dark.value:
            d.update(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        if isinstance(kw.get("title"), str):
            kw["title"] = dict(d["title"], text=kw["title"])
        d.update(kw)
        return d

    def stats_for(self, tag, db=None):
        db = db or self.db
        s = db.stats(tag, self.convention)
        if self.quantity == "meff":
            jk = db.res.get(tag)
            m, B = stats.derived(jk.orig, jk.blocks, stats.effective_mass_log)
            s = stats.tag_stats(m, B, db.tags, self.convention)
        return s

    def on_tab(self, e):
        self.tab = e.value
        self.update_all()

    def update_all(self):
        # only the visible tab is drawn; switching tabs redraws
        {"Plot": self.update_plot, "Table": self.update_table, "Correlation": self.update_cor,
         "Configurations": self.update_outliers, "Info": self.update_info, "Scan": self.update_scan}[self.tab]()

    def color(self, tag):
        # a tag keeps its color while selected, independent of selection order
        for t in list(self.slots):
            if t not in self.selected:
                del self.slots[t]
        if tag not in self.slots:
            used = set(self.slots.values())
            free = [i for i in range(len(SERIES)) if i not in used]
            self.slots[tag] = free[0] if free else len(self.slots) % len(SERIES)
        return SERIES[self.slots[tag]][1 if self.dark.value else 0]

    def slot(self, i):
        return SERIES[i % len(SERIES)][1 if self.dark.value else 0]

    def update_plot(self):
        fig = go.Figure()
        if self.quantity == "budget":
            self.plot_budget(fig)
        else:
            n = len(self.selected)
            for k, tag in enumerate(self.selected):
                try:
                    s = self.stats_for(tag)
                except Exception as e:
                    ui.notify("%s: %s" % (tag, e), type="warning")
                    continue
                x = np.arange(len(s.mean)) + (0.3 * k / max(n - 1, 1) - 0.15 if n > 1 and self.dodge.value else 0.0)
                y, tot, st = s.mean, s.tot_err(), s.stat_err()
                if self.quantity == "abs":
                    y = _nz(np.abs(y))
                if self.quantity == "relerr":
                    with np.errstate(divide="ignore", invalid="ignore"):
                        y = _nz(tot / np.abs(s.mean))
                    fig.add_trace(go.Scatter(x=x, y=y, mode="lines+markers", name=tag,
                                             line=dict(width=2, color=self.color(tag)), marker=dict(size=8)))
                    continue
                # jks_plot2 convention: outer bar total, inner thin bar statistical, both capped
                c = self.color(tag)
                fig.add_trace(go.Scatter(
                    x=x, y=y, mode="markers", name=tag, legendgroup=tag, marker=dict(size=8, color=c),
                    error_y=dict(type="data", array=tot, visible=True, thickness=1.5, width=5, color=c),
                    customdata=np.stack([st, s.sys_err(), tot], 1),
                    hovertemplate="%{x:.0f}: %{y:.8g}<br>stat %{customdata[0]:.3g}<br>sys %{customdata[1]:.3g}"
                                  "<br>total %{customdata[2]:.3g}<extra>" + tag + "</extra>"))
                fig.add_trace(go.Scatter(
                    x=x, y=y, mode="markers", legendgroup=tag, showlegend=False, hoverinfo="skip",
                    marker=dict(size=1, opacity=0, color=c),
                    error_y=dict(type="data", array=st, visible=True, thickness=0.75, width=5, color=c)))
                if self.change.get(tag) == "modified" and self.ref is not None:
                    self.plot_before(fig, tag, x, c)
            if self.quantity in ("value", "abs", "meff"):
                self.plot_fit(fig)
            if not self.selected:
                fig.update_layout(**self.layout(
                    xaxis=dict(visible=False), yaxis=dict(visible=False),
                    annotations=[dict(text="select tags on the left", showarrow=False, font=dict(size=16),
                                      xref="paper", yref="paper", x=0.5, y=0.5)]))
                self.plot.update_figure(_figure(fig))
                return
            ylog = self.quantity in ("abs", "relerr")
            ytitle = {"value": "value", "abs": "|value|", "meff": "m_eff", "relerr": "total error / |value|"}[self.quantity]
            fig.update_layout(**self.layout(xaxis_title="index", yaxis_title=ytitle,
                                            yaxis_type="log" if ylog else "linear"))
        self.plot.update_figure(_figure(fig))

    def plot_before(self, fig, tag, x, c):
        # the tag as it was before the step, open markers
        s = self.stats_for(tag, self.ref)
        y, tot, st = s.mean, s.tot_err(), s.stat_err()
        if self.quantity == "abs":
            y = _nz(np.abs(y))
        name = tag + " (before)"
        fig.add_trace(go.Scatter(
            x=x[: len(y)], y=y, mode="markers", name=name, legendgroup=name, opacity=0.6,
            marker=dict(size=9, color=c, symbol="circle-open"),
            error_y=dict(type="data", array=tot, visible=True, thickness=1, width=5, color=c)))
        fig.add_trace(go.Scatter(
            x=x[: len(y)], y=y, mode="markers", legendgroup=name, showlegend=False, hoverinfo="skip",
            opacity=0.6, marker=dict(size=1, opacity=0, color=c),
            error_y=dict(type="data", array=st, visible=True, thickness=0.75, width=5, color=c)))

    def plot_budget(self, fig):
        if self.active is None:
            fig.update_layout(**self.layout())
            return
        s = self.db.stats(self.active, self.convention)
        a = np.abs(s.mean)
        with np.errstate(divide="ignore", invalid="ignore"):
            fig.add_trace(go.Scatter(y=_nz(s.stat_err() / a), mode="lines+markers", name="stat",
                                     line=dict(width=2, color=self.slot(0)), marker=dict(size=8)))
            # largest variations individually, the rest in quadrature, so colors never repeat
            vs = sorted(s.vars(), key=lambda v: -np.max(s.var_err(v)))
            shown, rest = vs[: len(SERIES) - 2], vs[len(SERIES) - 2 :]
            if len(rest) == 1:
                shown, rest = vs, []
            for i, v in enumerate(shown):
                fig.add_trace(go.Scatter(y=_nz(s.var_err(v) / a), mode="lines+markers", name="!" + v,
                                         line=dict(width=2, color=self.slot(i + 1)), marker=dict(size=8)))
            if rest:
                e = np.sqrt(sum(s.var_err(v) ** 2 for v in rest))
                fig.add_trace(go.Scatter(y=_nz(e / a), mode="lines+markers", name="%d other variations" % len(rest),
                                         line=dict(width=2, color=self.slot(len(SERIES) - 1)), marker=dict(size=8)))
            fig.add_trace(go.Scatter(y=_nz(s.tot_err() / a), mode="lines", name="total",
                                     line=dict(width=2, dash="dot", color="#c3c2b7" if self.dark.value else "#52514e")))
        fig.update_layout(**self.layout(xaxis_title="index", yaxis_title="error / |value|",
                                        yaxis_type="log", title=self.active))

    def update_table(self):
        if self.active is None:
            self.values.columns, self.values.rows = [], []
            return
        s = self.db.stats(self.active, self.convention)
        vs = s.vars()
        cols = ["t", "value", "stat"] + ["!" + v for v in vs] + ["sys", "total", "formatted"]
        st, sy, tot = s.stat_err(), s.sys_err(), s.tot_err()
        rows = []
        for i in range(len(s.mean)):
            r = {"t": i, "value": _fmt(s.mean[i]), "stat": _fmt(st[i]), "sys": _fmt(sy[i]), "total": _fmt(tot[i])}
            for v in vs:
                r["!" + v] = _fmt(s.var_err(v)[i])
            r["formatted"] = _human(s.mean[i], {"stat": st[i], "sys": sy[i]}, ["stat", "sys"])
            rows.append(r)
        self.values.columns = [{"name": c, "label": c, "field": c, "align": "right" if c != "formatted" else "left"}
                               for c in cols]
        self.values.rows = rows

    def update_cor(self):
        fig = go.Figure()
        if self.active is not None:
            s = self.db.stats(self.active, self.convention)
            opts = CORRELATIONS + s.vars()
            if self.cor_which.options != opts:
                self.cor_which.options = opts
                if self.cor_which.value not in opts:
                    self.cor_which.value = "total"
                self.cor_which.update()
            r = s.cor(self.cor_which.value)
            fig.add_trace(go.Heatmap(z=r, zmin=-1, zmax=1, colorscale="RdBu_r",
                                     hovertemplate="(%{y}, %{x}): %{z:.3f}<extra></extra>"))
            fig.update_layout(**self.layout(title="%s, %s correlation" % (self.active, self.cor_which.value),
                                            xaxis=dict(constrain="domain"),
                                            yaxis=dict(autorange="reversed", scaleanchor="x", constrain="domain"),
                                            xaxis_title="index", yaxis_title="index"))
        else:
            fig.update_layout(**self.layout())
        self.cor.update_figure(_figure(fig))

    def update_outliers(self):
        fig = go.Figure()
        s = self.db.stats(self.active, "cov") if self.active is not None else None
        if s is not None and s.n_stat > 1:
            # D = b - <b> over stat blocks; sum D^2 = s^2/(N-1) for primary observables
            n = s.n_stat
            sd = np.sqrt((n - 1) * np.sum(s.D**2, axis=0))
            with np.errstate(divide="ignore", invalid="ignore"):
                z = -(n - 1) * s.D / sd
            z[~np.isfinite(z)] = np.nan
            fig.add_trace(go.Heatmap(z=z, y=self.db.configs, colorscale="RdBu_r", zmid=0,
                                     zmin=-4, zmax=4, colorbar=dict(title="z"),
                                     hovertemplate="%{y}, t=%{x}: z=%{z:.2f}<extra></extra>"))
            fig.update_layout(**self.layout(title="%s, max |z| = %.2f" % (self.active, np.nanmax(np.abs(z)) if np.any(np.isfinite(z)) else 0.0),
                                            xaxis_title="index", yaxis=dict(autorange="reversed")))
        else:
            fig.update_layout(**self.layout())
        self.outliers.update_figure(_figure(fig))

    # ---- scan of a loop: every iteration's output against the loop value ----
    def build_scan(self):
        sc = self.scan
        first = next((t for ts in sc["series"].values() for t in ts if t in self.db.res.set), None)
        n = len(np.atleast_1d(self.db.res.get(first).orig)) if first else 1
        with ui.row().classes("items-center gap-4"):
            self.scan_series = ui.select(list(sc["series"]), value=list(sc["series"])[0], label="output",
                                         on_change=self.update_scan).props("dense").classes("w-64")
            self.scan_index = ui.number("element", value=0, min=0, max=max(n - 1, 0), step=1,
                                        on_change=self.update_scan).props("dense").classes("w-28")
            numeric = all(_float(v) is not None for v in sc["values"])
            self.scan_log = ui.checkbox("log x", value=numeric and all(_float(v) > 0 for v in sc["values"]) and
                                        max(_float(v) for v in sc["values"]) / max(min(_float(v) for v in sc["values"]), 1e-300) > 50,
                                        on_change=self.update_scan)
            self.scan_log.set_visibility(numeric)
            ui.label("x: $%s; error bars as jks_plot2" % sc["var"]).classes("text-xs opacity-70")
        self.scan_box = ui.column().classes("w-full")
        self.scan_plot = None  # created when the tab is first shown

    def update_scan(self, e=None):
        sc = self.scan
        if self.scan_plot is None:
            # first shown: create the plot once the tab panel is displayed (not during the switch)
            def create():
                with self.scan_box:
                    self.scan_plot = ui.plotly(go.Figure()).classes("w-full").style("height: calc(%s - 14rem)" % self.height)
                self.update_scan()
            ui.timer(0.3, create, once=True)
            return
        tags = sc["series"][self.scan_series.value]
        k = int(self.scan_index.value or 0)
        numeric = all(_float(v) is not None for v in sc["values"])
        xs, ys, st, tot, names = [], [], [], [], []
        for v, t in zip(sc["values"], tags):
            if t not in self.db.res.set:
                continue
            s = self.db.stats(t, self.convention)
            if k >= len(s.mean):
                continue
            xs.append(_float(v) if numeric else v)
            ys.append(s.mean[k]); st.append(s.stat_err()[k]); tot.append(s.tot_err()[k]); names.append(t)
        c = SERIES[0][1 if self.dark.value else 0]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", name=self.scan_series.value,
                                 marker=dict(size=8, color=c), text=names,
                                 error_y=dict(type="data", array=tot, visible=True, thickness=1.5, width=5, color=c),
                                 hovertemplate="%{text}: %{y:.8g}<extra></extra>"))
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", showlegend=False, hoverinfo="skip",
                                 marker=dict(size=1, opacity=0, color=c),
                                 error_y=dict(type="data", array=st, visible=True, thickness=0.75, width=5, color=c)))
        fig.update_layout(**self.layout(xaxis_title="$" + sc["var"], yaxis_title="%s [%d]" % (self.scan_series.value, k),
                                        xaxis_type="log" if (numeric and self.scan_log.value) else
                                        ("linear" if numeric else "category")))
        self.scan_plot.update_figure(_figure(fig))

    def update_info(self):
        self.info.clear()
        if self.active is None:
            return
        s = self.db.stats(self.active, self.convention)
        with self.info:
            ui.label(self.active).classes("text-lg font-bold")
            ui.label("shape %s, %d elements, %d statistical blocks" % (s.shape, len(s.mean), s.n_stat))
            vs = s.vars()
            if not vs:
                ui.label("not shifted by any variation")
            for v in vs:
                ui.label("!%s  (max shift %.3g)" % (v, np.max(s.var_err(v)))).classes("font-bold mt-2")
                ui.label(self.db.info.get(v, "(no description)")).classes("text-sm whitespace-pre-wrap")
