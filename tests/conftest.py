"""Configuracao dos testes: poe a pasta do projeto no path."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

pytest.importorskip("tkinter")        # i18n/ui_kit importam o Tk (so' os modulos, sem janela)
