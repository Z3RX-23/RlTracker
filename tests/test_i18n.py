import ast
import glob
import os
import re

import i18n
from i18n_en import EN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIELDS = re.compile(r"\{(\w+)")


def _tr_keys():
    keys = {}
    for f in glob.glob(os.path.join(ROOT, "*.py")):
        if os.path.basename(f) in ("i18n.py", "i18n_en.py", "history_window.py"):
            continue
        tree = ast.parse(open(f, encoding="utf-8").read())
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr"
                    and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                keys[n.args[0].value] = os.path.basename(f)
    return keys


def test_every_tr_key_has_english():
    missing = {k: f for k, f in _tr_keys().items() if k not in EN}
    assert not missing, missing


def test_placeholders_match():
    bad = [k for k, v in EN.items() if set(FIELDS.findall(k)) != set(FIELDS.findall(v))]
    assert not bad, bad


def test_tr_fallback_and_format():
    i18n.set_language("pt")
    assert i18n.tr("{n} jogos", n=3) == "3 jogos"
    i18n.set_language("en")
    try:
        assert i18n.tr("{n} jogos", n=3) == "3 games"
        assert i18n.tr("texto sem traducao") == "texto sem traducao"
    finally:
        i18n.set_language("pt")
