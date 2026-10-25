#!/usr/bin/env python3
"""
Rocket League Live Dashboard (Tkinter)
=======================================

Liga-se a Stats API local do Rocket League e mostra placar, stats por
jogador, feed de eventos, totais da sessao (por perfil e por modo) e o
historico de partidas -- tudo na mesma janela (separadores Ao vivo /
Historico).
"""

import configparser
import os
import queue
import subprocess
import sys
import tkinter as tk

import ai_coach
import appsettings
import i18n
import maintenance
import tray as tray_mod
import stats_api_config
from i18n import tr
import rlapi
import threading
import time
from mmr_ui import MMRBox
from history import MODE_LABELS, MODES, MatchHistory
from coach_page import CoachPage
from history_page import HistoryPage
from replays_page import ReplaysPage
from settings_page import SettingsPage
from profiles import PLATFORMS, ProfileManager, platform_matches
from tracker_core import TrackerCore
from ui_kit import (setup_fonts, hgrad, Bar, Card, Dropdown, FlatButton, Pill, Segmented, StatTile, SideNav, PageBanner,
                    Switch, C, F, P, caption, make_entry, set_scale)

if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(_BASE_DIR, "config.ini")

STATUS_LABELS = {
    "connecting": "A ligar...",
    "error":      "Sem ligação ao jogo",
    "waiting":    "Em espera por uma partida",
    "in_match":   "Em partida",
}
STATUS_COLORS = {
    "connecting": C["warn"],
    "error":      C["bad"],
    "waiting":    C["accent"],
    "in_match":   C["good"],
}

TABS = ["Ao vivo", "Histórico", "Treinador", "Replays", "Definições"]


class SharedName:
    def __init__(self):
        self.value = ""


# ── Cartao de jogador ────────────────────────────────────────────────────────

class PlayerCard(tk.Frame):
    def __init__(self, master, team_color):
        super().__init__(master, bg=C["surface2"], highlightthickness=1,
                         highlightbackground=C["border"])
        self._tc = team_color
        tk.Frame(self, bg=team_color, width=P(4)).pack(side="left", fill="y")
        body = tk.Frame(self, bg=C["surface2"])
        body.pack(side="left", fill="both", expand=True, padx=P(12), pady=P(9))
        bg = C["surface2"]

        top = tk.Frame(body, bg=bg)
        top.pack(fill="x")
        self.name_lbl = tk.Label(top, bg=bg, fg=C["text"], font=F(11, "bold"), anchor="w")
        self.name_lbl.pack(side="left")
        self.super_badge = tk.Label(top, text="SUPERSÓNICO", bg=C["warn"], fg=C["bg"],
                                    font=F(7, "bold"), padx=P(5))
        self._super_on = False
        self.score_lbl = tk.Label(top, bg=bg, fg=C["warn"], font=F(14, "bold"))
        self.score_lbl.pack(side="right")

        stats = tk.Frame(body, bg=bg)
        stats.pack(fill="x", pady=(P(5), P(6)))
        self.stat_vals = {}
        for key, cap in (("g", "G"), ("a", "A"), ("sv", "SV"), ("sh", "SH")):
            cell = tk.Frame(stats, bg=bg)
            cell.pack(side="left", padx=(0, P(14)))
            tk.Label(cell, text=cap, bg=bg, fg=C["muted"], font=F(7, "bold")).pack(side="left")
            v = tk.Label(cell, text="0", bg=bg, fg=C["text"], font=F(10, "bold"))
            v.pack(side="left", padx=(P(4), 0))
            self.stat_vals[key] = v
        self.speed_lbl = tk.Label(stats, bg=bg, fg=C["muted"], font=F(8))
        self.speed_lbl.pack(side="right")

        brow = tk.Frame(body, bg=bg)
        brow.pack(fill="x")
        self.boost_bar = Bar(brow, height=7, bg=bg, track=C["bg"])
        self.boost_bar.pack(side="left", fill="x", expand=True)
        self.boost_lbl = tk.Label(brow, bg=bg, fg=C["muted"], font=F(8), width=5, anchor="e")
        self.boost_lbl.pack(side="right")

    @staticmethod
    def _boost_color(boost):
        if boost >= 70:
            return C["good"]
        if boost >= 30:
            return C["warn"]
        return C["bad"]

    def update_player(self, p, highlight):
        boost = max(0, min(100, int(p.get("Boost", 0) or 0)))
        speed = p.get("Speed", 0)
        self.name_lbl.config(text=p.get("Name", "?"), fg=C["warn"] if highlight else C["text"])
        self.config(highlightbackground=C["accent"] if highlight else C["border"])
        self.score_lbl.config(text=str(p.get("Score", 0)))
        for key, field in (("g", "Goals"), ("a", "Assists"), ("sv", "Saves"), ("sh", "Shots")):
            self.stat_vals[key].config(text=str(p.get(field, 0)))
        self.speed_lbl.config(
            text=f"{round(speed)} km/h" if isinstance(speed, (int, float)) else "")
        self.boost_bar.set([(boost / 100, self._boost_color(boost))])
        self.boost_lbl.config(text=f"{boost}%")
        is_super = bool(p.get("bSupersonic"))
        if is_super and not self._super_on:
            self.super_badge.pack(side="left", padx=(P(8), 0))
            self._super_on = True
        elif not is_super and self._super_on:
            self.super_badge.pack_forget()
            self._super_on = False


class TeamPanel(Card):
    def __init__(self, master, title, color):
        super().__init__(master, bg=C["surface"], radius=14, pad=12, fit=False)
        self.color = color
        self.rows, self.order = {}, []
        hdr = tk.Frame(self.body, bg=C["surface"])
        hdr.pack(fill="x", pady=(0, P(8)))
        dot = tk.Canvas(hdr, width=P(10), height=P(10), bg=C["surface"], highlightthickness=0)
        dot.create_oval(1, 1, P(9), P(9), fill=color, outline="")
        dot.pack(side="left", padx=(0, P(8)))
        caption(hdr, title, color=color, bg=C["surface"], size=9).pack(side="left")
        self.count_lbl = tk.Label(hdr, bg=C["surface"], fg=C["muted"], font=F(8))
        self.count_lbl.pack(side="right")
        self.cards = tk.Frame(self.body, bg=C["surface"])
        self.cards.pack(fill="both", expand=True)
        self.empty_lbl = tk.Label(self.cards, text="Sem jogadores", bg=C["surface"],
                                  fg=C["dim"], font=F(10))


# ── Aplicacao ────────────────────────────────────────────────────────────────

class DashboardGUI:
    def __init__(self, root, app_settings=None, single=None):
        self.root = root
        self.single = single
        self.app_settings = app_settings or appsettings.AppSettings()
        i18n.set_language(self.app_settings.language)
        self.PLACEHOLDER = tr("escreve o teu nome...")
        self.profiles = ProfileManager()
        self.history = MatchHistory()
        rlapi.ACTIVE = self.profiles
        self._ui_profile_id = None
        self._shared_name = SharedName()
        self._name_is_placeholder = True
        self.last_players_payload = {"players": [], "game": {}}

        self._events_log = []
        self._last_status = "connecting"
        self._alerted = set()
        self._alert_seeded = False
        self._alert = None            # (texto, cor) do aviso visivel
        self._last_snap = {}
        self._mmr_dirty = False
        self._mmr_idle_id = None
        self.tray = tray_mod.Tray(tr("Mostrar"), tr("Sair"))
        self.ai_settings = ai_coach.AISettings()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.app_settings.close_to_tray:
            self._set_tray(True)

        self.core = TrackerCore(profiles=self.profiles, history=self.history)
        self.core.set_exclude_bot_matches(self.exclude_bots_var.get())
        self.core.start_background_loop()

        if self.app_settings.compact_start:
            self._toggle_compact()

        self._start_loops()

    def _start_loops(self):
        self._poll_queue()
        self._api_check_loop()
        self._backup_loop()
        self.root.after(8000, self._mmr_session_start)
        self.root.after(60000, self._mmr_tick)

    def _build_ui(self):
        self._init_window()
        self._build_header()
        self._build_nav()
        self._build_footer()
        self._build_content()
        self._build_compact_bar()
        self._layout(False)
        self._sync_autostart_state()
        self._load_active_profile_into_ui()

    def reload_ui(self):
        """Reconstroi a janela com o idioma/escala das definicoes, sem parar o tracker."""
        keep = {"bots": self.exclude_bots_var.get(), "page": self.page}
        for after_id in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            try:
                # ao nivel do Tcl: after_cancel do Tkinter apaga o comando e o
                # destroy() do widget falharia a apagar o mesmo comando.
                self.root.tk.call("after", "cancel", after_id)
            except tk.TclError:
                pass
        for w in self.root.winfo_children():
            w.destroy()
        apply_scale(self.root, self.app_settings)
        i18n.set_language(self.app_settings.language)
        self.PLACEHOLDER = tr("escreve o teu nome...")
        self._name_is_placeholder = True
        self._ui_profile_id = None
        was_tray = self.tray.active()
        self.tray.stop()
        self.tray = tray_mod.Tray(tr("Mostrar"), tr("Sair"))    # menu no novo idioma
        if was_tray:
            self._set_tray(True)
        self._build_ui()
        self.exclude_bots_var.set(keep["bots"])
        # repor o estado visivel
        self._update_status_label(self._last_status)
        if self.last_players_payload.get("players"):
            self._update_state(self.last_players_payload)
        self._update_session(self.core.session.snapshot())
        for ev in self._events_log:
            self._write_event(ev)
        if self._alert:
            self._show_alert(*self._alert, beep=False)
        self.tabs.select(keep["page"], True)
        self._api_check()
        self._start_loops()

    # ── Janela ────────────────────────────────────────────────────────────────

    def _init_window(self):
        self.root.title("RL Live Dashboard")
        self.root.configure(bg=C["bg"])
        self.normal_geometry = f"{P(1200)}x{P(800)}"
        self.root.geometry(self.normal_geometry)
        self.root.minsize(P(1020), P(680))
        self.compact_var = tk.BooleanVar(value=False)
        self.exclude_bots_var = tk.BooleanVar(value=True)
        self.autostart_var = tk.BooleanVar(value=False)
        self.auto_switch_var = tk.BooleanVar(value=True)

    def _build_header(self):
        self.header = tk.Frame(self.root, bg=C["surface"])
        self.header.pack(fill="x")
        inner = tk.Frame(self.header, bg=C["surface"])
        inner.pack(fill="x", padx=P(20), pady=P(12))
        inner.grid_columnconfigure(0, weight=1, uniform="h")
        inner.grid_columnconfigure(2, weight=1, uniform="h")

        left = tk.Frame(inner, bg=C["surface"])
        left.grid(row=0, column=0, sticky="w")
        tk.Label(left, text="RL Live", bg=C["surface"], fg=C["text"],
                 font=F(17, "bold")).pack(anchor="w")
        tk.Label(left, text="Session tracker", bg=C["surface"], fg=C["muted"],
                 font=F(8)).pack(anchor="w")

        mid = tk.Frame(inner, bg=C["surface"])
        mid.grid(row=0, column=1)
        sb = tk.Frame(mid, bg=C["surface"])
        sb.pack()
        tk.Label(sb, text="AZUL", bg=C["surface"], fg=C["blue"], font=F(8, "bold")).pack(side="left", padx=(0, P(12)))
        self.blue_score_lbl = tk.Label(sb, text="-", bg=C["surface"], fg=C["dim"], font=F(30, "bold"), width=2)
        self.blue_score_lbl.pack(side="left")
        tk.Label(sb, text=":", bg=C["surface"], fg=C["dim"], font=F(22, "bold")).pack(side="left", padx=P(6))
        self.orange_score_lbl = tk.Label(sb, text="-", bg=C["surface"], fg=C["dim"], font=F(30, "bold"), width=2)
        self.orange_score_lbl.pack(side="left")
        tk.Label(sb, text="LARANJA", bg=C["surface"], fg=C["orange"], font=F(8, "bold")).pack(side="left", padx=(P(12), 0))
        self.match_lbl = tk.Label(mid, text="Sem partida em curso", bg=C["surface"],
                                  fg=C["muted"], font=F(9))
        self.match_lbl.pack()

        right = tk.Frame(inner, bg=C["surface"])
        right.grid(row=0, column=2, sticky="e")
        self.compact_btn = FlatButton(right, "Modo compacto", self._toggle_compact, kind="ghost")
        self.compact_btn.pack(side="right", padx=(P(10), 0))
        self.status_pill = Pill(right)
        self.status_pill.pack(side="right")
        self.status_pill.set(STATUS_LABELS["connecting"], STATUS_COLORS["connecting"])

        self.header_rule = tk.Canvas(self.root, height=2, bg=C["border"], highlightthickness=0, bd=0)
        self.header_rule.pack(fill="x")
        self.header_rule.bind("<Configure>", lambda e: (
            self.header_rule.delete("all"),
            hgrad(self.header_rule, 0, 0, e.width, 2, C["accent"], C["border"])))
        self.alert_bar = tk.Frame(self.root, bg=C["surface2"])
        self.alert_lbl = tk.Label(self.alert_bar, text="", bg=C["surface2"], fg=C["text"],
                                  font=F(10, "bold"), anchor="w", justify="left")
        self.alert_lbl.pack(side="left", padx=(P(20), P(10)), pady=P(8))
        FlatButton(self.alert_bar, "OK", self._hide_alert, kind="ghost", py=3, px=12).pack(
            side="right", padx=(0, P(20)))

    def _build_nav(self):
        self.tabs = SideNav(self.root, TABS, ["live", "history", "coach", "replays", "settings"],
                            TABS[0], command=self._show_page)
        self.nav = self.tabs

    def _build_footer(self):
        self.footer = tk.Frame(self.root, bg=C["surface"])
        tk.Frame(self.footer, bg=C["border"], height=1).pack(fill="x")
        row = tk.Frame(self.footer, bg=C["surface"])
        row.pack(fill="x", padx=P(20), pady=P(8))
        self.api_lbl = tk.Label(row, text="Stats API: a verificar...", bg=C["surface"],
                                fg=C["muted"], font=F(8), anchor="w", justify="left")
        self.api_lbl.pack(side="left")
        Switch(row, "Iniciar com o Windows", self.autostart_var,
               self._on_toggle_autostart, bg=C["surface"]).pack(side="right", padx=(P(18), 0))
        Switch(row, "Ignorar partidas com bots", self.exclude_bots_var,
               self._on_toggle_exclude_bots, bg=C["surface"]).pack(side="right")

    def _build_content(self):
        self.content = tk.Frame(self.root, bg=C["bg"])
        self.banner = PageBanner(self.content)
        self.banner.pack(fill="x", pady=(0, P(8)))
        self.live = tk.Frame(self.content, bg=C["bg"])
        self.history_page = HistoryPage(self.content, self.history, self.profiles)
        self.replays_page = ReplaysPage(self.content, self.profiles, open_settings=self._goto_settings)
        self.coach_page = CoachPage(self.content, self.history, self.profiles, self.replays_page.store,
                                    ai_settings=self.ai_settings, open_settings=self._goto_settings)
        self.settings_page = SettingsPage(self.content, self.app_settings, self.replays_page,
                                          self.ai_settings, on_reload=self.reload_ui,
                                          on_tray=self._set_tray)
        self._build_live(self.live)
        self.live.pack(fill="both", expand=True)
        self.page = "Ao vivo"
        self.banner.set("Ao vivo", self.PAGE_SUBS["Ao vivo"])

    # ── Pagina Ao vivo ────────────────────────────────────────────────────────

    def _build_live(self, parent):
        self._build_session_card(parent)

        grid = tk.Frame(parent, bg=C["bg"])
        grid.pack(fill="both", expand=True, pady=(P(10), 0))
        grid.grid_rowconfigure(0, weight=1)
        grid.grid_columnconfigure(0, weight=3, uniform="col")
        grid.grid_columnconfigure(1, weight=3, uniform="col")
        grid.grid_columnconfigure(2, weight=2, uniform="col")

        self.blue_panel = TeamPanel(grid, "Equipa Azul", C["blue"])
        self.blue_panel.grid(row=0, column=0, sticky="nsew", padx=(0, P(5)))
        self.orange_panel = TeamPanel(grid, "Equipa Laranja", C["orange"])
        self.orange_panel.grid(row=0, column=1, sticky="nsew", padx=P(5))

        ev = Card(grid, bg=C["surface"], radius=14, pad=12, fit=False)
        ev.grid(row=0, column=2, sticky="nsew", padx=(P(5), 0))
        caption(ev.body, "Eventos", bg=C["surface"], size=9).pack(anchor="w", pady=(0, P(8)))
        self.events_text = tk.Text(ev.body, bg=C["surface"], fg=C["text"], font=F(9, "medium"),
                                   wrap="word", relief="flat", bd=0, state="disabled",
                                   highlightthickness=0, cursor="arrow", spacing1=P(2), spacing3=P(2),
                                   width=10)
        self.events_text.pack(fill="both", expand=True)
        self.events_text.tag_config("ts", foreground=C["dim"])
        self.events_text.tag_config("goal", foreground=C["good"])
        self.events_text.tag_config("demo", foreground=C["bad"])
        self.events_text.tag_config("match", foreground=C["accent"])
        self.events_text.tag_config("stat", foreground=C["muted"])
        self.events_text.tag_config("info", foreground=C["text"])

    def _build_session_card(self, parent):
        card = Card(parent, bg=C["surface"], radius=14, pad=16)
        card.pack(fill="x")
        b = card.body

        r1 = tk.Frame(b, bg=C["surface"])
        r1.pack(fill="x")
        caption(r1, "Sessão", color=C["accent"], bg=C["surface"], size=9).pack(side="left", padx=(0, P(14)))
        self.profile_dd = Dropdown(r1, self._profile_items, self._on_profile_menu, text="")
        self.profile_dd.pack(side="left")
        tk.Label(r1, text="Nome no jogo", bg=C["surface"], fg=C["muted"], font=F(9)).pack(
            side="left", padx=(P(16), P(6)))
        self.name_entry = make_entry(r1, width=16)
        self.name_entry.pack(side="left", ipady=P(4))
        self.name_entry.bind("<FocusIn>", self._name_focus_in)
        self.name_entry.bind("<FocusOut>", self._name_focus_out)
        self.name_entry.bind("<KeyRelease>", self._name_changed)
        self.platform_dd = Dropdown(r1, self._platform_items, self._on_select_platform,
                                    text=PLATFORMS["any"])
        self.platform_dd.pack(side="left", padx=(P(8), 0))
        self.name_status_lbl = tk.Label(r1, text="", bg=C["surface"], font=F(9, "bold"))
        self.name_status_lbl.pack(side="left", padx=(P(12), 0))
        FlatButton(r1, "Reiniciar sessão", self._on_reset, kind="ghost").pack(side="right")
        Switch(r1, "Troca automática de perfil", self.auto_switch_var,
               self._on_toggle_auto_switch, bg=C["surface"]).pack(side="right", padx=(0, P(16)))

        tiles = tk.Frame(b, bg=C["surface"])
        tiles.pack(fill="x", pady=(P(14), P(10)))
        self.tiles = {}
        main = (("games", "Jogos"), ("wins", "Vitórias"), ("losses", "Derrotas"),
                ("win_pct", "Win %"), ("streak_text", "Sequência"))
        sub = (("goals", "Golos"), ("assists", "Assist."), ("saves", "Defesas"),
               ("shots", "Remates"), ("score_avg", "Pts / jogo"))
        for key, cap in main:
            t = StatTile(tiles, cap, big=True)
            t.pack(side="left", padx=(0, P(30)))
            self.tiles[key] = t
        tk.Frame(tiles, bg=C["border"], width=1).pack(side="left", fill="y", padx=(0, P(30)), pady=P(4))
        for key, cap in sub:
            t = StatTile(tiles, cap, big=False)
            t.pack(side="left", padx=(0, P(26)), pady=(P(6), 0))
            self.tiles[key] = t

        r3 = tk.Frame(b, bg=C["surface"])
        r3.pack(fill="x")
        caption(r3, "Por modo", bg=C["surface"]).pack(side="left", padx=(0, P(12)))
        self.modes_row = tk.Frame(r3, bg=C["surface"])
        self.modes_row.pack(side="left")
        self._render_mode_chips({})

        r4 = tk.Frame(b, bg=C["surface"])
        r4.pack(fill="x", pady=(P(10), 0))
        caption(r4, "MMR", bg=C["surface"]).pack(side="left", padx=(0, P(12)))
        self.mmr_box = MMRBox(r4, self.history, self.profiles, C["surface"])
        self.mmr_box.pack(side="left")
        self.mmr_box.on_sync = lambda: setattr(self, "_mmr_dirty", False)

    def _render_mode_chips(self, by_mode):
        for w in self.modes_row.winfo_children():
            w.destroy()
        shown = [m for m in MODES if m in by_mode]
        if not shown:
            tk.Label(self.modes_row, text="ainda sem partidas contadas", bg=C["surface"],
                     fg=C["dim"], font=F(9)).pack(side="left")
            return
        for m in shown:
            w_, l_ = by_mode[m]
            chip = tk.Frame(self.modes_row, bg=C["surface2"], padx=P(10), pady=P(4))
            chip.pack(side="left", padx=(0, P(8)))
            tk.Label(chip, text=MODE_LABELS[m], bg=C["surface2"], fg=C["text"],
                     font=F(9, "bold")).pack(side="left")
            tk.Label(chip, text=f"  {w_}", bg=C["surface2"], fg=C["good"], font=F(9, "bold")).pack(side="left")
            tk.Label(chip, text=" - ", bg=C["surface2"], fg=C["muted"], font=F(9)).pack(side="left")
            tk.Label(chip, text=str(l_), bg=C["surface2"], fg=C["bad"], font=F(9, "bold")).pack(side="left")

    # ── Barra compacta ────────────────────────────────────────────────────────

    def _build_compact_bar(self):
        self.compact_bar = tk.Frame(self.root, bg=C["bg"])
        card = Card(self.compact_bar, bg=C["surface"], radius=12, pad=10)
        card.pack(fill="x", padx=P(12), pady=P(10))
        row = tk.Frame(card.body, bg=C["surface"])
        row.pack(fill="x")
        self.compact_profile_lbl = tk.Label(row, text="", bg=C["surface"], fg=C["accent"],
                                            font=F(9, "bold"))
        self.compact_profile_lbl.pack(side="left", padx=(0, P(16)))
        self.compact_tiles = {}
        for key, cap in (("wins", "V"), ("losses", "D"), ("streak_text", "Seq."), ("win_pct", "Win %")):
            t = StatTile(row, cap, big=False)
            t.pack(side="left", padx=(0, P(20)))
            self.compact_tiles[key] = t
        FlatButton(row, "Reset", self._on_reset, kind="ghost", size=8).pack(side="right")

    # ── Layout / navegacao ────────────────────────────────────────────────────

    def _layout(self, compact):
        for w in (self.nav, self.footer, self.content, self.compact_bar):
            w.pack_forget()
        if compact:
            self.compact_bar.pack(fill="x")
            self.root.minsize(P(560), P(130))
            self.root.after(50, lambda: self.root.geometry(""))
        else:
            self.footer.pack(side="bottom", fill="x")
            self.nav.pack(side="left", fill="y")
            self.content.pack(side="left", fill="both", expand=True, padx=P(20), pady=P(14))
            self.root.minsize(P(1020), P(680))
            self.root.geometry(self.normal_geometry)

    def _toggle_compact(self):
        compact = not self.compact_var.get()
        self.compact_var.set(compact)
        self.compact_btn.config(text="Expandir" if compact else "Modo compacto")
        self._layout(compact)

    def _goto_settings(self):
        self.tabs.select("Definições", True)

    PAGE_SUBS = {
        "Ao vivo": "A partida em curso e a tua sessão",
        "Histórico": "A evolução das tuas partidas",
        "Treinador": "Dicas com base nos teus dados",
        "Replays": "Análise dos teus replays",
        "Definições": "Idioma, avisos, dados e cópias",
    }

    def _show_page(self, name):
        self.page = name
        self.banner.set(name, self.PAGE_SUBS.get(name, ""))
        self.live.pack_forget()
        self.history_page.pack_forget()
        self.coach_page.pack_forget()
        self.replays_page.pack_forget()
        self.settings_page.pack_forget()
        if name == "Histórico":
            self.history_page.pack(fill="both", expand=True)
            self.history_page.refresh()
        elif name == "Treinador":
            self.coach_page.pack(fill="both", expand=True)
            self.coach_page.refresh()
        elif name == "Replays":
            self.replays_page.pack(fill="both", expand=True)
            self.replays_page.refresh()
        elif name == "Definições":
            self.settings_page.pack(fill="both", expand=True)
            self.settings_page.refresh()
        else:
            self.live.pack(fill="both", expand=True)

    # ── Perfis ────────────────────────────────────────────────────────────────

    def _profile_items(self):
        items = [(p.display(), ("sel", p.id)) for p in list(self.profiles.profiles)]
        items += [(None, None), ("+  Novo perfil", ("new", None)),
                  ("Apagar perfil atual", ("del", None))]
        return items

    def _platform_items(self):
        return [(label, key) for key, label in PLATFORMS.items()]

    def _on_profile_menu(self, value):
        action, pid = value
        if action == "sel":
            self._on_select_profile(pid)
        elif action == "new":
            self._on_add_profile()
        elif action == "del":
            self._on_delete_profile()

    def _load_active_profile_into_ui(self):
        """Poe o perfil ativo na GUI (nome, plataforma, menus)."""
        prof = self.profiles.active()
        self._ui_profile_id = prof.id
        if hasattr(self, "mmr_box"):
            self.mmr_box.refresh()
        self.name_entry.delete(0, "end")
        if prof.name:
            self.name_entry.insert(0, prof.name)
            self.name_entry.config(fg=C["text"])
            self._name_is_placeholder = False
        elif self.root.focus_get() is self.name_entry:
            # O utilizador esta' a escrever neste campo -- deixa-o vazio
            # (o placeholder voltaria a aparecer ao perder o foco).
            self.name_entry.config(fg=C["text"])
            self._name_is_placeholder = False
        else:
            self.name_entry.insert(0, self.PLACEHOLDER)
            self.name_entry.config(fg=C["muted"])
            self._name_is_placeholder = True
        self._shared_name.value = prof.name
        self.platform_dd.set_text(PLATFORMS[prof.platform])
        self.auto_switch_var.set(self.profiles.auto_switch)
        self._refresh_profile_labels()

    def _refresh_profile_labels(self):
        prof = self.profiles.active()
        self.profile_dd.set_text(prof.display())
        self.compact_profile_lbl.config(text=prof.display())

    def _name_focus_in(self, _e=None):
        if self._name_is_placeholder:
            self.name_entry.delete(0, "end")
            self.name_entry.config(fg=C["text"])
            self._name_is_placeholder = False

    def _name_focus_out(self, _e=None):
        if not self.name_entry.get().strip():
            self.name_entry.delete(0, "end")
            self.name_entry.insert(0, self.PLACEHOLDER)
            self.name_entry.config(fg=C["muted"])
            self._name_is_placeholder = True
            self._shared_name.value = ""
            self._update_name_status()
            self._save_profile_name("")

    def _name_changed(self, _e=None):
        if self._name_is_placeholder:
            raw = self.name_entry.get()
            if raw != self.PLACEHOLDER:
                # texto escrito por cima do placeholder: limpa-o
                self.name_entry.delete(0, "end")
                self.name_entry.insert(0, raw.replace(self.PLACEHOLDER, "", 1))
                self.name_entry.config(fg=C["text"])
                self._name_is_placeholder = False
        if not self._name_is_placeholder:
            val = self.name_entry.get().strip()
            self._shared_name.value = val
            self._update_name_status()
            self._save_profile_name(val)

    def _save_profile_name(self, name):
        self.profiles.update(self.profiles.active().id, name=name)
        self._refresh_profile_labels()
        self._check_save_error()

    def _check_save_error(self):
        """Avisa (uma vez) se o profiles.json nao pode ser gravado."""
        err = self.profiles.last_error
        if err and not getattr(self, "_save_err_shown", False):
            self._save_err_shown = True
            from tkinter import messagebox
            messagebox.showerror(
                tr("Perfis"), tr("Não consegui gravar os perfis:\n{err}\n\nMove a app para uma pasta "
                                 "onde possas escrever (ex.: fora do OneDrive / Program Files).", err=err))

    def _on_select_profile(self, pid):
        if pid == self.profiles.active().id:
            return
        self.core.switch_profile(pid)
        self._load_active_profile_into_ui()
        self._render_players()
        self._profile_changed()

    def _on_select_platform(self, key):
        self.profiles.update(self.profiles.active().id, platform=key)
        self.platform_dd.set_text(PLATFORMS[key])
        self._refresh_profile_labels()
        self._render_players()

    def _on_add_profile(self):
        prof = self.profiles.add("", "any")
        self.core.switch_profile(prof.id)
        self._load_active_profile_into_ui()
        self._render_players()
        self._profile_changed()
        self.name_entry.focus_set()
        self._check_save_error()

    def _on_delete_profile(self):
        from tkinter import messagebox
        if len(self.profiles.profiles) <= 1:
            messagebox.showinfo(tr("Perfis"), tr("Tem de existir pelo menos um perfil."))
            return
        prof = self.profiles.active()
        if not messagebox.askyesno(
                tr("Apagar perfil"),
                tr("Apagar o perfil '{name}' e a sua sessão?", name=prof.display())):
            return
        new_id = self.profiles.delete(prof.id)
        self.core.sessions.pop(prof.id, None)
        self.core.switch_profile(new_id)
        self._load_active_profile_into_ui()
        self._render_players()
        self._profile_changed()

    def _profile_changed(self):
        if self.page == "Histórico":
            self.history_page.refresh()
        elif self.page == "Treinador":
            self.coach_page.refresh()
        elif self.page == "Replays":
            self.replays_page.refresh()

    def _on_toggle_auto_switch(self):
        self.profiles.set_auto_switch(self.auto_switch_var.get())

    # ── Polling ───────────────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.core.out_queue.get_nowait()
                if kind == "state":
                    self._update_state(payload)
                elif kind == "event":
                    self._update_events(payload)
                elif kind == "session":
                    self._update_session(payload)
                elif kind == "status":
                    self._update_status_label(payload)
                elif kind == "history":
                    if self.page == "Histórico":
                        self.history_page.refresh()
                    elif self.page == "Treinador":
                        self.coach_page.refresh()
                elif kind == "profile":
                    # Trocas feitas pela propria GUI ja' atualizaram o campo;
                    # recarregar outra vez apagava o que o utilizador escrevia.
                    if payload != self._ui_profile_id:
                        self._load_active_profile_into_ui()
                        self._render_players()
                        self._profile_changed()
        except queue.Empty:
            pass
        for cmd in self.tray.poll():
            if cmd == "show":
                self._show_window()
            elif cmd == "quit":
                self.quit()
                return
        if self.single and self.single.take_show_request():
            self._show_window()
        self.root.after(100, self._poll_queue)

    def _update_status_label(self, status):
        self._last_status = status
        self.status_pill.set(STATUS_LABELS.get(status, status),
                             STATUS_COLORS.get(status, C["muted"]))

    def _update_state(self, payload):
        self.last_players_payload = payload
        players = payload.get("players", [])
        game = payload.get("game", {})
        status = payload.get("status", "waiting")
        self._update_status_label(status)

        b_score = o_score = "-"
        for t in game.get("Teams", []):
            if t.get("TeamNum") == 0:
                b_score = str(t.get("Score", "-"))
            elif t.get("TeamNum") == 1:
                o_score = str(t.get("Score", "-"))

        if status == "in_match":
            self.blue_score_lbl.config(text=b_score, fg=C["blue"])
            self.orange_score_lbl.config(text=o_score, fg=C["orange"])
            secs = game.get("TimeSeconds")
            clock = f"{int(secs) // 60}:{int(secs) % 60:02d}" if isinstance(secs, (int, float)) else ""
            if game.get("bOverTime"):
                clock = (clock + "  ·  " if clock else "") + tr("Prolongamento")
            self.match_lbl.config(text=clock or "Em partida", fg=C["text"])
        else:
            self.blue_score_lbl.config(text="-", fg=C["dim"])
            self.orange_score_lbl.config(text="-", fg=C["dim"])
            self.match_lbl.config(text="Sem partida em curso", fg=C["muted"])

        self._render_players()

    def _render_players(self):
        players = self.last_players_payload.get("players", [])
        flt = self._shared_name.value.strip().lower()
        self._render_team(self.blue_panel, 0, players, flt)
        self._render_team(self.orange_panel, 1, players, flt)
        self._update_name_status()

    def _render_team(self, panel, team_num, players, flt):
        team_players = [p for p in players if p.get("TeamNum") == team_num]
        n_pl = len(team_players)
        panel.count_lbl.config(text=(tr("{n} jogador", n=n_pl) if n_pl == 1 else
                                     tr("{n} jogadores", n=n_pl)) if n_pl else "")
        if not team_players:
            for row in panel.rows.values():
                row.destroy()
            panel.rows.clear()
            panel.order = []
            panel.empty_lbl.pack(pady=P(30))
            return
        panel.empty_lbl.pack_forget()

        keys = []
        for p in team_players:
            key = p.get("Name", "?")
            keys.append(key)
            if key not in panel.rows:
                panel.rows[key] = PlayerCard(panel.cards, panel.color)
            panel.rows[key].update_player(p, bool(flt) and flt in key.lower())
        for key in list(panel.rows):
            if key not in keys:
                panel.rows.pop(key).destroy()
        if keys != panel.order:
            for key in keys:
                panel.rows[key].pack_forget()
            for key in keys:
                panel.rows[key].pack(fill="x", pady=(0, P(8)))
            panel.order = keys

    def _update_name_status(self):
        name = self._shared_name.value.strip()
        players = self.last_players_payload.get("players", [])
        if not name or not players:
            self.name_status_lbl.config(text="")
            return
        plat = self.profiles.active().platform
        found = any(
            platform_matches(plat, p.get("PrimaryId")) and (
                name.lower() in p.get("Name", "").lower() or
                p.get("Name", "").lower() in name.lower())
            for p in players
        )
        self.name_status_lbl.config(
            text="● encontrado" if found else "● não encontrado",
            fg=C["good"] if found else C["bad"])

    def _update_events(self, ev):
        self._events_log = (self._events_log + [ev])[-300:]
        self._write_event(ev)

    def _write_event(self, ev):
        tag = ev.get("kind", "info")
        t = self.events_text
        t.config(state="normal")
        t.insert("end", ev.get("ts", "") + "  ", "ts")
        t.insert("end", ev.get("text", "") + "\n", tag)
        t.see("end")
        t.config(state="disabled")

    def _update_session(self, snap):
        games = snap.get("games", 0)
        prev = getattr(self, "_last_games", None)
        self._last_games = games
        if prev is not None and games > prev:
            self._mmr_game_played()
        wins = snap.get("wins", 0)
        losses = snap.get("losses", 0)
        streak = snap.get("streak_text", "-")
        win_pct = f"{100 * wins / games:.0f}%" if games else "-"
        pct_col = None
        if games:
            pct = 100 * wins / games
            pct_col = C["good"] if pct >= 55 else (C["bad"] if pct < 45 else C["text"])
        streak_col = (C["good"] if streak.startswith("+") else
                      C["bad"] if len(streak) > 1 and streak.startswith("-") else C["muted"])

        values = {
            "games": (str(games), None),
            "wins": (str(wins), C["good"] if wins else C["muted"]),
            "losses": (str(losses), C["bad"] if losses else C["muted"]),
            "win_pct": (win_pct, pct_col or C["muted"]),
            "streak_text": (streak, streak_col),
            "goals": (str(snap.get("goals", 0)), None),
            "assists": (str(snap.get("assists", 0)), None),
            "saves": (str(snap.get("saves", 0)), None),
            "shots": (str(snap.get("shots", 0)), None),
            "score_avg": (str(snap.get("score_avg", "-")), C["accent"]),
        }
        for key, (text, color) in values.items():
            self.tiles[key].set(text, color)
        for key, t in self.compact_tiles.items():
            t.set(*values[key])
        self._render_mode_chips(snap.get("by_mode", {}))
        self._last_snap = snap
        self._update_tray_title()
        self._check_goals(snap)

    # ── Stats API (DefaultStatsAPI.ini) ────────────────────────────────────────
    # Um update do jogo (ou "verificar ficheiros") repoe o .ini original e
    # apaga a secao que ativa a Stats API. Verifica periodicamente e repara.

    @staticmethod
    def _configured_install_dir():
        try:
            parser = configparser.ConfigParser()
            parser.read(CONFIG_PATH, encoding="utf-8")
            return parser.get("game", "install_dir", fallback="").strip() or None
        except (configparser.Error, OSError):
            return None

    def _api_check_loop(self):
        # Durante uma partida o jogo ja' leu o ficheiro -- nao vale a pena.
        if self.core.status != "in_match":
            self._api_check()
        self.root.after(30000, self._api_check_loop)

    def _set_api(self, text, color):
        self.api_lbl.config(text=text, fg=color)

    def _api_check(self):
        try:
            extra = self._configured_install_dir()
            state, _paths = stats_api_config.check(extra)
            if state == stats_api_config.OK:
                if getattr(self, "_api_just_fixed", False):
                    return  # mantem a mensagem "reparada" visivel
                self._set_api("Stats API ativada no ficheiro do jogo", C["muted"])
            elif state == stats_api_config.NOT_FOUND:
                self._set_api("Stats API: não encontrei o DefaultStatsAPI.ini do Rocket League "
                              "(define [game] install_dir no config.ini)", C["muted"])
            else:
                fixed, errors = stats_api_config.repair(extra)
                if errors:
                    self._set_api(tr("Stats API desativada e não consegui reparar: {err}", err=errors[0][1]),
                                  C["bad"])
                elif fixed:
                    self._api_just_fixed = True
                    self._set_api("Stats API estava desativada (update do jogo?) -- reparada. "
                                  "Fecha e volta a abrir o Rocket League.", C["warn"])
        except Exception as e:  # nunca deixar isto rebentar a GUI
            self._set_api(tr("Stats API: erro na verificação ({err})", err=e), C["muted"])

    # ── Acoes ─────────────────────────────────────────────────────────────────

    def _on_reset(self):
        self.core.reset_session()
        if self._mmr_dirty and self._mmr_auto_ok() and hasattr(self, "mmr_box"):
            self._mmr_dirty = False
            self.mmr_box.refresh_online(silent=True)       # fim da sessao anterior

    # ── MMR automatico: 1 pedido no inicio, 1 no fim da sessao ───────────────

    MMR_IDLE_MS = 10 * 60 * 1000

    @staticmethod
    def _mmr_auto_ok():
        st = rlapi.SETTINGS
        return bool(st.api_key and st.auto and st.left_today() > 0)

    def _mmr_session_start(self):
        if self._mmr_auto_ok() and hasattr(self, "mmr_box"):
            self.mmr_box.refresh_online(silent=True)

    def _mmr_tick(self):
        """Consulta periodica durante a sessao (so' se escolheste um intervalo e houve jogos)."""
        try:
            st = rlapi.SETTINGS
            if (st.interval and self._mmr_dirty and self._mmr_auto_ok() and hasattr(self, "mmr_box")
                    and time.time() - rlapi.LAST_SYNC >= st.interval * 60):
                self._mmr_dirty = False
                self.mmr_box.refresh_online(silent=True)
        finally:
            self.root.after(60000, self._mmr_tick)

    def _mmr_game_played(self):
        self._mmr_dirty = True
        if self._mmr_idle_id:
            try:
                self.root.after_cancel(self._mmr_idle_id)
            except tk.TclError:
                pass
        self._mmr_idle_id = self.root.after(self.MMR_IDLE_MS, self._mmr_session_end)

    def _mmr_session_end(self):
        self._mmr_idle_id = None
        if self._mmr_dirty and self._mmr_auto_ok() and hasattr(self, "mmr_box"):
            self._mmr_dirty = False
            self.mmr_box.refresh_online(silent=True)

    def _mmr_final_sync(self):
        """Ao fechar a app com jogos por registar: 1 consulta, no maximo 5 s."""
        if not (self._mmr_dirty and self._mmr_auto_ok()):
            return
        prof = self.profiles.active()

        def work():
            try:
                rlapi.refresh_mmr(self.history, prof, rlapi.SETTINGS)
            except Exception:
                pass
        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(5)

    # ── Avisos da sessao (tilt stop / objetivo) ─────────────────────────────

    def _show_alert(self, text, color, beep=True):
        self._alert = (text, color)
        self.alert_lbl.config(text=text, fg=color)
        self.alert_bar.pack(fill="x", after=self.header_rule)
        if beep:
            self._beep()

    def _hide_alert(self):
        self._alert = None
        self.alert_bar.pack_forget()

    def _beep(self):
        if not self.app_settings.alert_sound:
            return
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except (ImportError, RuntimeError):
            try:
                self.root.bell()
            except tk.TclError:
                pass

    def _check_goals(self, snap):
        """Mostra um aviso ao chegar ao limite de derrotas seguidas ou de vitorias."""
        st = self.app_settings
        games, wins = snap.get("games", 0), snap.get("wins", 0)
        streak = snap.get("streak_text", "-")
        loss_run = int(streak[1:]) if len(streak) > 1 and streak[0] == "-" and streak[1:].isdigit() else 0
        if games == 0:                       # sessao nova
            self._alerted.clear()
            self._alert_seeded = True
            if self._alert:
                self._hide_alert()
            return
        due = []
        if st.stop_losses and loss_run >= st.stop_losses:
            due.append((("loss", loss_run), tr("{n} derrotas seguidas — faz uma pausa antes da próxima partida.",
                                               n=loss_run), C["warn"]))
        if st.goal_wins and wins >= st.goal_wins:
            due.append((("win", st.goal_wins), tr("Chegaste às {n} vitórias nesta sessão — bom momento para fechar.",
                                                  n=st.goal_wins), C["good"]))
        if not loss_run:
            self._alerted = {k for k in self._alerted if k[0] != "loss"}
        for key, text, color in due:
            if key in self._alerted:
                continue
            self._alerted.add(key)
            if self._alert_seeded:           # no arranque so' registamos, nao avisamos
                self._show_alert(text, color)
        self._alert_seeded = True

    # ── Bandeja, fecho e instancia unica ────────────────────────────────────

    def _set_tray(self, on):
        if on and tray_mod.available():
            self.tray.start()
            self._update_tray_title()
        else:
            self.tray.stop()

    def _update_tray_title(self):
        s = self._last_snap
        if s:
            self.tray.set_title(tr("RL Live — {w}V {l}D  ({s})", w=s.get("wins", 0),
                                   l=s.get("losses", 0), s=s.get("streak_text", "-")))

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def _on_close(self):
        if self.app_settings.close_to_tray and self.tray.active():
            self.root.withdraw()
        else:
            self.quit()

    def quit(self):
        self._mmr_final_sync()
        self.tray.stop()
        if self.single:
            self.single.release()
        self.root.destroy()

    def _backup_loop(self):
        st = self.app_settings
        if st.backup_on and maintenance.backup_due(st.backup_folder()):
            maintenance.run_backup_async(_BASE_DIR, st.backup_folder(), st.backup_keep)
        self.root.after(3600 * 1000, self._backup_loop)

    def _on_toggle_exclude_bots(self):
        self.core.set_exclude_bot_matches(self.exclude_bots_var.get())

    # ── Autostart (Windows) ───────────────────────────────────────────────────

    @staticmethod
    def _startup_lnk():
        startup_dir = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                                   "Start Menu", "Programs", "Startup")
        return os.path.join(startup_dir, "RL-Live-Dashboard.lnk")

    def _on_toggle_autostart(self):
        if self.autostart_var.get():
            self._enable_autostart()
        else:
            self._disable_autostart()

    def _enable_autostart(self):
        target, args = self._autostart_target()
        lnk_path = self._startup_lnk()
        ps_cmd = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$sc = $ws.CreateShortcut('{lnk_path}'); "
            f"$sc.TargetPath = '{target}'; "
            f"$sc.Arguments = '{args}'; "
            f"$sc.WorkingDirectory = '{_BASE_DIR}'; "
            f"$sc.WindowStyle = 1; "
            f"$sc.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                       capture_output=True, timeout=15)

    def _disable_autostart(self):
        try:
            os.remove(self._startup_lnk())
        except FileNotFoundError:
            pass

    def _sync_autostart_state(self):
        self.autostart_var.set(os.path.isfile(self._startup_lnk()))

    @staticmethod
    def _autostart_target():
        if getattr(sys, "frozen", False):
            return sys.executable, ""
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.isfile(pyw):
            pyw = sys.executable
        return pyw, os.path.abspath(__file__)


def _enable_dpi_awareness():
    """Texto nitido em ecras com escala 125/150/200% (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def apply_scale(root, settings):
    """Aplica a escala das definicoes (auto = a do ecra)."""
    if not hasattr(root, "_rl_auto_scaling"):
        root._rl_auto_scaling = float(root.tk.call("tk", "scaling"))
    factor = settings.scale_value()
    if factor is None:
        root.tk.call("tk", "scaling", root._rl_auto_scaling)
        factor = root._rl_auto_scaling * 72.0 / 96.0
    else:
        root.tk.call("tk", "scaling", factor * 96.0 / 72.0)
    set_scale(factor)


def main():
    _enable_dpi_awareness()
    root = tk.Tk()
    settings = appsettings.AppSettings()
    single = maintenance.SingleInstance()
    if not single.acquire():
        root.withdraw()
        i18n.set_language(settings.language)
        from tkinter import messagebox
        messagebox.showinfo("RL Live Dashboard",
                            tr("A app já está aberta (pode estar na bandeja do sistema)."))
        root.destroy()
        return
    setup_fonts(root)
    apply_scale(root, settings)
    DashboardGUI(root, settings, single=single)
    root.mainloop()


if __name__ == "__main__":
    main()
