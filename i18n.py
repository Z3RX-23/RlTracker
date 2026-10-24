"""
i18n.py

Idiomas da interface (pt = original, en = ingles).

Os textos do codigo estao em portugues e servem de chave. Em ingles:
  * textos dinamicos (com numeros): tr("... {n} ...", n=3)
  * textos fixos de widgets (Label/Button/...): traduzidos de forma
    automatica por um filtro no Tk (install_tk_hook), sem mexer nas chamadas.

Se uma chave nao existir no dicionario, mostra-se o texto em portugues
(nunca falha). Em portugues nada e' alterado.
"""

import os
import tkinter as tk

LANGUAGES = {"pt": "Português", "en": "English"}

_lang = "pt"
_EN = None
_installed = False
_seen = set()          # so' para o modo de gravacao (RL_I18N_RECORD)


def _load_en():
    global _EN
    if _EN is None:
        try:
            from i18n_en import EN
            _EN = EN
        except ImportError:
            _EN = {}
    return _EN


def set_language(code):
    global _lang
    _lang = code if code in LANGUAGES else "pt"
    if _lang != "pt":
        _load_en()
        install_tk_hook()


def get_language():
    return _lang


def tr(pt, **kw):
    """Texto na lingua atual; kw preenche os {campos}."""
    s = pt
    if _lang != "pt":
        s = _load_en().get(pt, pt)
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            return pt.format(**kw)
    return s


def _tx(value):
    """Traduz um valor de 'text' vindo de um widget (so' se for chave conhecida)."""
    if not isinstance(value, str) or not value:
        return value
    if os.environ.get("RL_I18N_RECORD"):
        _seen.add(value)
    if _lang == "pt":
        return value
    return _load_en().get(value, value)


def install_tk_hook():
    """Filtra a opcao 'text' de todos os widgets Tk classicos."""
    global _installed
    if _installed:
        return
    _installed = True
    orig = tk.Misc._options

    def patched(self, cnf, kw=None):
        if isinstance(cnf, dict) and isinstance(kw, dict) and kw:
            cnf, kw = dict(cnf, **kw), None
        elif cnf is None or not cnf:
            cnf, kw = (dict(kw) if isinstance(kw, dict) else cnf), None
        if isinstance(cnf, dict) and isinstance(cnf.get("text"), str):
            cnf = dict(cnf)
            cnf["text"] = _tx(cnf["text"])
        return orig(self, cnf, kw)

    tk.Misc._options = patched


def record_hook():
    """Modo de desenvolvimento: guarda todos os textos vistos (RL_I18N_RECORD=1)."""
    install_tk_hook()


def dump_seen(path):
    with open(path, "w", encoding="utf-8") as f:
        for s in sorted(_seen):
            f.write(s.replace("\n", "\\n") + "\n")
