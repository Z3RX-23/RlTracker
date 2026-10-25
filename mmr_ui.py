"""
mmr_ui.py

MMR registado a mao: caixa de registo (usada no Ao vivo e no Historico) e
o painel do Historico com evolucao, ganhos medios e variacao.
"""

import queue
import time
import threading
import tkinter as tk
from tkinter import ttk
from datetime import datetime

import charts
import mmr
import rlapi
from history import MODE_LABELS
from i18n import tr
from ui_kit import C, F, P, Card, FlatButton, Segmented, caption, make_entry


MODE_ONLY = "Só este modo"
MODE_ALL = "Todos os modos"


def _signed(d):
    return "—" if d is None else f"{d:+d}"


def _color(d):
    return C["dim"] if not d else (C["good"] if d > 0 else C["bad"])


class MMRBox(tk.Frame):
    """Modo + campo + Guardar. `on_change(mode)` e' chamado depois de gravar/mudar modo."""

    def __init__(self, master, history, profiles, bg, on_change=None, mode="doubles"):
        super().__init__(master, bg=bg)
        self.history, self.profiles, self.on_change = history, profiles, on_change
        self.mode = mode
        Segmented(self, [MODE_LABELS[m] for m in mmr.MMR_MODES], MODE_LABELS[mode],
                  bg=C["surface3"], size=8, px=8, py=2, command=self._set_mode).pack(side="left")
        self.entry = make_entry(self, width=7)
        self.entry.pack(side="left", padx=(P(8), P(6)), ipady=P(3))
        self.entry.bind("<Return>", lambda _e: self.save())
        FlatButton(self, "Guardar MMR", self.save, kind="ghost").pack(side="left")
        self.sync_btn = FlatButton(self, "Atualizar do jogo", self.refresh_online, kind="ghost")
        self.sync_btn.pack(side="left", padx=(P(6), 0))
        self.quota = tk.Label(self, text="", bg=bg, fg=C["dim"], font=F(8))
        self.quota.pack(side="right", padx=(P(10), 0))
        self.on_sync = None
        self._q = queue.Queue()
        self._busy = False
        self.after(500, self._poll)
        self.status = tk.Label(self, text="", bg=bg, fg=C["muted"], font=F(9))
        self.status.pack(side="left", padx=(P(10), 0))
        self._show_status()

    def _pid(self):
        return self.profiles.active().id

    def _set_mode(self, label):
        self.mode = next(m for m in mmr.MMR_MODES if MODE_LABELS[m] == label)
        self._show_status()
        if self.on_change:
            self.on_change(self.mode)

    def _show_status(self, err=None):
        if err:
            self.status.config(text=err, fg=C["bad"])
            return
        es = self.history.mmr_entries(self.mode, self._pid())
        if not es:
            self.status.config(text=tr("sem registos neste modo"), fg=C["dim"])
            return
        today = mmr.delta_since(es, mmr.since_ts(0))
        txt = f"{es[-1]['mmr']} MMR"
        if today is not None:
            txt += tr("  ({d} hoje)", d=_signed(today))
        self.status.config(text=txt, fg=_color(today) if today else C["text"])
        self._show_quota()

    def _show_quota(self):
        st = rlapi.SETTINGS
        if not st.api_key:
            self.quota.config(text="")
            return
        self.quota.config(text=tr("Pedidos hoje: {u}/{m}", u=st.used_today(), m=st.daily_limit),
                          fg=C["warn"] if st.left_today() <= 1 else C["dim"])

    def save(self):
        v = mmr.valid_mmr(self.entry.get())
        if v is None:
            self._show_status(tr("Escreve só o número (ex.: 1043)."))
            return
        if not self.history.add_mmr(self.mode, v, self._pid()):
            self._show_status(tr("Não consegui gravar."))
            return
        self.entry.delete(0, "end")
        self._show_status()
        if self.on_change:
            self.on_change(self.mode)

    def refresh(self):
        self._show_status()

    # ---- MMR automatico (API) ------------------------------------------------

    def refresh_online(self, silent=False):
        st = rlapi.SETTINGS
        if self._busy:
            return
        if not st.api_key:
            if not silent:
                self._show_status(tr("Falta a chave da API (Definições > MMR)."))
            return
        self._busy = True
        rlapi.LAST_SYNC = time.time()
        if not silent and self.on_sync:
            self.on_sync()
        if not silent:
            self.status.config(text=tr("A consultar o MMR…"), fg=C["muted"])
        prof = self.profiles.active()

        def work():
            try:
                res = rlapi.refresh_mmr(self.history, prof, st)
                self._q.put(("ok", res, silent))
            except rlapi.RLApiError as e:
                self._q.put(("err", str(e), silent))
            except Exception as e:                      # nunca deixar a thread morrer calada
                self._q.put(("err", str(e), silent))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            if not self.winfo_exists():
                return
            while True:
                kind, val, silent = self._q.get_nowait()
                self._busy = False
                self._show_quota()
                if kind == "ok":
                    self._show_status()
                    if val and self.on_change:
                        self.on_change(self.mode)
                    if not silent and not val:
                        self.status.config(text=self.status.cget("text") + tr("  · sem alterações"),
                                           fg=self.status.cget("fg"))
                elif not silent:
                    self._show_status(val)
        except queue.Empty:
            pass
        except tk.TclError:
            return
        self.after(500, self._poll)


class MMRPanel(tk.Frame):
    def __init__(self, master, history, profiles):
        super().__init__(master, bg=C["bg"])
        self.history, self.profiles = history, profiles
        self.mode = "doubles"
        top = Card(self, bg=C["surface"], radius=14, pad=12)
        top.pack(fill="x")
        row = tk.Frame(top.body, bg=C["surface"])
        row.pack(fill="x")
        caption(row, "MMR registado", color=C["accent"], bg=C["surface"]).pack(side="left", padx=(0, P(14)))
        self.box = MMRBox(row, history, profiles, C["surface"], on_change=self._on_box)
        self.box.pack(side="left")
        FlatButton(row, "Apagar último registo", self._delete_last, kind="ghost").pack(side="right")

        self.tiles = tk.Frame(self, bg=C["bg"])
        self.tiles.pack(fill="x", pady=(P(10), 0))
        cc = Card(self, bg=C["surface"], radius=14, pad=12)
        cc.pack(fill="x", pady=(P(10), 0))
        hdr = tk.Frame(cc.body, bg=C["surface"])
        hdr.pack(fill="x", pady=(0, P(6)))
        caption(hdr, "Evolução do MMR", color=C["accent"], bg=C["surface"]).pack(side="left")
        self.compare_all = False
        Segmented(hdr, [MODE_ONLY, MODE_ALL], MODE_ONLY, bg=C["surface3"], size=8, px=8, py=2,
                  command=self._set_compare).pack(side="right")
        self._info_text = ""
        self.hint = tk.Label(cc.body, text="", bg=C["surface"], fg=C["muted"], font=F(8), anchor="w",
                             justify="left", wraplength=P(880))
        self.hint.pack(side="bottom", fill="x")
        self.chart = charts.MMRChart(cc.body, C["surface"], height=92,
                                     on_hover=lambda t: self.hint.config(text=t or self._info_text))
        self.chart.pack(fill="x")
        tb = Card(self, bg=C["surface"], radius=14, pad=10)
        tb.pack(fill="x", pady=(P(10), 0))
        caption(tb.body, "Registos", color=C["accent"], bg=C["surface"]).pack(anchor="w", pady=(0, P(4)))
        cols = (("ts", "Data", 150, "w"), ("mmr", "MMR", 80, "e"), ("d", "Variação", 90, "e"))
        wrap = tk.Frame(tb.body, bg=C["surface"])
        wrap.pack(fill="x")
        self.table = ttk.Treeview(wrap, columns=[c[0] for c in cols], show="headings",
                                  style="RL.Treeview", height=3)
        for key, title, w, anc in cols:
            self.table.heading(key, text=tr(title), anchor=anc if anc != "e" else "e")
            self.table.column(key, width=P(w), anchor=anc, stretch=key == "ts")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.table.yview, style="RL.Vertical.TScrollbar")
        self.table.configure(yscrollcommand=sb.set)
        self.table.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        self.table.tag_configure("up", foreground=C["good"])
        self.table.tag_configure("down", foreground=C["bad"])

    def _set_compare(self, label):
        self.compare_all = label == MODE_ALL
        self.refresh()

    def _refresh_chart(self, pid, es):
        colors = {"duel": C["warn"], "doubles": C["accent"], "standard": C["good"]}
        modes = mmr.MMR_MODES if self.compare_all else [self.mode]
        series = []
        for m in modes:
            rows = es if m == self.mode else self.history.mmr_entries(m, pid)
            pts = [(datetime.strptime(e["ts"], mmr.FMT), e["mmr"]) for e in rows
                   if mmr._parse(e["ts"])]
            series.append({"mode": m, "label": MODE_LABELS[m], "color": colors[m], "points": pts})
        self.chart.set_series(series, self.mode)

    def _on_box(self, mode):
        self.mode = mode
        self.refresh()

    def _delete_last(self):
        self.history.delete_last_mmr(self.mode, self.profiles.active().id)
        self.box.refresh()
        self.refresh()

    def _tile(self, col, cap, text, color):
        f = Card(self.tiles, bg=C["surface"], radius=14, pad=10)
        f.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else P(5), P(5) if col < 4 else 0))
        self.tiles.grid_columnconfigure(col, weight=1, uniform="mm")
        caption(f.body, cap, bg=C["surface"]).pack(anchor="w")
        tk.Label(f.body, text=text, bg=C["surface"], fg=color, font=F(16, "bold")).pack(anchor="w")

    def refresh(self):
        pid = self.profiles.active().id
        es = self.history.mmr_entries(self.mode, pid)
        for w in self.tiles.winfo_children():
            w.destroy()
        s = mmr.summary(es)
        if s:
            self._tile(0, "Atual", str(s["now"]), C["text"])
            self._tile(1, "Hoje", _signed(s["today"]), _color(s["today"]))
            self._tile(2, "7 dias", _signed(s["week"]), _color(s["week"]))
            self._tile(3, "Melhor", str(s["best"]), C["good"])
            self._tile(4, "Registos", str(s["n"]), C["muted"])
        else:
            self._tile(0, "Atual", "—", C["dim"])
        self._refresh_chart(pid, es)
        for it in self.table.get_children():
            self.table.delete(it)
        for ts, v, d in mmr.table_rows(es):
            self.table.insert("", "end", tags=(("up" if d > 0 else "down") if d else "",),
                              values=(ts, v, "" if d is None else f"{d:+d}"))
        g = mmr.gains(es, self.history.recent(pid, None, self.mode, limit=10**9))
        lines = []
        if g["win_n"] >= mmr.MIN_GAIN_SAMPLES:
            lines.append(tr("Ganhas em média {v:+.0f} MMR por vitória (com {n} jogos medidos).",
                            v=g["win_avg"], n=g["win_n"]))
        if g["loss_n"] >= mmr.MIN_GAIN_SAMPLES:
            lines.append(tr("Perdes em média {v:+.0f} MMR por derrota (com {n} jogos medidos).",
                            v=g["loss_avg"], n=g["loss_n"]))
        if not lines:
            lines.append(tr("Para calcular quanto ganhas/perdes por jogo, regista o MMR depois de CADA jogo "
                            "(só contam intervalos com exatamente um jogo, mínimo {n} de cada).",
                            n=mmr.MIN_GAIN_SAMPLES))
        lines.append(tr("O MMR é escrito por ti — a Stats API do jogo não o fornece."))
        self._info_text = "\n".join(lines)
        self.hint.config(text=self._info_text)
