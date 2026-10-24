"""
history.py

Historico persistente das partidas contadas (SQLite, biblioteca padrao).
Cada partida que entra na sessao e' gravada em history.db, ao lado da
app/.exe, com o perfil, o modo (1v1/2v2/3v3), o resultado e as stats do
jogador. Serve a janela "Historico" e o export CSV.

O modo e' inferido pelo tamanho das equipas -- a Stats API nao diz a
playlist, por isso nao distingue ranked de casual (nem modos extra como
Hoops ou Rumble, que aparecem como 2v2/3v3).
"""

import csv
import os
import sqlite3
import sys
import threading

if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

HISTORY_PATH = os.path.join(_BASE_DIR, "history.db")

MODES = ["duel", "doubles", "standard", "other"]
MODE_LABELS = {"duel": "1v1", "doubles": "2v2", "standard": "3v3", "other": "Outro"}


def mode_from_team_size(size):
    return {1: "duel", 2: "doubles", 3: "standard"}.get(size, "other")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,      -- hora local, 'YYYY-MM-DD HH:MM:SS'
    profile_id   TEXT,
    profile_name TEXT,
    platform     TEXT,
    mode         TEXT NOT NULL,
    won          INTEGER NOT NULL,
    estimated    INTEGER NOT NULL DEFAULT 0,
    my_score     INTEGER,
    opp_score    INTEGER,
    goals        INTEGER NOT NULL DEFAULT 0,
    assists      INTEGER NOT NULL DEFAULT 0,
    saves        INTEGER NOT NULL DEFAULT 0,
    shots        INTEGER NOT NULL DEFAULT 0,
    demos        INTEGER NOT NULL DEFAULT 0,
    score        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_matches_ts ON matches(ts);
CREATE INDEX IF NOT EXISTS idx_matches_profile ON matches(profile_id);
"""

_FIELDS = ["ts", "profile_id", "profile_name", "platform", "mode", "won",
           "estimated", "my_score", "opp_score", "goals", "assists", "saves",
           "shots", "demos", "score"]


class MatchHistory:
    def __init__(self, path=HISTORY_PATH):
        self.path = path
        self._lock = threading.Lock()
        try:
            with self._conn() as c:
                c.executescript(_SCHEMA)
        except (sqlite3.Error, OSError):
            pass  # sem historico (ex. pasta sem permissoes) -- a app continua

    def _conn(self):
        # Uma ligacao por operacao: o core escreve numa thread e a GUI le
        # noutra, e assim nao ha' problemas de threads do sqlite3.
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- escrita -----------------------------------------------------------

    def add_match(self, rec):
        """Grava uma partida. Devolve True se gravou."""
        row = {k: rec.get(k) for k in _FIELDS}
        row["won"] = int(bool(row["won"]))
        row["estimated"] = int(bool(row["estimated"]))
        for k in ("goals", "assists", "saves", "shots", "demos", "score"):
            row[k] = int(row[k] or 0)
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    f"INSERT INTO matches ({','.join(_FIELDS)}) "
                    f"VALUES ({','.join('?' * len(_FIELDS))})",
                    [row[k] for k in _FIELDS])
            return True
        except (sqlite3.Error, OSError):
            return False

    # ---- leitura -----------------------------------------------------------

    @staticmethod
    def _where(profile_id, since, mode=None):
        clauses, args = [], []
        if profile_id:
            clauses.append("profile_id = ?"); args.append(profile_id)
        if since:
            clauses.append("ts >= ?"); args.append(since)
        if mode:
            clauses.append("mode = ?"); args.append(mode)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", args

    def summary(self, profile_id=None, since=None):
        """Dict modo -> agregados, com a chave extra 'total'. Modos sem
        partidas nao aparecem (exceto 'total', que existe sempre)."""
        where, args = self._where(profile_id, since)
        out = {}
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT mode, COUNT(*) n, SUM(won) wins, SUM(goals) goals, "
                    "SUM(assists) assists, SUM(saves) saves, SUM(shots) shots, "
                    "SUM(demos) demos, SUM(score) score FROM matches"
                    + where + " GROUP BY mode", args).fetchall()
        except (sqlite3.Error, OSError):
            rows = []
        total = dict(n=0, wins=0, goals=0, assists=0, saves=0, shots=0,
                     demos=0, score=0)
        for r in rows:
            d = {k: (r[k] or 0) for k in total}
            out[r["mode"]] = self._finish(d)
            for k in total:
                total[k] += d[k]
        out["total"] = self._finish(total)
        return out

    @staticmethod
    def _finish(d):
        n = d["n"]
        d["losses"] = n - d["wins"]
        d["win_pct"] = (100.0 * d["wins"] / n) if n else 0.0
        for k in ("goals", "assists", "saves", "shots", "score"):
            d[k + "_avg"] = (d[k] / n) if n else 0.0
        d["accuracy"] = (100.0 * d["goals"] / d["shots"]) if d["shots"] else 0.0
        return d

    def recent(self, profile_id=None, since=None, mode=None, limit=100):
        where, args = self._where(profile_id, since, mode)
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT * FROM matches" + where +
                    " ORDER BY ts DESC, id DESC LIMIT ?", args + [limit]).fetchall()
            return [dict(r) for r in rows]
        except (sqlite3.Error, OSError):
            return []

    def count(self):
        try:
            with self._conn() as c:
                return c.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        except (sqlite3.Error, OSError):
            return 0

    def export_csv(self, path, profile_id=None, since=None, mode=None):
        """Exporta (mais antigo primeiro) para CSV com ';' e UTF-8 com BOM,
        para abrir bem no Excel em portugues. Devolve o n.º de linhas."""
        rows = list(reversed(self.recent(profile_id, since, mode, limit=10**9)))
        cols = ["ts", "profile_name", "platform", "mode", "won", "estimated",
                "my_score", "opp_score", "goals", "assists", "saves", "shots",
                "demos", "score"]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["data", "perfil", "plataforma", "modo", "vitoria",
                        "estimativa", "golos_equipa", "golos_adversario",
                        "golos", "assistencias", "defesas", "remates",
                        "demos", "pontos"])
            for r in rows:
                w.writerow([MODE_LABELS.get(r[c], r[c]) if c == "mode" else r[c]
                            for c in cols])
        return len(rows)
