"""
replays_page.py

Separador "Replays": liga ao Ballchasing, envia os replays da pasta do jogo
e mostra as tuas medias (posse, boost, posicionamento) e a lista de replays.
"""

import queue
import tkinter as tk
import webbrowser
from tkinter import ttk

from ballchasing import ReplayStore, ReplaySync, Settings
from compare import CompareStrip, compare_replay
from i18n import tr
from coach import replay_averages
from ui_kit import Card, Dropdown, FlatButton, StatTile, Switch, C, F, P, caption

COLS = [("date", "Data", 150, "w"), ("playlist", "Modo", 110, "w"), ("res", "Resultado", 80, "w"),
        ("poss", "Posse", 65, "e"), ("bpm", "Boost/min", 80, "e"), ("zero", "Sem boost", 80, "e"),
        ("behind", "Atrás da bola", 100, "e"), ("link", "", 60, "center")]


def _fmt(v, suffix="", digits=0):
    return "-" if v is None else f"{v:.{digits}f}{suffix}"


class ReplaysPage(tk.Frame):
    def __init__(self, master, profiles, open_settings=None):
        super().__init__(master, bg=C["bg"])
        self.profiles = profiles
        self._open_settings = open_settings
        self.settings = Settings()
        self.store = ReplayStore()
        self._q = queue.Queue()
        self.sync = ReplaySync(self.settings, self.store, profiles,
                               lambda kind, payload: self._q.put((kind, payload)))
        self._links = {}
        self._rows, self._avg = {}, {}
        self._build()
        self.after(300, self._poll)
        if self.settings.auto and self.settings.token:
            self.sync.set_auto(True)

    # ---- construcao --------------------------------------------------------

    def _build(self):
        bar = Card(self, bg=C["surface"], radius=14, pad=10)
        bar.pack(fill="x")
        row = tk.Frame(bar.body, bg=C["surface"])
        row.pack(fill="x")
        self.status = tk.Label(row, text="", bg=C["surface"], fg=C["muted"], font=F(9),
                               anchor="w", justify="left", wraplength=P(620))
        self.status.pack(side="left", fill="x", expand=True)
        FlatButton(row, "Sincronizar agora", self._sync_now, kind="primary").pack(side="right")
        self.auto_var = tk.BooleanVar(value=self.settings.auto)
        Switch(row, "Enviar automaticamente", self.auto_var, self._toggle_auto,
               bg=C["surface"]).pack(side="right", padx=(0, P(14)))
        if self._open_settings:
            FlatButton(row, "Definições do Ballchasing", self._open_settings, kind="subtle").pack(
                side="right", padx=(0, P(10)))

        # aviso: replays sem dono (a tua conta tem outro nome no jogo)
        self.claim_card = Card(self, bg=C["surface2"], radius=14, pad=12, border=C["warn"])
        self.claim_lbl = tk.Label(self.claim_card.body, text="", bg=C["surface2"], fg=C["text"],
                                  font=F(9), justify="left", anchor="w", wraplength=P(700))
        self.claim_lbl.pack(side="left", fill="x", expand=True)
        FlatButton(self.claim_card.body, "Não é minha", self._ignore_claim, kind="subtle").pack(
            side="right", padx=(P(8), 0))
        self.claim_dd = Dropdown(self.claim_card.body, self._claim_items, self._do_claim,
                                 text="Sim, associar a")
        self.claim_dd.pack(side="right")
        self._claim = None
        self._ignored = set()

        # medias
        self.avg_card = Card(self, bg=C["surface"], radius=14, pad=12)
        self.avg_card.pack(fill="x", pady=(P(10), 0))
        hdr = tk.Frame(self.avg_card.body, bg=C["surface"])
        hdr.pack(fill="x", pady=(0, P(6)))
        caption(hdr, "As tuas médias nos replays", color=C["accent"], bg=C["surface"]).pack(side="left")
        self.count_lbl = tk.Label(hdr, text="", bg=C["surface"], fg=C["muted"], font=F(8))
        self.count_lbl.pack(side="right")
        grid = tk.Frame(self.avg_card.body, bg=C["surface"])
        grid.pack(fill="x")
        self.tiles = {}
        spec = [("poss", "Posse"), ("bpm", "Boost/min"), ("zero", "Sem boost"), ("full", "Boost cheio"),
                ("behind", "Atrás da bola"), ("dfn", "Terço defensivo"), ("off", "Terço ofensivo"),
                ("speed", "Velocidade")]
        for i, (k, cap) in enumerate(spec):
            grid.grid_columnconfigure(i, weight=1, uniform="av")
            t = StatTile(grid, cap, big=False, bg=C["surface"])
            t.grid(row=0, column=i, sticky="w")
            self.tiles[k] = t

        # lista
        tbl = Card(self, bg=C["surface"], radius=14, pad=10, fit=False)
        tbl.pack(fill="both", expand=True, pady=(P(10), 0))
        self.compare = CompareStrip(tbl.body, C["surface"])
        self.compare.pack(side="bottom", fill="x")
        wrap = tk.Frame(tbl.body, bg=C["surface"])
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in COLS], show="headings",
                                 style="RL.Treeview")
        for key, title, width, anchor in COLS:
            self.tree.heading(key, text=tr(title), anchor=anchor if anchor != "e" else "e")
            self.tree.column(key, width=P(width), anchor=anchor, stretch=key in ("date", "playlist"))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview,
                           style="RL.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("win", foreground=C["good"])
        self.tree.tag_configure("loss", foreground=C["bad"])
        self.tree.bind("<Double-1>", self._open_link)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.empty = tk.Label(tbl.body, text="Ainda não há replays analisados.\n"
                                             "Guarda replays no jogo (ou usa o BakkesMod) e carrega em "
                                             "'Sincronizar agora'.",
                              bg=C["surface"], fg=C["dim"], font=F(9), justify="center")

    # ---- definicoes --------------------------------------------------------

    def _toggle_auto(self):
        self.settings.auto = bool(self.auto_var.get())
        if self.settings.auto and not self.settings.token:
            self._set_status(tr("Cola primeiro a chave da API em Definições."), C["warn"])
            self.auto_var.set(False)
            self.settings.auto = False
        self.settings.save()
        self.sync.set_auto(self.settings.auto)

    # ---- acoes -------------------------------------------------------------

    def _set_status(self, text, color=None):
        self.status.config(text=text, fg=color or C["muted"])

    def _sync_now(self):
        if not self.settings.token:
            self._set_status(tr("Cola primeiro a chave da API em Definições."), C["warn"])
            return
        self._set_status(tr("A procurar replays novos…"))
        self.sync.sync_async()

    def _claim_items(self):
        return [(p.display(), p.id) for p in self.profiles.profiles]

    def _ignore_claim(self):
        if self._claim:
            self._ignored.add(f"{self._claim['platform']}:{self._claim['pid']}")
        self._update_claim()

    def _do_claim(self, profile_id):
        c = self._claim
        if not c:
            return
        self.profiles.add_replay_id(profile_id, f"{c['platform']}:{c['pid']}")
        self._set_status("A associar a conta e a recalcular os replays…")
        self._claim = None
        self.claim_card.pack_forget()
        self.sync.rematch_async()

    def _update_claim(self):
        claimed = {x for p in self.profiles.profiles for x in p.replay_ids}
        cands = [c for c in self.store.top_candidates(claimed)
                 if f"{c['platform']}:{c['pid']}" not in self._ignored]
        self._claim = cands[0] if cands else None
        if not self._claim:
            self.claim_card.pack_forget()
            return
        c = self._claim
        self.claim_lbl.config(text=tr(
            "Há replays enviados que não pertencem a nenhum dos teus perfis. A conta "
            "«{name}» ({platform}) aparece em {n} deles: és tu? "
            "O nome no replay pode ser diferente do nome do perfil.",
            name=c['name'], platform=c['platform'], n=c['n']))
        self.claim_card.pack(fill="x", pady=(P(10), 0), before=self.avg_card)

    def _open_link(self, _e=None):
        sel = self.tree.selection()
        if sel and self._links.get(sel[0]):
            webbrowser.open(self._links[sel[0]])

    def _poll(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "status":
                    self._set_status(payload)
                elif kind == "status_ok":
                    self._set_status(payload, C["good"])
                elif kind == "status_err":
                    self._set_status(payload, C["bad"])
                elif kind == "data":
                    self.refresh()
        except queue.Empty:
            pass
        self.after(300, self._poll)

    # ---- dados -------------------------------------------------------------

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        r = self._rows.get(sel[0]) if sel else None
        items = compare_replay(r["data"], self._avg) if r else []
        if not items:
            self.compare.clear()
            return
        self.compare.show(tr("Este replay vs a tua média nos replays"), items)

    def refresh(self):
        self._update_claim()
        pid = self.profiles.active().id
        rows = self.store.replays(pid, limit=300)
        self.count_lbl.config(text=tr("{n} replay(s) — perfil ativo", n=len(rows)))
        avg = replay_averages(rows)
        self.tiles["poss"].set(_fmt(avg.get("possession_pct"), "%"))
        self.tiles["bpm"].set(_fmt(avg.get("bpm")))
        self.tiles["zero"].set(_fmt(avg.get("percent_zero_boost"), "%"))
        self.tiles["full"].set(_fmt(avg.get("percent_full_boost"), "%"))
        self.tiles["behind"].set(_fmt(avg.get("percent_behind_ball"), "%"))
        self.tiles["dfn"].set(_fmt(avg.get("percent_defensive_third"), "%"))
        self.tiles["off"].set(_fmt(avg.get("percent_offensive_third"), "%"))
        self.tiles["speed"].set(_fmt(avg.get("avg_speed")))

        for i in self.tree.get_children():
            self.tree.delete(i)
        self._links.clear()
        self._rows, self._avg = {}, avg
        self.compare.clear()
        if rows:
            self.empty.pack_forget()
        else:
            self.empty.pack(pady=P(14))
        for r in rows:
            d = r["data"]
            won = r.get("won")
            res = "-" if won is None else (tr("Vitória") if won else tr("Derrota"))
            iid = self.tree.insert("", "end", tags=(() if won is None else ("win" if won else "loss",)),
                                   values=((r["date"] or "")[:16].replace("T", " "),
                                           r["playlist"] or "-", res,
                                           _fmt(d.get("possession_pct"), "%"), _fmt(d.get("bpm")),
                                           _fmt(d.get("percent_zero_boost"), "%"),
                                           _fmt(d.get("percent_behind_ball"), "%"),
                                           tr("abrir") if r.get("link") else ""))
            self._links[iid] = r.get("link")
            self._rows[iid] = r
