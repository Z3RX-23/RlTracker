"""
appsettings.py

Definicoes gerais da app (settings.json, ao lado da app/.exe):
idioma, escala, modo compacto, avisos da sessao, bandeja e copias de seguranca.
As chaves de API ficam nos seus ficheiros (ballchasing.json, ai.json).
"""

import json
import os
import sys

if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_PATH = os.path.join(_BASE_DIR, "settings.json")
SCALES = ["auto", "100%", "125%", "150%", "175%", "200%"]
LOSS_STOPS = [0, 2, 3, 4, 5]          # 0 = desligado
WIN_GOALS = [0, 3, 5, 10]
BACKUP_KEEP = [3, 7, 14, 30]

# nome -> valor por omissao (o tipo do valor por omissao valida o do ficheiro)
_DEFAULTS = {
    "language": "pt", "ui_scale": "auto", "compact_start": False,
    "stop_losses": 0, "goal_wins": 0, "alert_sound": True,
    "close_to_tray": False,
    "backup_on": True, "backup_dir": "", "backup_keep": 7,
}


class AppSettings:
    def __init__(self, path=SETTINGS_PATH):
        self.path = path
        self.last_error = None
        for k, v in _DEFAULTS.items():
            setattr(self, k, v)
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(d, dict):
            return
        if d.get("language") in ("pt", "en"):
            self.language = d["language"]
        if d.get("ui_scale") in SCALES:
            self.ui_scale = d["ui_scale"]
        for k in ("compact_start", "alert_sound", "close_to_tray", "backup_on"):
            if isinstance(d.get(k), bool):
                setattr(self, k, d[k])
        if d.get("stop_losses") in LOSS_STOPS:
            self.stop_losses = d["stop_losses"]
        if d.get("goal_wins") in WIN_GOALS:
            self.goal_wins = d["goal_wins"]
        if d.get("backup_keep") in BACKUP_KEEP:
            self.backup_keep = d["backup_keep"]
        if isinstance(d.get("backup_dir"), str):
            self.backup_dir = d["backup_dir"].strip()

    def scale_value(self):
        """None = automatico; senao fator (1.0 = 100%)."""
        if self.ui_scale == "auto":
            return None
        return int(self.ui_scale.rstrip("%")) / 100.0

    def backup_folder(self):
        return self.backup_dir or os.path.join(_BASE_DIR, "backups")

    def save(self):
        text = json.dumps({k: getattr(self, k) for k in _DEFAULTS}, indent=2, ensure_ascii=False)
        self.last_error = None
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.path)
            return True
        except OSError:
            pass
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(text)
            return True
        except OSError as e:
            self.last_error = f"{self.path}: {e}"
            return False
