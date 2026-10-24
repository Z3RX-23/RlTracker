"""
settings_page.py

Separador "Definições": idioma e aparencia, Ballchasing (chave, pastas),
servico de IA (chave, modelo, idioma da resposta) e gestao dos ficheiros
de dados.
"""

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import ai_coach
import appsettings
import maintenance
import tray as tray_mod
from maintenance import DATA_FILES
from ballchasing import (SINCE_OPTIONS, VISIBILITIES, VISIBILITY_LABELS, BallchasingError, Client)
from i18n import LANGUAGES, tr
from ui_kit import Card, Dropdown, FlatButton, Segmented, Switch, Tabs, C, F, P, caption, make_entry

SCALE_LABELS = {"auto": "Auto", "100%": "100%", "125%": "125%", "150%": "150%",
                "175%": "175%", "200%": "200%"}



def _card(parent, title):
    card = Card(parent, bg=C["surface"], radius=14, pad=14)
    card.pack(fill="x", pady=(0, P(10)))
    caption(card.body, title, color=C["accent"], bg=C["surface"], size=9).pack(anchor="w", pady=(0, P(8)))
    return card.body


def _field(parent, label, show=None, value=""):
    caption(parent, label, bg=C["surface"]).pack(anchor="w")
    e = make_entry(parent, width=30)
    if show:
        e.config(show=show)
    e.insert(0, value)
    e.pack(fill="x", ipady=P(3), pady=(P(2), P(8)))
    return e


class SettingsPage(tk.Frame):
    def __init__(self, master, app_settings, replays_page, ai_settings, on_reload=None, on_tray=None):
        super().__init__(master, bg=C["bg"])
        self.app = app_settings
        self.rp = replays_page
        self.bc = replays_page.settings
        self.ai = ai_settings
        self._q = queue.Queue()
        self.on_reload = on_reload
        self.on_tray = on_tray

        self._sections = {}
        self._build_sections()
        self.after(300, self._poll)

    def _two_columns(self, name):
        sec = tk.Frame(self, bg=C["bg"])
        self._sections[name] = sec
        cols = tk.Frame(sec, bg=C["bg"])
        cols.pack(fill="both", expand=True)
        cols.grid_columnconfigure(0, weight=1, uniform="sp")
        cols.grid_columnconfigure(1, weight=1, uniform="sp")
        cols.grid_rowconfigure(0, weight=1)
        left = tk.Frame(cols, bg=C["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, P(5)))
        right = tk.Frame(cols, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew", padx=(P(5), 0))
        return left, right

    SECTIONS = ["Geral", "Replays e IA", "Dados e cópias"]

    def _build_sections(self):
        nav = tk.Frame(self, bg=C["bg"])
        nav.pack(fill="x", pady=(0, P(10)))
        self.sec_seg = Tabs(nav, self.SECTIONS, self.SECTIONS[0], command=self._show_section,
                            size=10, px=16, py=5)
        self.sec_seg.pack(fill="x")
        l, r = self._two_columns("Geral")
        self._build_general(l)
        self._build_alerts(r)
        l, r = self._two_columns("Replays e IA")
        self._build_ballchasing(l)
        self._build_ai(r)
        l, r = self._two_columns("Dados e cópias")
        self._build_data(l)
        self._build_backup(r)
        self._show_section(self.SECTIONS[0])

    def _show_section(self, name):
        for sec in self._sections.values():
            sec.pack_forget()
        self._sections[name].pack(fill="both", expand=True)

    # ---- Geral -------------------------------------------------------------

    def _build_general(self, parent):
        b = _card(parent, "Geral")
        caption(b, "Idioma", bg=C["surface"]).pack(anchor="w", pady=(0, P(3)))
        self.lang_seg = Segmented(b, list(LANGUAGES.values()), LANGUAGES[self.app.language],
                                  bg=C["surface2"], command=self._set_language, px=12, py=5)
        self.lang_seg.pack(anchor="w", pady=(0, P(10)))

        caption(b, "Escala da interface", bg=C["surface"]).pack(anchor="w", pady=(0, P(3)))
        self.scale_seg = Segmented(b, list(SCALE_LABELS.values()), SCALE_LABELS[self.app.ui_scale],
                                   bg=C["surface2"], command=self._set_scale, px=10, py=5)
        self.scale_seg.pack(anchor="w", pady=(0, P(10)))

        self.compact_var = tk.BooleanVar(value=self.app.compact_start)
        Switch(b, "Iniciar em modo compacto", self.compact_var, self._set_compact,
               bg=C["surface"]).pack(anchor="w")
        self.tray_var = tk.BooleanVar(value=self.app.close_to_tray and tray_mod.available())
        sw = Switch(b, "Fechar para a bandeja do sistema", self.tray_var, self._set_tray,
                    bg=C["surface"])
        sw.pack(anchor="w", pady=(P(8), 0))
        if not tray_mod.available():
            tk.Label(b, text="Indisponível: falta instalar pystray e Pillow (pip install pystray pillow).",
                     bg=C["surface"], fg=C["dim"], font=F(8), anchor="w", justify="left",
                     wraplength=P(420)).pack(fill="x", pady=(P(2), 0))
        self.restart_lbl = tk.Label(b, text="", bg=C["surface"], fg=C["warn"], font=F(9),
                                    anchor="w", justify="left", wraplength=P(420))
        self.restart_lbl.pack(fill="x", pady=(P(10), 0))

    # ---- Avisos da sessao ---------------------------------------------------

    OFF = "Desligado"

    def _build_alerts(self, parent):
        b = _card(parent, "Avisos da sessão")
        tk.Label(b, text="A app mostra um aviso (e toca um som) quando chegas ao limite que definires. "
                         "Serve para parar a tempo, em vez de continuar em tilt.",
                 bg=C["surface"], fg=C["muted"], font=F(8), anchor="w", justify="left",
                 wraplength=P(420)).pack(fill="x", pady=(0, P(8)))
        caption(b, "Avisar após derrotas seguidas", bg=C["surface"]).pack(anchor="w", pady=(0, P(3)))
        opts = [self.OFF] + [str(n) for n in appsettings.LOSS_STOPS if n]
        cur = str(self.app.stop_losses) if self.app.stop_losses else self.OFF
        Segmented(b, opts, cur, bg=C["surface2"], command=self._set_stop_losses,
                  px=12, py=5).pack(anchor="w", pady=(0, P(10)))
        caption(b, "Avisar ao chegar a vitórias na sessão", bg=C["surface"]).pack(anchor="w", pady=(0, P(3)))
        opts = [self.OFF] + [str(n) for n in appsettings.WIN_GOALS if n]
        cur = str(self.app.goal_wins) if self.app.goal_wins else self.OFF
        Segmented(b, opts, cur, bg=C["surface2"], command=self._set_goal_wins,
                  px=12, py=5).pack(anchor="w", pady=(0, P(10)))
        self.sound_var = tk.BooleanVar(value=self.app.alert_sound)
        Switch(b, "Tocar um som no aviso", self.sound_var, self._set_sound,
               bg=C["surface"]).pack(anchor="w")

    def _set_stop_losses(self, label):
        self.app.stop_losses = 0 if label == self.OFF else int(label)
        self._save_app()

    def _set_goal_wins(self, label):
        self.app.goal_wins = 0 if label == self.OFF else int(label)
        self._save_app()

    def _set_sound(self):
        self.app.alert_sound = bool(self.sound_var.get())
        self._save_app()

    def _set_tray(self):
        self.app.close_to_tray = bool(self.tray_var.get())
        self._save_app()
        if self.on_tray:
            self.on_tray(self.app.close_to_tray)

    def _save_app(self):
        self.app.save()
        self._note_restart()

    def _note_restart(self):
        if self.app.last_error:
            self.restart_lbl.config(text=tr("Não consegui gravar as definições: {err}",
                                            err=self.app.last_error), fg=C["bad"])
        else:
            self.restart_lbl.config(text="")

    def _reload(self):
        # A interface e' reconstruida (idioma/escala); depois de este clique acabar.
        if self.on_reload and not self.app.last_error:
            self.after(60, self.on_reload)

    def _set_language(self, label):
        for code, name in LANGUAGES.items():
            if name == label:
                self.app.language = code
        self._save_app()
        self._reload()

    def _set_scale(self, label):
        for key, name in SCALE_LABELS.items():
            if name == label:
                self.app.ui_scale = key
        self._save_app()
        self._reload()

    def _set_compact(self):
        self.app.compact_start = bool(self.compact_var.get())
        self._save_app()

    # ---- Dados e ficheiros -------------------------------------------------

    def _build_data(self, parent):
        b = _card(parent, "Dados e ficheiros")
        tk.Label(b, text=appsettings._BASE_DIR, bg=C["surface"], fg=C["muted"], font=F(8),
                 anchor="w", justify="left", wraplength=P(430)).pack(fill="x", pady=(0, P(6)))
        self.files_box = tk.Frame(b, bg=C["surface"])
        self.files_box.pack(fill="x")
        row = tk.Frame(b, bg=C["surface"])
        row.pack(fill="x", pady=(P(10), 0))
        FlatButton(row, "Abrir pasta", self._open_folder).pack(side="left")
        FlatButton(row, "Exportar dados…", self._export).pack(side="left", padx=(P(8), 0))
        tk.Label(b, text="A exportação não inclui as chaves de API.", bg=C["surface"], fg=C["dim"],
                 font=F(8), anchor="w").pack(fill="x", pady=(P(6), 0))
        self._render_files()

    def _render_files(self):
        for w in self.files_box.winfo_children():
            w.destroy()
        for name, desc, secret in DATA_FILES:
            path = os.path.join(appsettings._BASE_DIR, name)
            row = tk.Frame(self.files_box, bg=C["surface"])
            row.pack(fill="x", pady=(0, P(2)))
            tk.Label(row, text=name, bg=C["surface"], fg=C["text"], font=F(9), anchor="w",
                     width=18).pack(side="left")
            tk.Label(row, text=tr(desc), bg=C["surface"], fg=C["muted"], font=F(9),
                     anchor="w").pack(side="left")
            size = os.path.getsize(path) if os.path.exists(path) else None
            tk.Label(row, text="-" if size is None else f"{size / 1024:.0f} KB", bg=C["surface"],
                     fg=C["warn"] if secret and size else C["dim"], font=F(8)).pack(side="right")

    def refresh(self):
        self._render_files()

    def _open_folder(self):
        base = appsettings._BASE_DIR
        try:
            if sys.platform.startswith("win"):
                os.startfile(base)                       # noqa: S606 (so' Windows)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", base])
            else:
                subprocess.Popen(["xdg-open", base])
        except OSError as e:
            messagebox.showerror(tr("Abrir pasta"), str(e), parent=self)

    def _export(self):
        stamp = time.strftime("%Y-%m-%d")
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".zip", initialfile=f"rl_dados_{stamp}.zip",
            filetypes=[("ZIP", "*.zip")])
        if not path:
            return
        try:
            n = len(maintenance.write_zip(path, appsettings._BASE_DIR))
        except OSError as e:
            messagebox.showerror(tr("Exportar dados…"), tr("Não foi possível gravar: {err}", err=e), parent=self)
            return
        messagebox.showinfo(tr("Exportar dados…"), tr("{n} ficheiros exportados.", n=n), parent=self)

    # ---- Copias de seguranca ------------------------------------------------

    def _build_backup(self, parent):
        b = _card(parent, "Cópia de segurança automática")
        tk.Label(b, text="Guarda uma cópia por dia dos teus dados (sem chaves de API), "
                         "ao abrir a app, e apaga as mais antigas.",
                 bg=C["surface"], fg=C["muted"], font=F(8), anchor="w", justify="left",
                 wraplength=P(420)).pack(fill="x", pady=(0, P(8)))
        self.backup_var = tk.BooleanVar(value=self.app.backup_on)
        Switch(b, "Fazer cópia automática", self.backup_var, self._set_backup_on,
               bg=C["surface"]).pack(anchor="w")
        caption(b, "Pasta das cópias", bg=C["surface"]).pack(anchor="w", pady=(P(10), P(3)))
        row = tk.Frame(b, bg=C["surface"])
        row.pack(fill="x")
        self.backup_dir_lbl = tk.Label(row, text="", bg=C["surface"], fg=C["text"], font=F(9),
                                       anchor="w", justify="left", wraplength=P(330))
        self.backup_dir_lbl.pack(side="left", fill="x", expand=True)
        FlatButton(row, "Escolher…", self._pick_backup_dir, kind="subtle", py=4, px=10, size=9).pack(side="right")
        caption(b, "Quantas cópias guardar", bg=C["surface"]).pack(anchor="w", pady=(P(10), P(3)))
        Segmented(b, [str(n) for n in appsettings.BACKUP_KEEP], str(self.app.backup_keep),
                  bg=C["surface2"], command=self._set_backup_keep, px=12, py=5).pack(anchor="w")
        row = tk.Frame(b, bg=C["surface"])
        row.pack(fill="x", pady=(P(12), 0))
        self.backup_btn = FlatButton(row, "Fazer cópia agora", self._backup_now)
        self.backup_btn.pack(side="left")
        self.backup_lbl = tk.Label(b, text="", bg=C["surface"], fg=C["muted"], font=F(8),
                                   anchor="w", justify="left", wraplength=P(420))
        self.backup_lbl.pack(fill="x", pady=(P(6), 0))
        self._render_backup()

    def _render_backup(self):
        folder = self.app.backup_folder()
        self.backup_dir_lbl.config(text=folder)
        names = maintenance.list_backups(folder)
        if names:
            self.backup_lbl.config(text=tr("Última cópia: {name} ({n} guardadas)", name=names[-1], n=len(names)),
                                   fg=C["muted"])
        else:
            self.backup_lbl.config(text=tr("Ainda não há cópias."), fg=C["muted"])

    def _set_backup_on(self):
        self.app.backup_on = bool(self.backup_var.get())
        self._save_app()

    def _set_backup_keep(self, label):
        self.app.backup_keep = int(label)
        self._save_app()

    def _pick_backup_dir(self):
        path = filedialog.askdirectory(parent=self, initialdir=self.app.backup_folder(),
                                       title=tr("Pasta das cópias"))
        if path:
            self.app.backup_dir = os.path.normpath(path)
            self._save_app()
            self._render_backup()

    def _backup_now(self):
        self.backup_btn.config(text="A guardar…")
        maintenance.run_backup_async(
            appsettings._BASE_DIR, self.app.backup_folder(), self.app.backup_keep,
            lambda path, err: self._q.put(("backup", path, err)))

    # ---- Ballchasing -------------------------------------------------------

    def _build_ballchasing(self, parent):
        b = _card(parent, "Ballchasing")
        caption(b, "Chave da API do Ballchasing", bg=C["surface"]).pack(anchor="w")
        trow = tk.Frame(b, bg=C["surface"])
        trow.pack(fill="x", pady=(P(2), 0))
        self.token_entry = make_entry(trow, width=30)
        self.token_entry.config(show="•")
        self.token_entry.insert(0, self.bc.token)
        self.token_entry.pack(side="left", fill="x", expand=True, ipady=P(3))
        self.token_entry.bind("<KeyRelease>", self._token_changed)
        FlatButton(trow, "Testar", self._test_bc).pack(side="left", padx=(P(8), 0))
        self.bc_status = tk.Label(b, text="ballchasing.com/upload  →  copia a chave", bg=C["surface"],
                                  fg=C["dim"], font=F(8), anchor="w", justify="left", wraplength=P(430))
        self.bc_status.pack(fill="x", pady=(P(3), P(10)))

        hdr = tk.Frame(b, bg=C["surface"])
        hdr.pack(fill="x")
        caption(hdr, "Pastas dos replays (Steam, Epic…)", bg=C["surface"]).pack(side="left")
        FlatButton(hdr, "+ Adicionar pasta", self._add_dir, py=2, px=8, size=8).pack(side="right")
        self.dirs_frame = tk.Frame(b, bg=C["surface"])
        self.dirs_frame.pack(fill="x", pady=(P(3), P(8)))
        self._render_dirs()

        row = tk.Frame(b, bg=C["surface"])
        row.pack(fill="x")
        for label, opts, current, cmd in (
                ("Visibilidade no Ballchasing", [VISIBILITY_LABELS[v] for v in VISIBILITIES],
                 VISIBILITY_LABELS[self.bc.visibility], self._set_visibility),
                ("Enviar replays", SINCE_OPTIONS, self.bc.since, self._set_since)):
            box = tk.Frame(row, bg=C["surface"])
            box.pack(side="left", padx=(0, P(14)))
            caption(box, label, bg=C["surface"]).pack(anchor="w", pady=(0, P(3)))
            Segmented(box, opts, current, bg=C["surface2"], command=cmd, px=9, py=5).pack(anchor="w")

    def _bc_save(self):
        self.bc.save()
        if self.bc.last_error:
            self._bc_msg(tr("Não consegui gravar as definições: {err}", err=self.bc.last_error), C["bad"])

    def _bc_msg(self, text, color=None):
        self.bc_status.config(text=text, fg=color or C["muted"])

    def _token_changed(self, _e=None):
        self.bc.token = self.token_entry.get().strip()
        self._bc_save()

    def _test_bc(self):
        self._token_changed()
        self._bc_msg(tr("A testar a ligação…"))

        def work():
            try:
                info = Client(self.bc.token).ping()
                q = (info.get("quota") or {}).get("uploads_in_24h") or {}
                extra = tr(" · uploads hoje: {used}/{max}", used=q.get("used"), max=q.get("max")) if q else ""
                self._q.put(("ok", tr("Ligado como {name}", name=info.get("name", "?")) + extra, "bc"))
            except BallchasingError as e:
                self._q.put(("err", str(e), "bc"))
        threading.Thread(target=work, daemon=True).start()

    def _render_dirs(self):
        for w in self.dirs_frame.winfo_children():
            w.destroy()
        if not self.bc.replay_dirs:
            tk.Label(self.dirs_frame, text=tr("Nenhuma pasta. Adiciona a pasta onde o jogo guarda os replays."),
                     bg=C["surface"], fg=C["warn"], font=F(9), anchor="w", justify="left",
                     wraplength=P(430)).pack(fill="x")
        for d in self.bc.replay_dirs:
            row = tk.Frame(self.dirs_frame, bg=C["surface2"])
            row.pack(fill="x", pady=(0, P(4)))
            ok = os.path.isdir(d)
            tk.Label(row, text=("●  " if ok else "✕  ") + d, bg=C["surface2"],
                     fg=C["text"] if ok else C["bad"], font=F(9), anchor="w",
                     padx=P(8), pady=P(4)).pack(side="left", fill="x", expand=True)
            FlatButton(row, "Remover", lambda p=d: self._remove_dir(p), kind="subtle",
                       py=3, px=8, size=8).pack(side="right", padx=P(4), pady=P(2))

    def _add_dir(self):
        start = self.bc.replay_dirs[0] if self.bc.replay_dirs else None
        d = filedialog.askdirectory(parent=self, initialdir=start if start and os.path.isdir(start) else None)
        if d:
            d = os.path.normpath(d)
            if d not in self.bc.replay_dirs:
                self.bc.replay_dirs.append(d)
                self._bc_save()
            self._render_dirs()

    def _remove_dir(self, path):
        self.bc.replay_dirs = [x for x in self.bc.replay_dirs if x != path]
        self._bc_save()
        self._render_dirs()

    def _set_visibility(self, label):
        for k, v in VISIBILITY_LABELS.items():
            if v == label:
                self.bc.visibility = k
        self._bc_save()

    def _set_since(self, value):
        self.bc.since = value
        if value == "Só novos":
            self.bc.enabled_since = time.time()
        self._bc_save()

    # ---- IA ----------------------------------------------------------------

    def _build_ai(self, parent):
        b = _card(parent, "Análise com IA")
        row = tk.Frame(b, bg=C["surface"])
        row.pack(fill="x", pady=(0, P(8)))
        caption(row, "Serviço", bg=C["surface"]).pack(side="left", padx=(0, P(8)))
        self.ai_prov = Dropdown(row, lambda: [(k, k) for k in ai_coach.PRESETS],
                                self._ai_pick_provider, text=self.ai.provider)
        self.ai_prov.pack(side="left")
        grid = tk.Frame(b, bg=C["surface"])
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1, uniform="ai")
        grid.grid_columnconfigure(1, weight=1, uniform="ai")
        self.ai_entries = {}
        for key, label, show, r, c, span in (("api_key", "Chave da API", "•", 0, 0, 1),
                                             ("model", "Modelo", None, 0, 1, 1),
                                             ("base_url", "Endereço (base URL)", None, 1, 0, 2)):
            cell = tk.Frame(grid, bg=C["surface"])
            cell.grid(row=r, column=c, columnspan=span, sticky="ew",
                      padx=(0, P(8)) if c == 0 and span == 1 else 0)
            e = _field(cell, label, show, getattr(self.ai, key))
            e.bind("<KeyRelease>", lambda _e, k=key: self._ai_edited(k))
            self.ai_entries[key] = e

        caption(b, "Idioma da resposta", bg=C["surface"]).pack(anchor="w", pady=(0, P(3)))
        Segmented(b, list(ai_coach.AI_LANGUAGES.values()), ai_coach.AI_LANGUAGES[self.ai.language],
                  bg=C["surface2"], command=self._ai_set_lang, px=10, py=5).pack(anchor="w")
        self.ai_note = tk.Label(
            b, text=tr("Cria a chave no site do serviço (confirma lá o plano gratuito e os modelos)."),
            bg=C["surface"], fg=C["dim"], font=F(8), justify="left", anchor="w", wraplength=P(430))
        self.ai_note.pack(fill="x", pady=(P(8), 0))

    def _ai_pick_provider(self, name):
        self.ai.pick_provider(name)
        self.ai_prov.set_text(name)
        for k in ("model", "base_url"):
            self.ai_entries[k].delete(0, "end")
            self.ai_entries[k].insert(0, getattr(self.ai, k))
        self.ai.save()

    def _ai_edited(self, key):
        setattr(self.ai, key, self.ai_entries[key].get().strip())
        self.ai.save()

    def _ai_set_lang(self, label):
        for code, name in ai_coach.AI_LANGUAGES.items():
            if name == label:
                self.ai.language = code
        self.ai.save()

    # ---- fila de mensagens das threads --------------------------------------

    def _poll(self):
        try:
            while True:
                kind, text, extra = self._q.get_nowait()
                if kind == "backup":
                    self.backup_btn.config(text="Fazer cópia agora")
                    if extra:
                        self.backup_lbl.config(text=tr("Não foi possível fazer a cópia: {err}", err=extra),
                                               fg=C["bad"])
                    else:
                        self._render_backup()
                    continue
                self._bc_msg(text, C["good"] if kind == "ok" else C["bad"])
        except queue.Empty:
            pass
        self.after(300, self._poll)
