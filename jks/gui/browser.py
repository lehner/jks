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
    def __init__(self, db, dark, diff=None, ref=None):
        # diff, ref: preview of a step, compared with the database ref
        self.db = db
        self.dark = dark
        self.diff, self.ref = diff, ref
        self.change = {}
        if diff is not None:
            self.change.update((t, "new") for t in diff["added"])
            self.change.update((t, "modified") for t in diff["modified"])
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
        with ui.splitter(value=28, limits=(15, 60)).classes("w-full h-[calc(100vh-5rem)]") as sp:
            with sp.before, ui.column().classes("w-full h-full no-wrap gap-1 pr-2"):
                self.build_overview()
                with ui.row().classes("w-full items-center no-wrap gap-1"):
                    self.filter = ui.input(placeholder="filter tags (fnmatch, e.g. C.*.b)").props("dense clearable").classes("grow")
                    self.filter.on_value_change(self.apply_filter)
                self.var_filter = ui.select(
                    ["(any)"] + db.variations, value="(any)", label="shifted by variation"
                ).props("dense").classes("w-full")
                self.var_filter.on_value_change(self.apply_filter)
                self.only_changes = ui.checkbox("changed tags only", value=bool(self.change),
                                                on_change=self.apply_filter).props("dense")
                self.only_changes.set_visibility(self.diff is not None)
                self.count = ui.label().classes("text-xs opacity-70")
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
            with sp.after, ui.column().classes("w-full h-full no-wrap pl-2"):
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
                with ui.tab_panels(tabs, value=t_plot, keep_alive=False).classes("w-full grow"):
                    with ui.tab_panel(t_plot):
                        with ui.row().classes("items-center gap-4"):
                            ui.select(QUANTITIES, value=self.quantity, label="show",
                                      on_change=lambda e: self.set_quantity(e.value)).props("dense").classes("w-72")
                            self.dodge = ui.checkbox("offset tags in x", value=False, on_change=self.update_plot)
                            ui.label("error bars as jks_plot2: inner statistical, outer stat and sys in quadrature"
                                     ).classes("text-xs opacity-70")
                        self.plot = ui.plotly(go.Figure()).classes("w-full h-[65vh]")
                    with ui.tab_panel(t_table):
                        self.values = ui.table(columns=[], rows=[], row_key="t", pagination={"rowsPerPage": 0}) \
                            .props("dense flat virtual-scroll").classes("w-full h-[70vh]")
                    with ui.tab_panel(t_cor):
                        self.cor_which = ui.select(CORRELATIONS, value="total", label="covariance",
                                                   on_change=self.update_cor).props("dense").classes("w-56")
                        self.cor = ui.plotly(go.Figure()).classes("w-full h-[65vh]")
                    with ui.tab_panel(t_out):
                        ui.label("z-score of each configuration's pseudo-value, "
                                 "z = (N-1)(<b> - b_i) / s with s the single-configuration standard deviation"
                                 ).classes("text-xs opacity-70")
                        self.outliers = ui.plotly(go.Figure()).classes("w-full h-[65vh]")
                    with ui.tab_panel(t_info):
                        self.info = ui.column().classes("w-full")
                tabs.on_value_change(self.on_tab)
        self.apply_filter()
        if self.change:
            # show what the step wrote
            first = [t for t in self.db.keys() if t in self.change][: len(SERIES)]
            self.table.selected = [r for r in self.table.rows if r["tag"] in first]
            self.set_selected(first)
        else:
            self.update_all()

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
        self.active_sel.options = tags
        if self.active not in tags:
            self.active = tags[-1] if tags else None
        self.active_sel.value = self.active
        self.active_sel.update()
        self.update_all()

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
         "Configurations": self.update_outliers, "Info": self.update_info}[self.tab]()

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
