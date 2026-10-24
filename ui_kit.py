"""
ui_kit.py

Tema e componentes visuais (Tkinter puro) usados pela app: cartoes com
cantos arredondados, botoes planos, menus, abas, switches, barras e
"pills". Tudo desenhado com Canvas/Label para ter o mesmo aspeto no
Windows e sem depender de temas nativos.

Escala (DPI): P(n) converte pixeis "a 96 dpi" para pixeis reais, para que
a janela nao fique minuscula em ecras com 125/150/200%.
"""

import os
import sys
import tkinter as tk

from i18n import tr

FONT = "Segoe UI"

C = {
    "bg":       "#0b1128",
    "surface":  "#141d44",
    "surface2": "#1d2a5c",
    "surface3": "#283a73",
    "border":   "#2e4083",
    "text":     "#e9eeff",
    "muted":    "#a3b3dc",
    "dim":      "#7f90bd",
    "blue":     "#4d8dff",
    "blue_dk":  "#1b3a78",
    "orange":   "#ff8a3d",
    "orange_dk": "#7a3a12",
    "good":     "#34d399",
    "warn":     "#fbbf24",
    "bad":      "#f87171",
    "accent":   "#6ea8ff",
}

SCALE = 1.0

PREFERRED_FONT = "Source Sans Pro"
FONT_M = None          # peso "medio" (Semibold) para texto pequeno de tabelas/eventos
FONT_N = None          # familia do peso normal (None = a regular)
SIZE_BONUS = 0         # a Source Sans tem x-height pequeno: +1pt iguala o tamanho visual
FONT_FILES = ("SourceSansPro-Regular.ttf", "SourceSansPro-Semibold.ttf", "SourceSansPro-Bold.ttf")


def setup_fonts(root):
    """Usa a Inter (vai junto com a app, pasta fonts/) e cai para a Segoe UI se falhar."""
    global FONT, FONT_N, FONT_M, SIZE_BONUS
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    fdir = os.path.join(base, "fonts")
    if sys.platform == "win32" and os.path.isdir(fdir):
        try:
            import ctypes
            for name in FONT_FILES:
                p = os.path.join(fdir, name)
                if os.path.exists(p):
                    ctypes.windll.gdi32.AddFontResourceExW(p, 0x10, 0)    # FR_PRIVATE: so' neste processo
        except Exception:
            pass
    try:
        import tkinter.font as tkfont
        fams = tkfont.families(root)
        if PREFERRED_FONT in fams:
            FONT = PREFERRED_FONT
            SIZE_BONUS = 1
            FONT_M = PREFERRED_FONT + " Semibold" if PREFERRED_FONT + " Semibold" in fams else None
    except tk.TclError:
        pass


def set_scale(value):
    global SCALE
    SCALE = max(1.0, float(value))


def P(n):
    """Pixeis a 96 dpi -> pixeis reais."""
    return int(round(n * SCALE)) if n else 0


def F(size, weight="normal"):
    size += SIZE_BONUS
    if weight == "medium":
        return (FONT_M, size, "normal") if FONT_M else (FONT, size, "normal")
    if weight == "normal" and FONT_N:
        return (FONT_N, size, "normal")
    return (FONT, size, weight)


def _mix(c1, c2, t):
    """Mistura duas cores #rrggbb (t=0 -> c1, t=1 -> c2)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def hgrad(cv, x0, y0, x1, y1, c0, c1, tag=None, step=None):
    """Gradiente horizontal (c0 -> c1) feito com linhas verticais."""
    w = max(1, int(x1 - x0))
    step = step or max(2, w // 220)
    x = 0
    while x < w:
        t = x / max(1, w - 1)
        cv.create_rectangle(x0 + x, y0, min(x0 + x + step, x1), y1, fill=_mix(c0, c1, t),
                            outline="", tags=tag or ())
        x += step


def vgrad(cv, x0, y0, x1, y1, c0, c1, tag=None, step=None):
    """Gradiente vertical (c0 -> c1)."""
    h = max(1, int(y1 - y0))
    step = step or max(2, h // 220)
    y = 0
    while y < h:
        t = y / max(1, h - 1)
        cv.create_rectangle(x0, y0 + y, x1, min(y0 + y + step, y1), fill=_mix(c0, c1, t),
                            outline="", tags=tag or ())
        y += step


def _rrect(x1, y1, x2, y2, r):
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


# ── Cartao ───────────────────────────────────────────────────────────────────

class Card(tk.Canvas):
    """Fundo arredondado com contorno. Os widgets vao em self.body.

    fit=True  -> a altura segue o conteudo (cartoes "fill=x").
    fit=False -> ocupa o espaco que o layout lhe der (fill="both").
    """

    def __init__(self, master, bg=None, radius=14, pad=14, border=None, fit=True, **kw):
        outer = master.cget("bg")
        super().__init__(master, bg=outer, highlightthickness=0, bd=0,
                         height=kw.pop("height", 10), **kw)
        self._fill = bg or C["surface"]
        self._border = border or C["border"]
        self._r = P(radius)
        self._pad = P(pad)
        self._fit = fit
        self.body = tk.Frame(self, bg=self._fill)
        self.body.place(x=self._pad, y=self._pad, relwidth=1.0,
                        width=-2 * self._pad,
                        **({} if fit else {"relheight": 1.0, "height": -2 * self._pad}))
        self.bind("<Configure>", self._on_cfg)
        self.body.bind("<Configure>", self._on_body_cfg)

    def _on_cfg(self, e):
        self.delete("_bg")
        w, h = e.width - 1, e.height - 1
        if w <= 2 or h <= 2:
            return
        r = min(self._r, w // 2, h // 2)
        self.create_polygon(_rrect(0, 0, w, h, r), smooth=True, fill=self._fill,
                            outline=self._border, width=1, tags="_bg")
        # realce: fio de luz no topo (do acento a transparente)
        x0, x1 = r, w - r
        if x1 - x0 > 8:
            n = 40
            for k in range(n):
                xa = x0 + (x1 - x0) * k / n
                xb = x0 + (x1 - x0) * (k + 1) / n
                self.create_line(xa, 1, xb, 1, fill=_mix(C["accent"], self._fill, 0.45 + 0.55 * k / n),
                                 tags="_bg")
        self.tag_lower("_bg")

    def _on_body_cfg(self, _e):
        if self._fit:
            h = self.body.winfo_reqheight() + 2 * self._pad
            if h > 2 and int(self.cget("height")) != h:
                self.config(height=h)


# ── Botoes ───────────────────────────────────────────────────────────────────

class FlatButton(tk.Label):
    KINDS = {
        "ghost":   (C["surface2"], C["text"], C["surface3"]),
        "primary": (C["accent"], C["bg"], "#8dbbff"),
        "danger":  (C["surface2"], C["bad"], "#3a2036"),
        "subtle":  (C["surface"], C["muted"], C["surface2"]),
    }

    def __init__(self, master, text, command=None, kind="ghost", size=9, px=12, py=5, **kw):
        bg, fg, hover = self.KINDS[kind]
        super().__init__(master, text=text, bg=bg, fg=fg, font=F(size, "bold" if kind == "primary" else "normal"),
                         padx=P(px), pady=P(py), cursor="hand2", **kw)
        self._bg, self._hover, self._cmd = bg, hover, command
        self.bind("<Enter>", lambda _e: self.config(bg=self._hover))
        self.bind("<Leave>", lambda _e: self.config(bg=self._bg))
        self.bind("<ButtonRelease-1>", self._click)

    def _click(self, e):
        if self._cmd and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self._cmd()

    def set_command(self, cmd):
        self._cmd = cmd


class Dropdown(FlatButton):
    """Botao que abre um menu proprio (cartao com linhas). provider() -> [(rotulo, valor)]."""

    _open_menu = None          # so' um menu aberto de cada vez

    def __init__(self, master, provider, on_pick, text="", size=9, px=10, py=5, **kw):
        super().__init__(master, text, None, "ghost", size, px, py, **kw)
        self._provider, self._on_pick, self._text, self._size = provider, on_pick, text, size
        self.set_text(text)
        self.set_command(self._toggle)

    def set_text(self, text):
        self._text = text
        self.config(text=f"{tr(text)}   ▾")

    def _toggle(self):
        top = Dropdown._open_menu
        if top is not None:
            try:
                alive = bool(top.winfo_exists())
            except tk.TclError:
                alive = False
            Dropdown._close_menu()
            if alive:
                return
        self._open()

    @staticmethod
    def _close_menu():
        top = Dropdown._open_menu
        Dropdown._open_menu = None
        Dropdown._owner = None
        if top is not None:
            try:
                top.destroy()
            except tk.TclError:
                pass

    _owner = None
    _bound = False

    @staticmethod
    def _global_click(e):
        top = Dropdown._open_menu
        if top is None:
            return
        w = e.widget
        path = str(w)
        if path.startswith(str(top)) or w is Dropdown._owner:
            return            # clique no menu (escolhe a linha) ou no botao (faz toggle)
        Dropdown._close_menu()

    def _open(self):
        items = list(self._provider())
        root = self.winfo_toplevel()
        if not Dropdown._bound:
            root.bind_all("<ButtonPress-1>", Dropdown._global_click, add="+")
            root.bind_all("<Escape>", lambda _e: Dropdown._close_menu(), add="+")
            Dropdown._bound = True
        # o menu vive DENTRO da janela da app (nunca fica fora dela)
        top = tk.Frame(root, bg=C["accent"])             # 1px de contorno
        card = tk.Frame(top, bg=C["surface2"])
        card.pack(padx=1, pady=1)
        inner = tk.Frame(card, bg=C["surface2"])
        inner.pack(padx=P(4), pady=P(4))

        def pick(value):
            Dropdown._close_menu()
            self._on_pick(value)

        min_w = self.winfo_width() - P(8)
        for label, value in items:
            if label is None:
                tk.Frame(inner, bg=C["border"], height=1).pack(fill="x", padx=P(8), pady=P(4))
                continue
            text = tr(label).strip()
            current = label == self._text
            is_new = text.startswith("+")
            danger = value == ("del", None)
            fg = C["bad"] if danger else (C["accent"] if is_new else C["text"])
            row = tk.Frame(inner, bg=C["surface2"], cursor="hand2")
            row.pack(fill="x", pady=1)
            mark = tk.Label(row, text="●" if current else " ", bg=C["surface2"], fg=C["accent"],
                            font=F(7), width=2, cursor="hand2")
            mark.pack(side="left", padx=(P(6), 0))
            lbl = tk.Label(row, text=text, bg=C["surface2"], fg=fg, anchor="w",
                           font=F(self._size, "bold" if current else "normal"),
                           padx=P(4), pady=P(6), cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True, padx=(0, P(10)))
            widgets = (row, mark, lbl)

            def hover(on, ws=widgets):
                col = (C["surface3"] if on else C["surface2"])
                for w in ws:
                    w.config(bg=col)
            for w in widgets:
                w.bind("<Enter>", lambda _e, h=hover: h(True))
                w.bind("<Leave>", lambda _e, h=hover: h(False))
                w.bind("<ButtonRelease-1>", lambda _e, v=value: pick(v))

        top.update_idletasks()
        w = max(top.winfo_reqwidth(), min_w)
        h = top.winfo_reqheight()
        rw, rh = root.winfo_width(), root.winfo_height()
        x = self.winfo_rootx() - root.winfo_rootx()
        y = self.winfo_rooty() - root.winfo_rooty() + self.winfo_height() + P(4)
        x = max(P(4), min(x, rw - w - P(4)))
        if y + h > rh - P(4):                            # sem espaco em baixo: abre para cima
            y = max(P(4), self.winfo_rooty() - root.winfo_rooty() - h - P(4))
        top.place(x=x, y=y, width=w, height=h)
        top.lift()
        Dropdown._open_menu = top
        Dropdown._owner = self


def _rrect_pts(x1, y1, x2, y2, r):
    return _rrect(x1, y1, x2, y2, r)


class Segmented(tk.Canvas):
    """Grupo de opcoes exclusivas (filtros): pilula com a opcao ativa destacada."""

    def __init__(self, master, options, value=None, command=None, size=9, px=14, py=6, bg=None):
        import tkinter.font as tkfont
        self._track = bg or C["surface"]
        self._opts = list(options)
        self._cmd, self._value, self._size = command, None, size
        self._hover = None
        normal = tkfont.Font(master, font=F(size))
        bold = tkfont.Font(master, font=F(size, "bold"))
        self._gap = P(3)
        self._widths = [max(normal.measure(tr(o)), bold.measure(tr(o))) + 2 * P(px) for o in self._opts]
        self._h = bold.metrics("linespace") + 2 * P(py) + 2 * self._gap
        super().__init__(master, width=sum(self._widths) + 2 * self._gap, height=self._h,
                         bg=master.cget("bg"), highlightthickness=0, bd=0, cursor="hand2")
        self._font_n, self._font_b = F(size), F(size, "bold")
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _e: self._set_hover(None))
        self.select(value if value in self._opts else self._opts[0], False)

    def _index_at(self, x):
        pos = self._gap
        for i, w in enumerate(self._widths):
            if pos <= x < pos + w:
                return i
            pos += w
        return None

    def _click(self, e):
        i = self._index_at(e.x)
        if i is not None:
            self.select(self._opts[i], True)

    def _motion(self, e):
        self._set_hover(self._index_at(e.x))

    def _set_hover(self, i):
        if i != self._hover:
            self._hover = i
            self._draw()

    def select(self, value, fire=False):
        self._value = value
        self._draw()
        if fire and self._cmd:
            self._cmd(value)

    def get(self):
        return self._value

    def _draw(self):
        self.delete("all")
        w, h, g = int(self.cget("width")) - 1, self._h - 1, self._gap
        self.create_polygon(_rrect(0, 0, w, h, h // 2), smooth=True, fill=self._track,
                            outline=C["border"])
        x = g
        for i, opt in enumerate(self._opts):
            ow = self._widths[i]
            on = opt == self._value
            if on:
                self.create_polygon(_rrect(x, g, x + ow, h - g, (h - 2 * g) // 2), smooth=True,
                                    fill=C["accent"], outline=C["accent"])
            col = C["bg"] if on else (C["text"] if i == self._hover else C["muted"])
            self.create_text(x + ow / 2, h / 2 + 1, text=tr(opt), fill=col,
                             font=self._font_b if on else self._font_n)
            x += ow


class Tabs(tk.Canvas):
    """Separadores com sublinhado na ativa (navegacao entre paginas)."""

    def __init__(self, master, options, value=None, command=None, size=10, px=18, py=7, bg=None):
        import tkinter.font as tkfont
        self._opts = list(options)
        self._cmd, self._value, self._size, self._hover = command, None, size, None
        normal = tkfont.Font(master, font=F(size))
        bold = tkfont.Font(master, font=F(size, "bold"))
        self._widths = [max(normal.measure(tr(o)), bold.measure(tr(o))) + 2 * P(px) for o in self._opts]
        self._h = bold.metrics("linespace") + 2 * P(py) + P(4)
        super().__init__(master, width=sum(self._widths), height=self._h, bg=bg or master.cget("bg"),
                         highlightthickness=0, bd=0, cursor="hand2")
        self._font_n, self._font_b = F(size), F(size, "bold")
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Motion>", lambda e: self._set_hover(self._index_at(e.x)))
        self.bind("<Leave>", lambda _e: self._set_hover(None))
        self.bind("<Configure>", lambda _e: self._draw())
        self.select(value if value in self._opts else self._opts[0], False)

    def _index_at(self, x):
        pos = 0
        for i, w in enumerate(self._widths):
            if pos <= x < pos + w:
                return i
            pos += w
        return None

    def _click(self, e):
        i = self._index_at(e.x)
        if i is not None:
            self.select(self._opts[i], True)

    def _set_hover(self, i):
        if i != self._hover:
            self._hover = i
            self._draw()

    def select(self, value, fire=False):
        self._value = value
        self._draw()
        if fire and self._cmd:
            self._cmd(value)

    def get(self):
        return self._value

    def _draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), sum(self._widths)), self._h
        base = h - 1
        self.create_line(0, base, w, base, fill=C["border"])
        x = 0
        for i, opt in enumerate(self._opts):
            ow = self._widths[i]
            on = opt == self._value
            col = C["text"] if on else (C["text"] if i == self._hover else C["muted"])
            self.create_text(x + ow / 2, (h - P(4)) / 2 + 1, text=tr(opt), fill=col,
                             font=self._font_b if on else self._font_n)
            if on:
                t = max(2, P(3))
                self.create_polygon(_rrect(x + P(10), base - t, x + ow - P(10), base + 1, t // 2 + 1),
                                    smooth=True, fill=C["accent"], outline=C["accent"])
            x += ow


class SideNav(tk.Canvas):
    """Barra lateral: icones desenhados + nome; a pagina ativa tem cartao e barra de destaque."""

    ICON_BOX = 18

    def __init__(self, master, options, icons, value=None, command=None, width=200, caption_text="MENU"):
        self._opts, self._icons = list(options), list(icons)
        self._cmd, self._value, self._hover = command, None, None
        self._caption = caption_text
        self._item_h, self._gap, self._top = P(42), P(4), P(44)
        self._wpx = P(width)
        super().__init__(master, width=self._wpx, bg=C["surface"], highlightthickness=0, bd=0,
                         cursor="hand2")
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Motion>", lambda e: self._set_hover(self._index_at(e.x, e.y)))
        self.bind("<Leave>", lambda _e: self._set_hover(None))
        self.bind("<Configure>", lambda _e: self._draw())
        self.select(value if value in self._opts else self._opts[0], False)

    def _y(self, i):
        return self._top + i * (self._item_h + self._gap)

    def _index_at(self, x, y):
        for i in range(len(self._opts)):
            y0 = self._y(i)
            if P(10) <= x <= self._wpx - P(10) and y0 <= y <= y0 + self._item_h:
                return i
        return None

    def _click(self, e):
        i = self._index_at(e.x, e.y)
        if i is not None:
            self.select(self._opts[i], True)

    def _set_hover(self, i):
        if i != self._hover:
            self._hover = i
            self._draw()

    def select(self, value, fire=False):
        self._value = value
        self._draw()
        if fire and self._cmd:
            self._cmd(value)

    def get(self):
        return self._value

    def _icon(self, kind, cx, cy, col):
        u = P(1)
        lw = max(2, P(2))
        if kind == "live":
            self.create_oval(cx - 8 * u, cy - 8 * u, cx + 8 * u, cy + 8 * u, outline=col, width=lw)
            self.create_oval(cx - 3 * u, cy - 3 * u, cx + 3 * u, cy + 3 * u, fill=col, outline=col)
        elif kind == "history":
            for k, hh in enumerate((6, 11, 16)):
                x = cx - 9 * u + k * 7 * u
                self.create_rectangle(x, cy + 8 * u - hh * u, x + 4 * u, cy + 8 * u, fill=col, outline=col)
        elif kind == "coach":
            for r in (8, 4):
                self.create_oval(cx - r * u, cy - r * u, cx + r * u, cy + r * u, outline=col, width=lw)
            self.create_oval(cx - u, cy - u, cx + u, cy + u, fill=col, outline=col)
        elif kind == "replays":
            self.create_polygon(_rrect(cx - 9 * u, cy - 7 * u, cx + 9 * u, cy + 7 * u, 3 * u), smooth=True,
                                outline=col, fill="", width=lw)
            self.create_polygon(cx - 2 * u, cy - 3 * u, cx - 2 * u, cy + 3 * u, cx + 3 * u, cy,
                                fill=col, outline=col)
        else:  # settings: tres reguladores
            for k, kx in enumerate((-3, 4, -1)):
                y = cy + (k - 1) * 6 * u
                self.create_line(cx - 9 * u, y, cx + 9 * u, y, fill=col, width=lw)
                self.create_oval(cx + kx * u - 2.5 * u, y - 2.5 * u, cx + kx * u + 2.5 * u, y + 2.5 * u,
                                 fill=C["surface"], outline=col, width=lw)

    def _draw(self):
        self.delete("all")
        h = max(self.winfo_height(), 1)
        vgrad(self, 0, 0, self._wpx, h, _mix(C["surface"], C["accent"], 0.10), _mix(C["surface"], C["bg"], 0.55))
        self.create_line(self._wpx - 1, 0, self._wpx - 1, h, fill=C["border"])
        self.create_text(P(24), P(26), text=tr(self._caption), anchor="w", fill=C["dim"], font=F(8, "bold"))
        for i, opt in enumerate(self._opts):
            y0 = self._y(i)
            y1 = y0 + self._item_h
            on = opt == self._value
            hov = i == self._hover and not on
            if on or hov:
                self.create_polygon(_rrect(P(10), y0, self._wpx - P(12), y1, P(9)), smooth=True,
                                    fill=C["surface3"] if on else C["surface2"],
                                    outline=C["accent"] if on else C["surface2"])
                if on:   # brilho do acento a esvanecer para a direita
                    hgrad(self, P(14), y0 + 2, self._wpx - P(14), y1 - 2,
                          _mix(C["surface3"], C["accent"], 0.38), C["surface3"])
            if on:
                self.create_polygon(_rrect(P(10), y0 + P(10), P(14), y1 - P(10), P(2)), smooth=True,
                                    fill=C["accent"], outline=C["accent"])
            col = C["accent"] if on else (C["text"] if hov else C["muted"])
            self._icon(self._icons[i], P(34), (y0 + y1) / 2, col)
            self.create_text(P(56), (y0 + y1) / 2 + 1, text=tr(opt), anchor="w",
                             fill=C["text"] if on else (C["text"] if hov else C["muted"]),
                             font=F(10, "bold") if on else F(10))


class WrapLabel(tk.Label):
    """Label cujo wraplength acompanha a largura disponivel (a janela/pagina pode encolher)."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.bind("<Configure>", self._fit)

    def _fit(self, e):
        wl = max(P(100), e.width - P(6))
        if abs(wl - int(self.cget("wraplength") or 0)) > P(3):
            self.config(wraplength=wl)


class PageBanner(tk.Canvas):
    """Cabecalho da pagina: titulo + subtitulo sobre um brilho de acento."""

    def __init__(self, master, height=54):
        super().__init__(master, height=P(height), bg=C["bg"], highlightthickness=0, bd=0)
        self._title, self._sub = "", ""
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, title, sub=""):
        self._title, self._sub = title, sub
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        hgrad(self, 0, 0, w, h, _mix(C["bg"], C["accent"], 0.20), C["bg"])
        # aros decorativos a direita
        for k, r in enumerate((h * 1.6, h * 1.1, h * 0.65)):
            cx, cy = w - h * 0.9, h * 0.5
            self.create_oval(cx - r, cy - r, cx + r, cy + r,
                             outline=_mix(C["bg"], C["accent"], 0.14 - k * 0.03), width=1)
        hgrad(self, 0, h - 2, w, h, C["accent"], C["bg"])
        self.create_polygon(_rrect(0, P(12), P(4), h - P(14), P(2)), smooth=True,
                            fill=C["accent"], outline=C["accent"])
        self.create_text(P(20), h * 0.36, text=tr(self._title), anchor="w", fill=C["text"], font=F(15, "bold"))
        if self._sub:
            self.create_text(P(20), h * 0.75, text=tr(self._sub), anchor="w", fill=C["muted"], font=F(9))


class Switch(tk.Frame):
    """Interruptor com rotulo, ligado a uma tk.BooleanVar."""

    def __init__(self, master, text, variable, command=None, bg=None):
        super().__init__(master, bg=bg or C["surface"], cursor="hand2")
        self._var, self._cmd = variable, command
        self.w, self.h = P(34), P(18)
        self.cv = tk.Canvas(self, width=self.w, height=self.h, bg=self["bg"],
                            highlightthickness=0, bd=0, cursor="hand2")
        self.cv.pack(side="left")
        self.lbl = tk.Label(self, text=text, bg=self["bg"], fg=C["muted"], font=F(9),
                            cursor="hand2")
        self.lbl.pack(side="left", padx=(P(8), 0))
        for w in (self, self.cv, self.lbl):
            w.bind("<ButtonRelease-1>", self._toggle)
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _e=None):
        self._var.set(not self._var.get())
        if self._cmd:
            self._cmd()

    def _draw(self):
        on = bool(self._var.get())
        self.cv.delete("all")
        w, h = self.w, self.h
        track = C["accent"] if on else C["surface3"]
        r = h // 2
        self.cv.create_oval(0, 0, h, h, fill=track, outline=track)
        self.cv.create_oval(w - h, 0, w, h, fill=track, outline=track)
        self.cv.create_rectangle(r, 0, w - r, h, fill=track, outline=track)
        k = P(3)
        x = (w - h + k) if on else k
        self.cv.create_oval(x, k, x + h - 2 * k, h - k, fill=C["bg"] if on else C["muted"], outline="")
        self.lbl.config(fg=C["text"] if on else C["muted"])


class Pill(tk.Frame):
    """Estado com bolinha colorida."""

    def __init__(self, master, bg=None):
        super().__init__(master, bg=bg or C["surface2"], padx=P(12), pady=P(5),
                         highlightthickness=1, highlightbackground=C["border"])
        self.dot = tk.Canvas(self, width=P(10), height=P(10), bg=self["bg"], highlightthickness=0)
        self.dot.pack(side="left")
        self._d = self.dot.create_oval(1, 1, P(9), P(9), fill=C["muted"], outline="")
        self.lbl = tk.Label(self, text="", bg=self["bg"], fg=C["text"], font=F(9, "bold"))
        self.lbl.pack(side="left", padx=(P(7), 0))

    def set(self, text, color):
        self.dot.itemconfig(self._d, fill=color)
        self.lbl.config(text=text, fg=color)


class StatTile(tk.Frame):
    def __init__(self, master, caption, big=True, bg=None):
        super().__init__(master, bg=bg or C["surface"])
        self.val = tk.Label(self, text="0", bg=self["bg"], fg=C["text"],
                            font=F(22 if big else 15, "bold"), anchor="w")
        self.val.pack(anchor="w")
        tk.Label(self, text=caption.upper(), bg=self["bg"], fg=C["muted"],
                 font=F(7, "bold"), anchor="w").pack(anchor="w")

    def set(self, text, color=None):
        self.val.config(text=text, fg=color or C["text"])


class Bar(tk.Canvas):
    """Barra horizontal: um ou dois segmentos (ex. vitorias/derrotas)."""

    def __init__(self, master, height=6, bg=None, track=None):
        super().__init__(master, height=P(height), bg=bg or C["surface"],
                         highlightthickness=0, bd=0)
        self._track = track or C["surface3"]
        self._segs = []
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, segments):
        """segments: [(fracao 0..1, cor), ...] somando <= 1."""
        self._segs = segments
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 2:
            return
        self.create_rectangle(0, 0, w, h, fill=self._track, outline="")
        x = 0
        for frac, color in self._segs:
            nx = x + int(w * max(0.0, min(1.0, frac)))
            if nx > x:
                self.create_rectangle(x, 0, nx, h, fill=color, outline="")
            x = nx


def make_entry(master, width=16, bg=None):
    return tk.Entry(master, width=width, bg=bg or C["surface3"], fg=C["text"],
                    insertbackground=C["text"], relief="flat", bd=0, font=F(10),
                    highlightthickness=1, highlightbackground=C["border"],
                    highlightcolor=C["accent"])


def caption(master, text, color=None, bg=None, size=8):
    return tk.Label(master, text=text.upper(), bg=bg or master.cget("bg"),
                    fg=color or C["muted"], font=F(size, "bold"))
