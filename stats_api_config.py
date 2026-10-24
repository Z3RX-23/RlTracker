#!/usr/bin/env python3
"""
stats_api_config.py

Deteta a pasta de instalacao do Rocket League (Steam / Epic) e garante que
o ficheiro TAGame\\Config\\DefaultStatsAPI.ini tem a Stats API ativada.

Porque existe: um update do jogo (ou "verificar ficheiros" no Steam/Epic)
repoe o ficheiro original e apaga a secao [TAGame.MatchStatsExporter_TA].
Sem ela o jogo nao abre o socket e a app fica em "API desativada".

Uso (linha de comando):
    python stats_api_config.py            # so verifica
    python stats_api_config.py --fix      # verifica e repara

NOTA: o jogo so le este ficheiro no arranque -- depois de uma reparacao
e' preciso fechar e voltar a abrir o Rocket League.

Opcional (config.ini ao lado da app):
    [game]
    install_dir = D:\\Jogos\\rocketleague
"""

import glob
import json
import os
import re
import sys

from i18n import tr

SECTION = "TAGame.MatchStatsExporter_TA"
INI_RELPATH = os.path.join("TAGame", "Config", "DefaultStatsAPI.ini")
DEFAULT_PORT = 49123
DEFAULT_RATE = 10

# Estados devolvidos por check()
OK = "ok"                  # secao presente e valida
NEEDS_FIX = "needs_fix"    # ficheiro existe mas config ausente/invalida
NOT_FOUND = "not_found"    # nao foi possivel localizar o jogo/ficheiro


# --------------------------------------------------------------------------- #
# Localizar a instalacao
# --------------------------------------------------------------------------- #

def _steam_roots():
    roots = []
    try:
        import winreg
        for hive, key, val in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    path, _ = winreg.QueryValueEx(k, val)
                    if path:
                        roots.append(os.path.normpath(path))
            except OSError:
                pass
    except ImportError:
        pass
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if base:
            roots.append(os.path.join(base, "Steam"))
    return roots


def _steam_candidates():
    out = []
    for root in _steam_roots():
        libs = [root]
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                text = f.read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                libs.append(m.group(1).replace("\\\\", "\\"))
        except OSError:
            pass
        for lib in libs:
            out.append(os.path.join(lib, "steamapps", "common", "rocketleague"))
    return out


def _epic_candidates():
    out = []
    base = os.environ.get("ProgramData", r"C:\ProgramData")
    pattern = os.path.join(base, "Epic", "EpicGamesLauncher", "Data", "Manifests", "*.item")
    for item in glob.glob(pattern):
        try:
            with open(item, encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        name = str(data.get("DisplayName", "")) + " " + str(data.get("AppName", ""))
        if "rocket league" in name.lower() or "sugar" in name.lower():
            loc = data.get("InstallLocation")
            if loc:
                out.append(loc)
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        b = os.environ.get(env)
        if b:
            out.append(os.path.join(b, "Epic Games", "rocketleague"))
    return out


def find_ini_paths(extra_dir=None):
    """Devolve a lista (sem repetidos) de DefaultStatsAPI.ini existentes.
    Pode haver mais do que um (ex.: Steam e Epic instalados)."""
    dirs = []
    if extra_dir:
        dirs.append(extra_dir)
    dirs += _steam_candidates() + _epic_candidates()
    found, seen = [], set()
    for d in dirs:
        p = os.path.normpath(os.path.join(d, INI_RELPATH))
        key = os.path.normcase(p)
        if key not in seen and os.path.isfile(p):
            seen.add(key)
            found.append(p)
    return found


# --------------------------------------------------------------------------- #
# Ler / validar / reparar (edicao textual -- nao usa configparser para nao
# mexer em comentarios, maiusculas nem chaves repetidas do resto do ficheiro)
# --------------------------------------------------------------------------- #

def _read(path):
    with open(path, "rb") as f:
        raw = f.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig", errors="replace")
    nl = "\r\n" if "\r\n" in text else "\n"
    return text, nl, bom


def _section_bounds(lines):
    """(inicio, fim) das linhas do corpo da secao, ou None."""
    start = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            if start is not None:
                return start, i
            if s[1:-1].strip().lower() == SECTION.lower():
                start = i + 1
    return (start, len(lines)) if start is not None else None


def _get_value(lines, bounds, key):
    if bounds is None:
        return None
    for ln in lines[bounds[0]:bounds[1]]:
        m = re.match(r"\s*([^=;#\s]+)\s*=\s*(.*?)\s*$", ln)
        if m and m.group(1).lower() == key.lower():
            return m.group(2)
    return None


def check_file(path, port=DEFAULT_PORT):
    """OK se PacketSendRate > 0 e Port == port; senao NEEDS_FIX."""
    text, _, _ = _read(path)
    lines = text.splitlines()
    b = _section_bounds(lines)
    rate = _get_value(lines, b, "PacketSendRate")
    p = _get_value(lines, b, "Port")
    try:
        if rate is not None and float(rate) > 0 and p is not None and int(p) == port:
            return OK
    except ValueError:
        pass
    return NEEDS_FIX


def repair_file(path, port=DEFAULT_PORT, rate=DEFAULT_RATE):
    """Garante a secao e as duas chaves, preservando o resto do ficheiro.
    Levanta PermissionError/OSError se nao conseguir escrever."""
    text, nl, bom = _read(path)
    lines = text.splitlines()
    wanted = {"PacketSendRate": str(rate), "Port": str(port)}

    b = _section_bounds(lines)
    if b is None:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines.append(f"[{SECTION}]")
        lines += [f"{k}={v}" for k, v in wanted.items()]
    else:
        start, end = b
        pending = dict(wanted)
        for i in range(start, end):
            m = re.match(r"(\s*)([^=;#\s]+)(\s*=\s*)(.*)$", lines[i])
            if m:
                for k in list(pending):
                    if m.group(2).lower() == k.lower():
                        val = pending.pop(k)
                        # Mantem um PacketSendRate valido (>0) que o utilizador
                        # ja tenha escolhido (ex.: 30).
                        if k == "PacketSendRate":
                            try:
                                if 0 < float(m.group(4).strip()) <= 120:
                                    val = m.group(4).strip()
                            except ValueError:
                                pass
                        lines[i] = f"{m.group(1)}{k}={val}"
        insert_at = end
        while insert_at > start and not lines[insert_at - 1].strip():
            insert_at -= 1
        for k, v in pending.items():
            lines.insert(insert_at, f"{k}={v}")
            insert_at += 1

    data = (nl.join(lines) + nl).encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data

    # Ficheiro so-de-leitura (comum em quem tentou "proteger" a config)
    try:
        import stat
        mode = os.stat(path).st_mode
        if not mode & stat.S_IWRITE:
            os.chmod(path, mode | stat.S_IWRITE)
    except OSError:
        pass
    tmp = path + ".rltracker.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# API de alto nivel (usada pela GUI)
# --------------------------------------------------------------------------- #

def check(extra_dir=None, port=DEFAULT_PORT):
    """Devolve (estado, [paths]). estado: OK / NEEDS_FIX / NOT_FOUND.
    NEEDS_FIX se pelo menos um ficheiro encontrado precisar de reparacao."""
    paths = find_ini_paths(extra_dir)
    if not paths:
        return NOT_FOUND, []
    bad = [p for p in paths if check_file(p, port) != OK]
    return (NEEDS_FIX if bad else OK), (bad or paths)


def repair(extra_dir=None, port=DEFAULT_PORT):
    """Repara todos os ficheiros que precisem. Devolve (reparados, erros)
    onde erros e' uma lista de (path, mensagem)."""
    fixed, errors = [], []
    for p in find_ini_paths(extra_dir):
        try:
            if check_file(p, port) != OK:
                repair_file(p, port)
                fixed.append(p)
        except PermissionError:
            errors.append((p, tr("sem permissões -- corre a app como administrador "
                                   "(a pasta do jogo está em Program Files)")))
        except OSError as e:
            errors.append((p, str(e)))
    return fixed, errors


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    state, paths = check()
    if state == NOT_FOUND:
        print("Nao encontrei o DefaultStatsAPI.ini (Steam/Epic). "
              "Define [game] install_dir no config.ini.")
        return 2
    for p in paths:
        print(("OK        " if state == OK else "A REPARAR ") + p)
    if state == NEEDS_FIX and "--fix" in argv:
        fixed, errors = repair()
        for p in fixed:
            print("Reparado: " + p + "  (reinicia o Rocket League)")
        for p, msg in errors:
            print("ERRO: " + p + " -- " + msg)
        return 1 if errors else 0
    return 0 if state == OK else 1


if __name__ == "__main__":
    sys.exit(main())
