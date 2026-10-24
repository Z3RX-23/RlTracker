"""
tray.py

Icone na bandeja do sistema (opcional): precisa de `pystray` e `Pillow`.
Se faltarem, available() devolve False e a app funciona sem bandeja.

As acoes do menu correm noutra thread: so' poem pedidos numa fila
(poll() e' lido pelo Tk), nunca mexem na interface diretamente.
"""

import queue

try:
    import pystray
    from PIL import Image, ImageDraw
    _OK = True
except Exception:       # falta o pacote ou o sistema nao tem bandeja
    pystray = None
    _OK = False


def available():
    return _OK


def _image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(17, 24, 48, 255))
    d.pieslice((12, 12, 52, 52), 90, 270, fill=(77, 141, 255, 255))
    d.pieslice((12, 12, 52, 52), 270, 450, fill=(255, 138, 61, 255))
    return img


class Tray:
    def __init__(self, show_label="Mostrar", quit_label="Sair", title="RL Live"):
        self._q = queue.Queue()
        self._icon = None
        self._labels = (show_label, quit_label)
        self._title = title

    def start(self):
        if not _OK or self._icon is not None:
            return self._icon is not None
        menu = pystray.Menu(
            pystray.MenuItem(self._labels[0], lambda *_: self._q.put("show"), default=True),
            pystray.MenuItem(self._labels[1], lambda *_: self._q.put("quit")))
        try:
            self._icon = pystray.Icon("rl_live", _image(), self._title, menu)
            self._icon.run_detached()
        except Exception:
            self._icon = None
            return False
        return True

    def active(self):
        return self._icon is not None

    def set_title(self, text):
        if self._icon is not None:
            try:
                self._icon.title = text[:120]
            except Exception:
                pass

    def poll(self):
        out = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                return out

    def stop(self):
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
