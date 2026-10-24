"""
compare.py

"Esta partida/replay vs a tua media": calculo (puro, testavel) e a faixa
que mostra o resultado por baixo das listas do Historico e dos Replays.
"""

import tkinter as tk

from i18n import tr
from ui_kit import C, F, P, caption

# (nome, chave na partida, chave na media, sentido: +1 maior e' melhor)
MATCH_METRICS = [
    ("Golos", "goals", "goals_avg", 1),
    ("Assistências", "assists", "assists_avg", 1),
    ("Defesas", "saves", "saves_avg", 1),
    ("Remates", "shots", "shots_avg", 0),
    ("Pontos", "score", "score_avg", 1),
]

# (nome, chave nos dados do replay, sentido, sufixo, casas)
REPLAY_METRICS = [
    ("Posse", "possession_pct", 1, "%", 0),
    ("Boost/min", "bpm", 0, "", 0),
    ("Sem boost", "percent_zero_boost", -1, "%", 0),
    ("Atrás da bola", "percent_behind_ball", 1, "%", 0),
    ("Velocidade", "avg_speed", 0, "", 0),
]


def _verdict(delta, direction, ref):
    """True = melhor que a media, False = pior, None = igual/neutro."""
    if not direction:
        return None
    tol = max(0.25, abs(ref) * 0.08)
    if direction * delta > tol:
        return True
    if direction * delta < -tol:
        return False
    return None


def compare_match(row, avg):
    """row: partida do historico; avg: dict de MatchHistory.summary()[modo]."""
    out = []
    for name, key, akey, direction in MATCH_METRICS:
        v, a = row.get(key), avg.get(akey)
        if v is None or a is None:
            continue
        out.append({"label": name, "value": float(v), "avg": float(a), "delta": v - a,
                    "good": _verdict(v - a, direction, a), "suffix": "", "digits": 1})
    return out


def compare_replay(data, avg):
    """data: stats deste replay; avg: medias (coach.replay_averages)."""
    out = []
    for name, key, direction, suffix, digits in REPLAY_METRICS:
        v, a = data.get(key), avg.get(key)
        if not isinstance(v, (int, float)) or a is None:
            continue
        out.append({"label": name, "value": float(v), "avg": float(a), "delta": v - a,
                    "good": _verdict(v - a, direction, a), "suffix": suffix, "digits": digits})
    return out


class CompareStrip(tk.Frame):
    """Faixa com 'valor (media X, +Y)' por metrica; fica sempre com a mesma altura."""

    def __init__(self, master, bg):
        super().__init__(master, bg=bg)
        self._bg = bg
        self.title = tk.Label(self, text="", bg=bg, fg=C["muted"], font=F(8), anchor="w")
        self.title.pack(fill="x", pady=(P(8), P(4)))
        self.row = tk.Frame(self, bg=bg)
        self.row.pack(fill="x")
        self.clear()

    def clear(self):
        self._fill(tr("Escolhe uma linha para a comparar com a tua média."), [])

    def show(self, title, items):
        self._fill(title, items)

    def _fill(self, title, items):
        self.title.config(text=title)
        for w in self.row.winfo_children():
            w.destroy()
        for i, it in enumerate(items):
            self.row.grid_columnconfigure(i, weight=1, uniform="cmp")
            col = C["good"] if it["good"] is True else C["bad"] if it["good"] is False else C["muted"]
            cell = tk.Frame(self.row, bg=self._bg)
            cell.grid(row=0, column=i, sticky="w")
            d, suf = it["digits"], it["suffix"]
            tk.Label(cell, text=f"{it['value']:.{d}f}{suf}", bg=self._bg, fg=C["text"],
                     font=F(11, "bold")).pack(anchor="w")
            tk.Label(cell, text=f"{it['delta']:+.{d}f}{suf}  ({tr('média')} {it['avg']:.{d}f}{suf})",
                     bg=self._bg, fg=col, font=F(8)).pack(anchor="w")
            caption(cell, tr(it["label"]), bg=self._bg, color=C["dim"], size=7).pack(anchor="w")
