"""
history_page.py

Pagina "Historico" (dentro da janela principal): cartoes com as stats por
modo (1v1/2v2/3v3/total), lista das ultimas partidas, filtros por
periodo/perfil/modo e export CSV.
"""

import tkinter as tk
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox, ttk

import charts
from mmr_ui import MMRPanel
from compare import CompareStrip, compare_match
from history import MODE_LABELS, MODES
from i18n import tr
from ui_kit import WrapLabel, Bar, Card, FlatButton, Segmented, C, F, P, caption

PERIODS = ["Hoje", "7 dias", "30 dias", "Tudo"]
SCOPES = ["Perfil ativo", "Todos"]
MODE_FILTERS = ["Todos"] + [MODE_LABELS[m] for m in MODES]
VIEWS = ["Resumo", "Gráficos", "MMR"]

RECENT_COLS = [
    ("ts", "Data", 150, "w"), ("perfil", "Perfil", 130, "w"), ("modo", "Modo", 60, "w"),
    ("res", "Resultado", 90, "w"), ("placar", "Placar", 70, "center"),
    ("g", "Golos", 55, "e"), ("a", "Assist.", 55, "e"), ("sv", "Defesas", 65, "e"),
    ("sh", "Remates", 70, "e"), ("pts", "Pontos", 65, "e"),
]


def since_for(period, now=None):
    """Limite inferior (hora local, 'YYYY-MM-DD HH:MM:SS') ou None."""
    now = now or datetime.now()
    fmt = "%Y-%m-%d %H:%M:%S"
    if period == "Hoje":
        return now.replace(hour=0, minute=0, second=0, microsecond=0).strftime(fmt)
    if period == "7 dias":
        return (now - timedelta(days=7)).strftime(fmt)
    if period == "30 dias":
        return (now - timedelta(days=30)).strftime(fmt)
    return None


class HistoryPage(tk.Frame):
    def __init__(self, master, history, profiles):
        super().__init__(master, bg=C["bg"])
        self.history, self.profiles = history, profiles
        self.period, self.scope, self.mode = PERIODS[1], SCOPES[0], MODE_FILTERS[0]
        self.view = VIEWS[0]
        self._rows, self._summ = {}, {}
        self._build()

    # ---- construcao --------------------------------------------------------

    def _build(self):
        bar = tk.Frame(self, bg=C["bg"])
        bar.pack(fill="x", pady=(0, P(10)))
        for label, opts, attr in (("Período", PERIODS, "period"),
                                  ("Perfil", SCOPES, "scope"),
                                  ("Modo da lista", MODE_FILTERS, "mode"),
                                  ("Vista", VIEWS, "view")):
            box = tk.Frame(bar, bg=C["bg"])
            box.pack(side="left", padx=(0, P(16)))
            caption(box, label, bg=C["bg"]).pack(anchor="w", pady=(0, P(3)))
            Segmented(box, opts, getattr(self, attr), bg=C["surface"],
                      command=lambda v, a=attr: self._set(a, v), px=8, py=5).pack(anchor="w")
        FlatButton(bar, "Exportar CSV", self._export, kind="ghost").pack(side="right", anchor="s")

        self.cards_row = tk.Frame(self, bg=C["bg"])
        self.cards_row.pack(fill="x")

        self.empty_lbl = tk.Label(self, text="Sem partidas registadas neste filtro.",
                                  bg=C["bg"], fg=C["muted"], font=F(9))

        tbl = self.table_card = Card(self, bg=C["surface"], radius=14, pad=10, fit=False)
        tbl.pack(fill="both", expand=True, pady=(P(12), 0))
        hdr = tk.Frame(tbl.body, bg=C["surface"])
        hdr.pack(fill="x", pady=(0, P(6)))
        caption(hdr, "Últimas partidas", color=C["accent"], bg=C["surface"]).pack(side="left")
        tk.Label(hdr, text="~ resultado estimado pelo placar   ·   modo inferido pelo tamanho das equipas "
                           "(não distingue ranked de casual)",
                 bg=C["surface"], fg=C["dim"], font=F(8)).pack(side="right")

        self._style_tree()
        self.compare = CompareStrip(tbl.body, C["surface"])
        self.compare.pack(side="bottom", fill="x")
        wrap = tk.Frame(tbl.body, bg=C["surface"])
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in RECENT_COLS],
                                 show="headings", style="RL.Treeview")
        for key, title, width, anchor in RECENT_COLS:
            self.tree.heading(key, text=tr(title), anchor=anchor if anchor != "e" else "e")
            self.tree.column(key, width=P(width), anchor=anchor, stretch=key in ("perfil", "ts"))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview, style="RL.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("win", foreground=C["good"])
        self.tree.tag_configure("loss", foreground=C["bad"])
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self._build_charts()
        self.mmr_panel = MMRPanel(self, self.history, self.profiles)

    # ---- graficos ----------------------------------------------------------

    METRICS = [("Pontos", "score", "pontos"), ("Golos", "goals", "golos"), ("Assist.", "assists", "assist."),
               ("Defesas", "saves", "defesas"), ("Remates", "shots", "remates")]

    def _build_charts(self):
        self.charts_frame = tk.Frame(self, bg=C["bg"])
        self.chart_hint = tk.Label(self.charts_frame, text="", bg=C["bg"], fg=C["muted"],
                                   font=F(9), anchor="w")
        self.chart_hint.pack(side="bottom", fill="x", pady=(P(6), 0))
        grid = tk.Frame(self.charts_frame, bg=C["bg"])
        grid.pack(fill="x")
        for i in range(3):
            grid.columnconfigure(i, weight=1, uniform="ch")

        def card(title, row, col, span=1):
            c = Card(grid, bg=C["surface"], radius=14, pad=12)
            c.grid(row=row, column=col, columnspan=span, sticky="nsew",
                   padx=(0 if col == 0 else P(5), 0 if col + span == 3 else P(5)),
                   pady=(0 if row == 0 else P(10), 0))
            caption(c.body, title, color=C["accent"], bg=C["surface"]).pack(anchor="w", pady=(0, P(6)))
            return c.body

        hint = lambda t: self.chart_hint.config(text=t)
        b = card("Win % pelo nº do jogo na sessão", 0, 0)
        self.pos_chart = charts.BarChart(b, C["surface"], height=118, on_hover=hint)
        self.pos_chart.pack(fill="x")
        b = card("Win % depois de ganhar / perder", 0, 1)
        self.after_chart = charts.BarChart(b, C["surface"], height=118, on_hover=hint)
        self.after_chart.pack(fill="x")
        b = card("Evolução por jogo (média de 10)", 0, 2)
        self.metric = self.METRICS[0][1]
        Segmented(b, [m[0] for m in self.METRICS], self.METRICS[0][0], bg=C["surface"], size=8, px=6, py=2,
                  command=self._set_metric).pack(anchor="w", pady=(0, P(4)))
        self.trend_chart = charts.ValueChart(b, C["surface"], height=88, on_hover=hint, unit="pontos")
        self.trend_chart.pack(fill="x")
        b = card("Win % por hora do dia", 1, 0, span=2)
        self.hour_chart = charts.BarChart(b, C["surface"], height=118, on_hover=hint)
        self.hour_chart.pack(fill="x")
        b = card("Win % por dia da semana", 1, 2)
        self.day_chart = charts.BarChart(b, C["surface"], height=118, on_hover=hint)
        self.day_chart.pack(fill="x")
        self.insight_lbl = WrapLabel(self.charts_frame, text="", bg=C["bg"], fg=C["text"], font=F(9),
                                     anchor="w", justify="left", wraplength=P(900))
        self.insight_lbl.pack(fill="x", pady=(P(10), 0))
        self._chart_rows = []

    def _set_metric(self, label):
        for lab, key, unit in self.METRICS:
            if lab == label:
                self.metric = key
                self.trend_chart.set_unit(unit)
        self._refresh_trend()

    def _refresh_trend(self):
        self.trend_chart.set(charts.rolling_avg(self._chart_rows, self.metric, 10))

    def _apply_view(self):
        for w in (self.cards_row, self.empty_lbl, self.table_card, self.charts_frame, self.mmr_panel):
            w.pack_forget()
        if self.view == VIEWS[2]:
            self.mmr_panel.pack(fill="both", expand=True, pady=(P(2), 0))
        elif self.view == VIEWS[1]:
            self.charts_frame.pack(fill="both", expand=True, pady=(P(2), 0))
        else:
            self.cards_row.pack(fill="x")
            self.table_card.pack(fill="both", expand=True, pady=(P(12), 0))

    def _refresh_charts(self, rows):
        self.chart_hint.config(text="")
        self._chart_rows = rows
        self._refresh_trend()
        pos = charts.by_session_position(rows)
        self.pos_chart.set([((f"{i + 1}+" if i == charts.POS_CAP - 1 else str(i + 1)), charts.pct(b), b[0])
                            for i, b in enumerate(pos)])
        aft = charts.after_result(rows)
        self.after_chart.set([(tr(name), charts.pct(b), b[0]) for name, b in
                              zip(("1.º jogo", "Após vitória", "Após derrota"), aft)])
        hours, days = charts.by_hour(rows), charts.by_weekday(rows)
        self.hour_chart.set([(f"{h}h", charts.pct(b), b[0]) for h, b in enumerate(hours)])
        self.day_chart.set([(tr(charts.WEEKDAYS[i]), charts.pct(b), b[0]) for i, b in enumerate(days)])
        lines = []
        early = [sum(b[0] for b in pos[:3]), sum(b[1] for b in pos[:3])]
        late = [sum(b[0] for b in pos[3:]), sum(b[1] for b in pos[3:])]
        if early[0] >= 5 and late[0] >= 5:
            lines.append(tr("Nos 3 primeiros jogos da sessão ganhas {a:.0f}% ({na} jogos); do 4.º em diante, {b:.0f}% ({nb} jogos).",
                            a=charts.pct(early), na=early[0], b=charts.pct(late), nb=late[0]))
        if aft[1][0] >= 5 and aft[2][0] >= 5:
            lines.append(tr("Depois de ganhar ganhas {a:.0f}% ({na} jogos); depois de perder, {b:.0f}% ({nb} jogos).",
                            a=charts.pct(aft[1]), na=aft[1][0], b=charts.pct(aft[2]), nb=aft[2][0]))
        bw = charts.best_worst(hours)
        if bw:
            g, w = bw
            lines.append(tr("Melhor hora: {a}h ({pa:.0f}% em {na} jogos)  ·  pior hora: {b}h ({pb:.0f}% em {nb} jogos).",
                            a=g, pa=charts.pct(hours[g]), na=hours[g][0],
                            b=w, pb=charts.pct(hours[w]), nb=hours[w][0]))
        bw = charts.best_worst(days)
        if bw:
            g, w = bw
            lines.append(tr("Melhor dia: {a} ({pa:.0f}% em {na} jogos)  ·  pior dia: {b} ({pb:.0f}% em {nb} jogos).",
                            a=tr(charts.WEEKDAYS[g]), pa=charts.pct(days[g]), na=days[g][0],
                            b=tr(charts.WEEKDAYS[w]), pb=charts.pct(days[w]), nb=days[w][0]))
        if lines:
            lines.append(tr("Uma sessão são jogos seguidos com menos de 1 h entre eles. Só há barra com pelo menos {n} jogos; "
                            "um traço cinzento na base quer dizer poucos jogos.", n=charts.MIN_BUCKET))
        elif rows:
            lines.append(tr("Ainda há poucos jogos por hora/dia para tirar conclusões."))
        else:
            lines.append(tr("Sem partidas registadas neste filtro."))
        self.insight_lbl.config(text="\n".join(lines))

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        r = self._rows.get(sel[0]) if sel else None
        if not r:
            self.compare.clear()
            return
        avg = self._summ.get(r["mode"])
        if not avg or avg.get("n", 0) < 3:
            avg = self._summ.get("total") or {}
            who = tr("a tua média no período")
        else:
            who = tr("a tua média em {m}", m=tr(MODE_LABELS.get(r["mode"], r["mode"])))
        items = compare_match(r, avg)
        if not items:
            self.compare.clear()
            return
        self.compare.show(tr("Esta partida vs {who}", who=who), items)

    def _style_tree(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("RL.Treeview", background=C["surface"], fieldbackground=C["surface"],
                     foreground=C["text"], rowheight=P(26), borderwidth=0, font=F(9, "medium"),
                     bordercolor=C["surface"], lightcolor=C["surface"], darkcolor=C["surface"])
        st.layout("RL.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("RL.Treeview.Heading", background=C["surface"], foreground=C["muted"],
                     relief="flat", borderwidth=0, font=F(8, "bold"), padding=(P(6), P(6)))
        st.map("RL.Treeview", background=[("selected", C["surface3"])],
               foreground=[("selected", C["text"])])
        st.map("RL.Treeview.Heading", background=[("active", C["surface"])])
        st.configure("RL.Vertical.TScrollbar", background=C["surface3"], troughcolor=C["surface"],
                     bordercolor=C["surface"], arrowcolor=C["muted"], lightcolor=C["surface3"],
                     darkcolor=C["surface3"], relief="flat")

    # ---- dados -------------------------------------------------------------

    def _set(self, attr, value):
        setattr(self, attr, value)
        self.refresh()

    def _filters(self):
        pid = self.profiles.active().id if self.scope == SCOPES[0] else None
        mode = next((m for m in MODES if MODE_LABELS[m] == self.mode), None)
        return pid, since_for(self.period), mode

    def refresh(self):
        pid, since, mode = self._filters()
        self._apply_view()
        if self.view == VIEWS[2]:
            self.mmr_panel.box.refresh()
            self.mmr_panel.refresh()
            return
        if self.view == VIEWS[1]:
            self._refresh_charts(self.history.recent(pid, since, mode, limit=5000))
            return
        summ = self._summ = self.history.summary(pid, since)

        for w in self.cards_row.winfo_children():
            w.destroy()
        keys = [m for m in ("duel", "doubles", "standard") ] + (["other"] if "other" in summ else []) + ["total"]
        for i, k in enumerate(keys):
            self.cards_row.grid_columnconfigure(i, weight=1, uniform="mc")
            self._mode_card(i, k, summ.get(k))
        if summ["total"]["n"]:
            self.empty_lbl.pack_forget()
        else:
            self.empty_lbl.pack(anchor="w", pady=(P(6), 0), before=self.table_card)

        for item in self.tree.get_children():
            self.tree.delete(item)
        self._rows = {}
        self.compare.clear()
        for r in self.history.recent(pid, since, mode, limit=300):
            res = (tr("Vitória") if r["won"] else tr("Derrota")) + (" ~" if r["estimated"] else "")
            placar = (f"{r['my_score']} - {r['opp_score']}"
                      if r["my_score"] is not None and r["opp_score"] is not None else "-")
            iid = self.tree.insert("", "end", tags=("win" if r["won"] else "loss",), values=(
                r["ts"], r["profile_name"] or tr("(sem nome)"),
                tr(MODE_LABELS.get(r["mode"], r["mode"])), res, placar,
                r["goals"], r["assists"], r["saves"], r["shots"], r["score"]))
            self._rows[iid] = r

    def _mode_card(self, col, key, d):
        total = key == "total"
        label = "Total" if total else MODE_LABELS[key]
        card = Card(self.cards_row, bg=C["surface2"] if total else C["surface"], radius=14, pad=12)
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else P(5), P(5)))
        b = card.body
        bg = C["surface2"] if total else C["surface"]

        top = tk.Frame(b, bg=bg)
        top.pack(fill="x")
        tk.Label(top, text=label, bg=bg, fg=C["accent"] if not total else C["text"],
                 font=F(12, "bold")).pack(side="left")
        n = d["n"] if d else 0
        tk.Label(top, text=tr("{n} jogo", n=n) if n == 1 else tr("{n} jogos", n=n), bg=bg, fg=C["muted"],
                 font=F(8)).pack(side="right")

        if not d or not n:
            tk.Label(b, text="Sem jogos", bg=bg, fg=C["dim"], font=F(10)).pack(
                anchor="w", pady=(P(14), P(26)))
            return

        pct = d["win_pct"]
        col_pct = C["good"] if pct >= 55 else (C["bad"] if pct < 45 else C["text"])
        row = tk.Frame(b, bg=bg)
        row.pack(fill="x", pady=(P(6), P(4)))
        tk.Label(row, text=f"{pct:.0f}%", bg=bg, fg=col_pct, font=F(24, "bold")).pack(side="left")
        wl = tk.Frame(row, bg=bg)
        wl.pack(side="right", anchor="s", pady=(0, P(4)))
        tk.Label(wl, text=str(d["wins"]), bg=bg, fg=C["good"], font=F(11, "bold")).pack(side="left")
        tk.Label(wl, text=" V   ", bg=bg, fg=C["muted"], font=F(8)).pack(side="left")
        tk.Label(wl, text=str(d["losses"]), bg=bg, fg=C["bad"], font=F(11, "bold")).pack(side="left")
        tk.Label(wl, text=" D", bg=bg, fg=C["muted"], font=F(8)).pack(side="left")

        bar = Bar(b, height=6, bg=bg)
        bar.pack(fill="x", pady=(0, P(8)))
        bar.set([(d["wins"] / n, C["good"]), (d["losses"] / n, C["bad"])])

        grid = tk.Frame(b, bg=bg)
        grid.pack(fill="x")
        stats = [("Golos/j", f"{d['goals_avg']:.2f}"), ("Assist./j", f"{d['assists_avg']:.2f}"),
                 ("Defesas/j", f"{d['saves_avg']:.2f}"), ("Remates/j", f"{d['shots_avg']:.2f}"),
                 ("Precisão", f"{d['accuracy']:.0f}%" if d["shots"] else "-"),
                 ("Pontos/j", f"{d['score_avg']:.0f}")]
        for i, (k, v) in enumerate(stats):
            r, c = divmod(i, 3)
            grid.grid_columnconfigure(c, weight=1, uniform="st")
            cell = tk.Frame(grid, bg=bg)
            cell.grid(row=r, column=c, sticky="w", pady=(0, P(5)))
            tk.Label(cell, text=v, bg=bg, fg=C["text"], font=F(10, "bold")).pack(anchor="w")
            tk.Label(cell, text=k, bg=bg, fg=C["muted"], font=F(7)).pack(anchor="w")

    # ---- export ------------------------------------------------------------

    def _export(self):
        pid, since, mode = self._filters()
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", initialfile="rl_historico.csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            n = self.history.export_csv(path, pid, since, mode)
        except OSError as e:
            messagebox.showerror(tr("Exportar CSV"), tr("Não foi possível gravar: {err}", err=e), parent=self)
            return
        messagebox.showinfo(tr("Exportar CSV"), tr("{n} partidas exportadas.", n=n), parent=self)
