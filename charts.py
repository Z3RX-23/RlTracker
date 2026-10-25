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


SESSION_GAP_MIN = 60      # mais de 1 h sem jogar = sessao nova
POS_CAP = 8               # ultima barra = "8 ou mais"


def sessions(rows, gap_min=SESSION_GAP_MIN):
    """Agrupa os jogos em sessoes (lista de listas, cada uma por ordem cronologica)."""
    rows = sorted(rows, key=lambda r: (r["ts"], r.get("id", 0)))
    out, cur, last = [], [], None
    for r in rows:
        t = parse_ts(r["ts"])
        if t is None:
            continue
        if last is not None and cur and (t - last).total_seconds() > gap_min * 60:
            out.append(cur)
            cur = []
        cur.append(r)
        last = t
    if cur:
        out.append(cur)
    return out


def by_session_position(rows, cap=POS_CAP):
    """[[jogos, vitorias]] para o 1.o, 2.o, ... jogo da sessao (o ultimo junta os restantes)."""
    b = [[0, 0] for _ in range(cap)]
    for s in sessions(rows):
        for i, r in enumerate(s):
            k = min(i, cap - 1)
            b[k][0] += 1
            b[k][1] += 1 if r["won"] else 0
    return b


def after_result(rows):
    """[[n, w] 1.o jogo da sessao, [n, w] depois de ganhar, [n, w] depois de perder]."""
    b = [[0, 0], [0, 0], [0, 0]]
    for s in sessions(rows):
        for i, r in enumerate(s):
            k = 0 if i == 0 else (1 if s[i - 1]["won"] else 2)
            b[k][0] += 1
            b[k][1] += 1 if r["won"] else 0
    return b


def rolling_avg(rows, key, window=10, min_games=5):
    """[(n_do_jogo, media)] da stat `key` nos ultimos `window` jogos."""
    rows = sorted(rows, key=lambda r: (r["ts"], r.get("id", 0)))
    out = []
    for i in range(len(rows)):
        w = rows[max(0, i - window + 1):i + 1]
        if len(w) >= min(min_games, window):
            out.append((i + 1, sum((r.get(key) or 0) for r in w) / len(w)))
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


class ValueChart(LineChart):
    """Linha de uma media (golos, pontos...) com eixo em valores, nao em %."""

    def __init__(self, *a, unit="", **kw):
        super().__init__(*a, **kw)
        self._unit = unit
        self._vmax = 1.0

    def set_unit(self, unit):
        self._unit = unit

    def _nice_max(self):
        top = max((v for _, v in self._data), default=1.0) * 1.1
        for m in (1, 2, 4, 6, 8, 10, 20, 40, 60, 80, 100, 200, 400, 600, 800, 1000, 2000, 5000):
            if top <= m:
                return float(m)
        return float(top)

    def _grid(self, x0, y0, x1, y1):
        self._vmax = self._nice_max()
        for frac in (0, 0.5, 1):
            y = y1 - (y1 - y0) * frac
            self.create_line(x0, y, x1, y, fill=C["border"], dash=(3, 3) if frac == 0.5 else ())
            v = self._vmax * frac
            self.create_text(x0 - P(6), y, text=f"{v:.0f}" if v >= 10 else f"{v:.1f}".rstrip("0").rstrip("."),
                             anchor="e", fill=C["dim"], font=F(7))

    def _y(self, v, y0, y1):
        return y1 - (y1 - y0) * min(v, self._vmax) / self._vmax

    def redraw(self):
        if self._data:
            self._vmax = self._nice_max()
        super().redraw()

    def _motion(self, e):
        if not self._data or len(self._data) < 2 or not self._on_hover or not getattr(self, "_xy", None):
            return
        xs = [x for x, _ in self._xy]
        i = min(range(len(xs)), key=lambda k: abs(xs[k] - e.x))
        n, v = self._data[i]
        self._on_hover(tr("Jogo #{n}: média de {v:.1f} {u} nos últimos 10 jogos", n=n, v=v, u=tr(self._unit)))


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


class MMRChart(_Base):
    """MMR registado ao longo do TEMPO (eixo X = data/hora real). Aceita varias
    linhas (uma por modo); a do modo escolhido fica em destaque."""
    LEFT = 40

    def set_series(self, series, active=None):
        """series: [{"mode", "label", "color", "points": [(datetime, mmr)]}]"""
        self._series = [s for s in series if s["points"]]
        self._active = active
        self._data = [p for s in self._series for p in s["points"]]
        self.redraw()

    def redraw(self):
        super().redraw()
        x0, y0, x1, y1 = self._area()
        if x1 - x0 < 20:
            return
        ser = getattr(self, "_series", [])
        if not any(len(s["points"]) >= 2 for s in ser):
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2,
                             text=tr("Regista o MMR pelo menos duas vezes para ver o gráfico."),
                             fill=C["dim"], font=F(9))
            return
        vals = [v for _, v in self._data]
        lo, hi = min(vals), max(vals)
        pad = max(10, (hi - lo) * 0.15)
        lo, hi = lo - pad, hi + pad
        t0 = min(t for t, _ in self._data)
        t1 = max(t for t, _ in self._data)
        span = max(1.0, (t1 - t0).total_seconds())
        for frac in (0, 0.5, 1):
            y = y1 - (y1 - y0) * frac
            self.create_line(x0, y, x1, y, fill=C["border"], dash=(3, 3) if frac == 0.5 else ())
            self.create_text(x0 - P(6), y, text=f"{lo + (hi - lo) * frac:.0f}", anchor="e",
                             fill=C["dim"], font=F(7))
        self._pts = []
        order = sorted(ser, key=lambda s: s["mode"] == self._active)       # o ativo desenha por cima
        for s in order:
            on = s["mode"] == self._active or len(ser) == 1
            xy = [(x0 + (x1 - x0) * (t - t0).total_seconds() / span,
                   y1 - (y1 - y0) * (v - lo) / (hi - lo)) for t, v in s["points"]]
            if len(xy) >= 2:
                self.create_line(*[c for p in xy for c in p], fill=s["color"],
                                 width=max(2, P(2)) if on else 1, dash=() if on else (4, 3))
            lx, ly = xy[-1]
            r = P(3) if on else P(2)
            self.create_oval(lx - r, ly - r, lx + r, ly + r, fill=s["color"], outline="")
            for (x, y), (t, v) in zip(xy, s["points"]):
                self._pts.append((x, y, s, t, v))
        fmt = "%d/%m %H:%M" if span < 86400 * 2 else "%d/%m"
        self.create_text(x0, y1 + P(10), text=t0.strftime(fmt), anchor="w", fill=C["dim"], font=F(7))
        self.create_text(x1, y1 + P(10), text=t1.strftime(fmt), anchor="e", fill=C["dim"], font=F(7))
        if len(ser) > 1:
            x = x0 + P(8)
            for s in ser:
                self.create_rectangle(x, y0 + P(2), x + P(8), y0 + P(8), fill=s["color"], outline="")
                self.create_text(x + P(12), y0 + P(5), text=s["label"], anchor="w", fill=C["muted"], font=F(7))
                x += P(46)

    def _motion(self, e):
        pts = getattr(self, "_pts", None)
        if not pts or not self._on_hover:
            return
        x, y, s, t, v = min(pts, key=lambda p: abs(p[0] - e.x) + abs(p[1] - e.y) * 0.3)
        self._on_hover(tr("{m}: {v} MMR em {t}", m=s["label"], v=v, t=t.strftime("%d/%m/%Y %H:%M")))
