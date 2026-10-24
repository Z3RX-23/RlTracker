"""
maintenance.py

Copias de seguranca dos dados, exportacao e "so' uma instancia" da app.
Sem interface: usado por app.py e settings_page.py (e testado em tests/).

Nunca entram chaves de API (ballchasing.json, ai.json).
"""

import os
import socket
import sqlite3
import tempfile
import threading
import time
import zipfile

# (ficheiro, descricao, contem chaves)
DATA_FILES = [
    ("profiles.json", "Perfis", False),
    ("history.db", "Histórico de partidas", False),
    ("replays.db", "Replays analisados", False),
    ("settings.json", "Definições gerais", False),
    ("ballchasing.json", "Ballchasing (contém a chave)", True),
    ("ai.json", "Serviço de IA (contém a chave)", True),
]

BACKUP_PREFIX = "rl_backup_"


def write_zip(zip_path, base_dir):
    """Escreve os dados sem chaves num zip. Devolve a lista de ficheiros incluidos."""
    done = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, _desc, secret in DATA_FILES:
            src = os.path.join(base_dir, name)
            if secret or not os.path.exists(src):
                continue
            if name.endswith(".db"):
                # copia consistente mesmo com a app a escrever
                with tempfile.TemporaryDirectory() as tmp:
                    dst = os.path.join(tmp, name)
                    try:
                        a = sqlite3.connect(src)
                        b = sqlite3.connect(dst)
                        with b:
                            a.backup(b)
                        b.close()
                        a.close()
                        z.write(dst, name)
                    except sqlite3.Error:
                        z.write(src, name)
            else:
                z.write(src, name)
            done.append(name)
    return done


def backup_path(folder, day=None):
    return os.path.join(folder, BACKUP_PREFIX + (day or time.strftime("%Y-%m-%d")) + ".zip")


def list_backups(folder):
    try:
        names = [n for n in os.listdir(folder) if n.startswith(BACKUP_PREFIX) and n.endswith(".zip")]
    except OSError:
        return []
    return sorted(names)


def backup_due(folder):
    """True se ainda nao ha' copia de hoje."""
    return not os.path.exists(backup_path(folder))


def make_backup(base_dir, folder, keep):
    """Cria a copia de hoje e apaga as mais antigas. Devolve (caminho, ficheiros)."""
    os.makedirs(folder, exist_ok=True)
    path = backup_path(folder)
    tmp = path + ".tmp"
    files = write_zip(tmp, base_dir)
    os.replace(tmp, path)
    old = list_backups(folder)
    for name in old[:max(0, len(old) - max(1, keep))]:
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass
    return path, files


def run_backup_async(base_dir, folder, keep, callback=None):
    """Faz a copia numa thread; callback(path_ou_None, erro_ou_None) na thread de fundo."""
    def work():
        try:
            path, _ = make_backup(base_dir, folder, keep)
            if callback:
                callback(path, None)
        except Exception as e:          # disco cheio, pasta sem permissoes, ...
            if callback:
                callback(None, str(e))
    threading.Thread(target=work, daemon=True).start()


# ── Uma so' instancia ────────────────────────────────────────────────────────

class SingleInstance:
    """Trinco numa porta local. A 2.a instancia avisa a 1.a ("show") e sai."""

    def __init__(self, port=49199):
        self.port = port
        self._sock = None
        self._shows = 0
        self._lock = threading.Lock()

    def acquire(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":      # (no Windows isto permitiria 2 donos da mesma porta)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", self.port))
            s.listen(2)
        except OSError:
            s.close()
            self._notify_other()
            return False
        self._sock = s
        threading.Thread(target=self._serve, args=(s,), daemon=True).start()
        return True

    def _notify_other(self):
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1) as c:
                c.sendall(b"show")
        except OSError:
            pass

    def _serve(self, sock):
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            try:
                conn.settimeout(1)
                if conn.recv(8) == b"show":
                    with self._lock:
                        self._shows += 1
            except OSError:
                pass
            finally:
                conn.close()

    def take_show_request(self):
        with self._lock:
            n, self._shows = self._shows, 0
        return n > 0

    def release(self):
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)      # acorda o accept() da thread
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
