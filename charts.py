"""
charts.py

Graficos do Historico: calculo (puro, testavel) e dois graficos desenhados
em Canvas -- linha (win% movel) e barras (win% por hora / dia da semana).
"""

import tkinter as tk
from datetime import datetime

from i18n import tr
from ui_kit import C, F, P

MIN_BUCKET = 3          # jogos minimos para uma barra "contar"
WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def parse_ts(ts):
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def rolling_win_pct(rows, window=10, min_games=5):
    """[(n_do_jogo, win%)] com a janela dos ultimos `window` jogos (mais antigo -> recente)."""
    rows = sorted(rows, key=lambda r: (r["ts"], r.get("id", 0)))
    out = []
    for i in range(len(rows)):
        w = rows[max(0, i - window + 1):i + 1]
        if len(w) >= min(min_games, window):
            out.append((i + 1, 100.0 * sum(1 for r in w if r["won"]) / len(w)))
    return out


def _bucket(rows, size, key):
    b = [[0, 0] for _ in range(size)]          # [jogos, vitorias]
    for r in rows:
        t = parse_ts(r["ts"])
        if t is None:
            continue
        i = key(t)
        b[i][0] += 1
        b[i][1] += 1 if r["won"] else 0
    return b


def by_hour(rows):
    return _bucket(rows, 24, lambda t: t.hour)


def by_weekday(rows):
    return _bucket(rows, 7, lambda t: t.weekday())


def pct(bucket):
    n, w = bucket
    return 100.0 * w / n if n else None


def best_worst(buckets, min_n=MIN_BUCKET):
    """(melhor_idx, pior_idx) entre os baldes com jogos suficientes, ou None."""
    ok = [(pct(b), i) for i, b in enumerate(buckets) if b[0] >= min_n]
    if len(ok) < 2:
        return None
    best = max(ok, key=lambda x: (x[0], -x[1]))
    worst = min(ok, key=lambda x: (x[0], x[1]))
    if best[1] == worst[1] or best[0] == worst[0]:
        return None
    return best[1], worst[1]


def pct_color(p):
    return C["good"] if p >= 55 else (C["bad"] if p < 45 else C["accent"])


class _Base(tk.Canvas):
    LEFT, BOTTOM, TOP, RIGHT = 34, 20, 8, 8

    def __init__(self, master, bg, height=150, on_hover=None):
        super().__init__(master, bg=bg, height=P(height), highlightthickness=0, bd=0)
        self._bg = bg
        self._on_hover = on_hover
        self._data = []
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._on_hover and self._on_hover(""))

    def _area(self):
        w, h = self.winfo_width(), self.winfo_height()
        return P(self.LEFT), P(self.TOP), w - P(self.RIGHT), h - P(self.BOTTOM)

    def _y(self, pct_value, y0, y1):
        return y1 - (y1 - y0) * pct_value / 100.0

    def _grid(self, x0, y0, x1, y1):
        for v in (0, 50, 100):
            y = self._y(v, y0, y1)
            self.create_line(x0, y, x1, y, fill=C["border"], dash=(3, 3) if v == 50 else ())
            self.create_text(x0 - P(6), y, text=f"{v}%", anchor="e", fill=C["dim"], font=F(7))

    def _motion(self, e):
        pass

    def set(self, data):
        self._data = data
        self.redraw()

    def redraw(self):
        self.delete("all")


class LineChart(_Base):
    def redraw(self):
        super().redraw()
        x0, y0, x1, y1 = self._area()
        if x1 - x0 < 20:
            return
        self._grid(x0, y0, x1, y1)
        pts = self._data
        if len(pts) < 2:
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=tr("Poucos jogos para o gráfico."),
                             fill=C["dim"], font=F(9))
            return
        first, last = pts[0][0], pts[-1][0]
        span = max(1, last - first)
        self._xy = [(x0 + (x1 - x0) * (n - first) / span, self._y(p, y0, y1)) for n, p in pts]
        flat = [c for xy in self._xy for c in xy]
        self.create_line(*flat, fill=C["accent"], width=max(2, P(2)), smooth=False)
        lx, ly = self._xy[-1]
        self.create_oval(lx - P(3), ly - P(3), lx + P(3), ly + P(3), fill=C["accent"], outline="")
        self.create_text(x0, y1 + P(10), text=f"#{first}", anchor="w", fill=C["dim"], font=F(7))
        self.create_text(x1, y1 + P(10), text=f"#{last}", anchor="e", fill=C["dim"], font=F(7))

    def _motion(self, e):
        if not self._data or len(self._data) < 2 or not self._on_hover:
            return
        xs = [x for x, _ in self._xy]
        i = min(range(len(xs)), key=lambda k: abs(xs[k] - e.x))
        n, p = self._data[i]
        self._on_hover(tr("Jogo #{n}: {p:.0f}% de vitórias nos últimos jogos", n=n, p=p))


class BarChart(_Base):
    """data: [(rotulo, pct_ou_None, n_jogos)]"""

    def redraw(self):
        super().redraw()
        x0, y0, x1, y1 = self._area()
        if x1 - x0 < 20 or not self._data:
            return
        self._grid(x0, y0, x1, y1)
        k = len(self._data)
        slot = (x1 - x0) / k
        self._slots = []
        step = 1 if k <= 8 else 3
        for i, (label, p, n) in enumerate(self._data):
            bx0, bx1 = x0 + slot * i + slot * 0.18, x0 + slot * (i + 1) - slot * 0.18
            self._slots.append((x0 + slot * i, x0 + slot * (i + 1)))
            if p is not None and n >= MIN_BUCKET:
                self.create_rectangle(bx0, self._y(p, y0, y1), bx1, y1, fill=pct_color(p), outline="")
            elif n:                      # poucos jogos: so' um traco na base
                self.create_rectangle(bx0, y1 - P(2), bx1, y1, fill=C["dim"], outline="")
            if i % step == 0:
                self.create_text((bx0 + bx1) / 2, y1 + P(10), text=label, fill=C["dim"], font=F(7))

    def _motion(self, e):
        if not self._data or not self._on_hover or not getattr(self, "_slots", None):
            return
        for i, (a, b) in enumerate(self._slots):
            if a <= e.x < b:
                label, p, n = self._data[i]
                if not n:
                    self._on_hover(tr("{l}: sem jogos", l=label))
                else:
                    self._on_hover(tr("{l}: {p:.0f}% de vitórias em {n} jogos", l=label, p=p, n=n))
                return
