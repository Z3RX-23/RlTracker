"""
coach_page.py

Separador "Treinador": dicas automaticas (coach.py) a partir do historico.
"""

import queue
import tkinter as tk

import ai_coach
from i18n import tr

from coach import analyze, analyze_replays
from history_page import PERIODS, SCOPES, since_for
from ui_kit import Card, FlatButton, Segmented, WrapLabel, C, F, P, caption

LEVEL_COLOR = {"warn": "warn", "good": "good", "info": "accent"}
MAX_TIPS = 6


class CoachPage(tk.Frame):
    def __init__(self, master, history, profiles, replay_store=None, ai_settings=None, open_settings=None):
        super().__init__(master, bg=C["bg"])
        self.history, self.profiles, self.replay_store = history, profiles, replay_store
        self._ai_settings, self._open_settings = ai_settings, open_settings
        self.period, self.scope = PERIODS[2], SCOPES[0]   # 30 dias, perfil ativo

        bar = tk.Frame(self, bg=C["bg"])
        bar.pack(fill="x", pady=(0, P(10)))
        for label, opts, attr in (("Período", PERIODS, "period"), ("Perfil", SCOPES, "scope")):
            box = tk.Frame(bar, bg=C["bg"])
            box.pack(side="left", padx=(0, P(16)))
            caption(box, label, bg=C["bg"]).pack(anchor="w", pady=(0, P(3)))
            Segmented(box, opts, getattr(self, attr), bg=C["surface"],
                      command=lambda v, a=attr: self._set(a, v), px=11, py=5).pack(anchor="w")

        self.summary_lbl = tk.Label(self, text="", bg=C["bg"], fg=C["muted"], font=F(9), anchor="w")
        self.summary_lbl.pack(fill="x", pady=(0, P(8)))

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=3, uniform="cp")
        body.grid_columnconfigure(1, weight=2, uniform="cp")
        body.grid_rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=C["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, P(10)))
        right = tk.Frame(body, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        self._build_ai(right)

        self.list = tk.Frame(left, bg=C["bg"])
        self.list.pack(fill="x")

        WrapLabel(left, text="Dicas automáticas a partir das tuas stats (golos, assistências, defesas, "
                            "remates, pontos e placar). A API do jogo não dá posicionamento nem boost, "
                            "por isso são tendências, não análise de jogadas.",
                 bg=C["bg"], fg=C["dim"], font=F(8), justify="left", anchor="w",
                 wraplength=P(640)).pack(fill="x", pady=(P(10), 0))

    # ---- analise com IA ----------------------------------------------------

    def _build_ai(self, parent):
        self.ai = self._ai_settings or ai_coach.AISettings()
        self._ai_q = queue.Queue()
        card = Card(parent, bg=C["surface"], radius=14, pad=12)
        card.pack(fill="x")
        b = card.body
        head = tk.Frame(b, bg=C["surface"])
        head.pack(fill="x")
        caption(head, "Análise com IA", color=C["accent"], bg=C["surface"]).pack(side="left")
        self.ai_cfg_btn = FlatButton(head, "Definições", self._goto_settings, kind="subtle", py=3, px=8, size=8)
        self.ai_cfg_btn.pack(side="right")
        WrapLabel(b, text="Pede a um modelo na cloud conclusões a partir das tuas stats e replays. "
                         "Só vão números agregados (sem nomes nem ficheiros).",
                 bg=C["surface"], fg=C["muted"], font=F(8), justify="left", anchor="w",
                 wraplength=P(400)).pack(fill="x", pady=(P(4), P(8)))

        row = tk.Frame(b, bg=C["surface"])
        row.pack(fill="x")
        self.ai_btn = FlatButton(row, "Analisar com IA", self._ai_run, kind="primary")
        self.ai_btn.pack(side="left")
        self.ai_prev_btn = FlatButton(row, "Ver dados enviados", self._ai_toggle_preview,
                                      kind="subtle", py=5, px=10, size=9)
        self.ai_prev_btn.pack(side="left", padx=(P(8), 0))
        self.ai_out = tk.Text(b, height=1, wrap="word", bg=C["surface"], fg=C["text"], font=F(9),
                              relief="flat", bd=0, highlightthickness=0, padx=0, pady=0,
                              cursor="arrow", state="disabled")
        self.ai_out.tag_config("data", foreground=C["text"])
        self.ai_out.tag_config("hyp", foreground=C["text"])
        self.ai_out.tag_config("badge_data", foreground=C["good"], font=F(8, "bold"))
        self.ai_out.tag_config("badge_hyp", foreground=C["warn"], font=F(8, "bold"))
        self.ai_out.tag_config("err", foreground=C["bad"])
        self.ai_out.tag_config("warn", foreground=C["warn"])
        self.ai_out.pack(fill="x", pady=(P(10), 0))
        self.ai_legend = WrapLabel(b, text="", bg=C["surface"], fg=C["dim"], font=F(8),
                                  anchor="w", justify="left", wraplength=P(400))
        self._ai_preview_on = False
        self.ai_preview = tk.Text(b, height=8, wrap="word", bg=C["surface2"], fg=C["muted"],
                                  font=F(8), relief="flat", bd=0, highlightthickness=0,
                                  padx=P(8), pady=P(6), state="disabled")

    def _ai_show(self, parts):
        """parts: [(texto, marca)] com marca None/data/hyp/err/warn."""
        t = self.ai_out
        t.config(state="normal")
        t.delete("1.0", "end")
        has_tags = False
        for text, mark in parts:
            if mark in ("data", "hyp"):
                has_tags = True
                t.insert("end", text.rstrip(), mark)
                t.insert("end", "  " + (tr("(dado)") if mark == "data" else tr("(hipótese)")),
                         "badge_" + mark)
            else:
                t.insert("end", text, mark or ())
        t.config(state="disabled")
        t.update_idletasks()
        try:
            lines = t.count("1.0", "end", "displaylines")[0]
        except (tk.TclError, TypeError, IndexError):
            lines = int(t.index("end-1c").split(".")[0]) + 2
        t.config(height=max(1, lines))
        if has_tags:
            self.ai_legend.config(text=tr("(dado) vem dos teus números; (hipótese) é interpretação da IA."))
            self.ai_legend.pack(fill="x", pady=(P(6), 0))
        else:
            self.ai_legend.pack_forget()

    def _ai_toggle_preview(self):
        self._ai_preview_on = not self._ai_preview_on
        if not self._ai_preview_on:
            self.ai_preview.pack_forget()
            self.ai_prev_btn.config(text="Ver dados enviados")
            return
        pid = self.profiles.active().id if self.scope == SCOPES[0] else None
        summary = ai_coach.build_summary(self.history, self.replay_store, pid, since_for(self.period))
        self.ai_preview.config(state="normal")
        self.ai_preview.delete("1.0", "end")
        self.ai_preview.insert("1.0", ai_coach.preview(self.ai, summary))
        self.ai_preview.config(state="disabled")
        self.ai_preview.pack(fill="x", pady=(P(10), 0))
        self.ai_prev_btn.config(text="Ocultar dados enviados")

    def _goto_settings(self):
        if self._open_settings:
            self._open_settings()

    def _ai_run(self):
        if not self.ai.ready():
            self._ai_show([(tr("Preenche a chave, o modelo e o endereço em Definições."), "warn")])
            return
        pid = self.profiles.active().id if self.scope == SCOPES[0] else None
        summary = ai_coach.build_summary(self.history, self.replay_store, pid, since_for(self.period))
        self.ai_btn.config(text="A analisar…")
        self._ai_show([])

        ai_coach.ask_async(self.ai, summary, lambda text, err: self._ai_q.put((text, err)))
        self.after(300, self._ai_poll)

    def _ai_poll(self):
        """A thread de fundo so' poe o resultado numa fila; o Tk le-a aqui."""
        try:
            text, err = self._ai_q.get_nowait()
        except queue.Empty:
            self.after(300, self._ai_poll)
            return
        self._ai_done(text, err)

    def _ai_done(self, text, err):
        self.ai_btn.config(text="Analisar com IA")
        if err:
            self._ai_show([(tr("Não consegui obter a análise: {err}", err=err), "err")])
        else:
            self._ai_show(ai_coach.split_tags(text))

    def _set(self, attr, value):
        setattr(self, attr, value)
        self.refresh()

    def refresh(self):
        pid = self.profiles.active().id if self.scope == SCOPES[0] else None
        rows = self.history.recent(pid, since_for(self.period), None, limit=500)
        tips = analyze(rows)[:MAX_TIPS]
        rtips = []
        nrep = 0
        if self.replay_store is not None and self.profiles.active().id:
            rrows = self.replay_store.replays(
                self.profiles.active().id if self.scope == SCOPES[0] else None, limit=300)
            nrep = len(rrows)
            if nrep:
                rtips = analyze_replays(rrows)[:MAX_TIPS]
        self.summary_lbl.config(text=tr("{n} partidas analisadas", n=len(rows)) +
                                (tr("  ·  {n} replays", n=nrep) if nrep else
                                 tr("  ·  liga o Ballchasing no separador Replays para dicas de boost e posicionamento")))
        for w in self.list.winfo_children():
            w.destroy()
        if rtips:
            tips = tips + [dict(level="sep", title=tr("Com base nos replays"), text="")] + rtips
        for t in tips:
            if t["level"] == "sep":
                caption(self.list, t["title"], color=C["accent"], bg=C["bg"]).pack(
                    anchor="w", pady=(P(6), P(6)))
                continue
            color = C[LEVEL_COLOR[t["level"]]]
            card = Card(self.list, bg=C["surface"], radius=12, pad=12)
            card.pack(fill="x", pady=(0, P(8)))
            b = card.body
            stripe = tk.Frame(b, bg=color, width=P(4))
            stripe.pack(side="left", fill="y", padx=(0, P(12)))
            txt = tk.Frame(b, bg=C["surface"])
            txt.pack(side="left", fill="x", expand=True)
            tk.Label(txt, text=t["title"], bg=C["surface"], fg=color,
                     font=F(11, "bold"), anchor="w").pack(fill="x")
            WrapLabel(txt, text=t["text"], bg=C["surface"], fg=C["text"], font=F(9),
                     anchor="w", justify="left", wraplength=P(600)).pack(fill="x", pady=(P(2), 0))
