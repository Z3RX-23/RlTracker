"""
ballchasing.py

Integracao com o ballchasing.com: envia os teus replays (.replay) para a
conta, espera que sejam processados, vai buscar as stats (boost,
posicionamento, posse...) e guarda as tuas num SQLite local (replays.db).

Ficheiros (ao lado da app/.exe):
  ballchasing.json  -- definicoes (chave da API, pasta de replays, ...)
  replays.db        -- ficheiros ja' tratados e stats extraidas

So' usa a biblioteca padrao. A chave da API fica em texto simples no
ballchasing.json: nao partilhes esse ficheiro.
"""

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from i18n import tr

if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_PATH = os.path.join(_BASE_DIR, "ballchasing.json")
DB_PATH = os.path.join(_BASE_DIR, "replays.db")
BASE_URL = "https://ballchasing.com"
USER_AGENT = "RL-Live-Dashboard/1.0"

SINCE_OPTIONS = ["Só novos", "7 dias", "30 dias", "Tudo"]
VISIBILITIES = ["private", "unlisted", "public"]
VISIBILITY_LABELS = {"private": "Privado", "unlisted": "Não listado", "public": "Público"}

SYNC_INTERVAL = 60        # s entre varrimentos automaticos
STABLE_SECONDS = 8        # o replay so' conta quando o ficheiro parou de crescer
POLL_EVERY = 4            # s entre verificacoes do processamento
POLL_TIMEOUT = 240        # s a esperar pelo processamento


def default_replay_dir():
    home = os.path.expanduser("~")
    rel = os.path.join("My Games", "Rocket League", "TAGame", "Demos")
    cands = [os.path.join(home, "Documents", rel)]
    for var in ("OneDrive", "OneDriveConsumer"):
        if os.environ.get(var):
            cands.append(os.path.join(os.environ[var], "Documents", rel))
    cands.append(os.path.join(home, "OneDrive", "Documents", rel))
    for c in cands:
        if os.path.isdir(c):
            return c
    return cands[0]


# ── Definicoes ───────────────────────────────────────────────────────────────

class Settings:
    def __init__(self, path=SETTINGS_PATH):
        self.path = path
        self.lock = threading.RLock()
        self.token = ""
        self.replay_dirs = [default_replay_dir()]
        self.visibility = "private"
        self.auto = False
        self.since = "7 dias"
        self.enabled_since = time.time()     # para "Só novos"
        self.last_error = None
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(d, dict):
            return
        self.token = str(d.get("token", "")).strip()
        dirs = d.get("replay_dirs")
        if not isinstance(dirs, list):
            dirs = [d.get("replay_dir")]          # formato antigo (uma pasta)
        dirs = [x.strip() for x in dirs if isinstance(x, str) and x.strip()]
        if dirs or "replay_dirs" in d:
            self.replay_dirs = list(dict.fromkeys(dirs))
        self.visibility = d.get("visibility") if d.get("visibility") in VISIBILITIES else "private"
        self.auto = bool(d.get("auto", False))
        self.since = d.get("since") if d.get("since") in SINCE_OPTIONS else "7 dias"
        try:
            self.enabled_since = float(d.get("enabled_since", self.enabled_since))
        except (TypeError, ValueError):
            pass

    def save(self):
        with self.lock:
            text = json.dumps({
                "token": self.token, "replay_dirs": self.replay_dirs,
                "visibility": self.visibility, "auto": self.auto, "since": self.since,
                "enabled_since": self.enabled_since}, ensure_ascii=False, indent=2)
            self.last_error = None
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(tmp, self.path)
                return True
            except OSError:
                pass
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.write(text)
                return True
            except OSError as e:
                self.last_error = f"{self.path}: {e}"
                return False

    def cutoff(self):
        """Timestamp minimo (mtime) dos replays a enviar."""
        if self.since == "Só novos":
            return self.enabled_since
        days = {"7 dias": 7, "30 dias": 30}.get(self.since)
        return time.time() - days * 86400 if days else 0.0


# ── Cliente HTTP ─────────────────────────────────────────────────────────────

class BallchasingError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, token, base=None):
        self.token = token.strip()
        self.base = (base or os.environ.get("BALLCHASING_URL") or BASE_URL).rstrip("/")

    def _request(self, method, path, body=None, headers=None, timeout=60):
        if not self.token:
            raise BallchasingError(tr("Falta a chave da API."), 401)
        h = {"Authorization": self.token, "User-Agent": USER_AGENT}
        h.update(headers or {})
        for attempt in range(4):
            req = urllib.request.Request(self.base + path, data=body, method=method, headers=h)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.status, self._json(r.read())
            except urllib.error.HTTPError as e:
                data = self._json(e.read())
                if e.code == 429 and attempt < 3:
                    try:
                        wait = float(e.headers.get("Retry-After", "5"))
                    except ValueError:
                        wait = 5.0
                    time.sleep(min(max(wait, 1.0), 30.0))
                    continue
                return e.code, data
            except (urllib.error.URLError, OSError) as e:
                raise BallchasingError(tr("Sem ligação ao Ballchasing: {r}", r=getattr(e, 'reason', e)))
        return 429, {"error": "demasiados pedidos"}

    @staticmethod
    def _json(raw):
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, AttributeError):
            return {}

    @staticmethod
    def _err(status, data):
        msg = data.get("error") if isinstance(data, dict) else None
        if status == 401:
            return tr("Chave da API inválida (401).")
        return f"{msg or tr('erro')} ({status})"

    def ping(self):
        status, data = self._request("GET", "/api/")
        if status != 200:
            raise BallchasingError(self._err(status, data), status)
        return data

    def upload(self, path, visibility="private"):
        """Devolve o id do replay (tambem quando ja' existia: 409)."""
        boundary = "----rl" + uuid.uuid4().hex
        with open(path, "rb") as f:
            payload = f.read()
        name = os.path.basename(path).replace('"', "")
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
        status, data = self._request(
            "POST", "/api/v2/upload?" + urllib.parse.urlencode({"visibility": visibility}),
            body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=120)
        if status in (201, 409) and isinstance(data, dict) and data.get("id"):
            return data["id"]
        raise BallchasingError(self._err(status, data), status)

    def get_replay(self, rid):
        status, data = self._request("GET", "/api/replays/" + urllib.parse.quote(rid))
        if status != 200:
            raise BallchasingError(self._err(status, data), status)
        return data

    def wait_ready(self, rid, stop=None):
        deadline = time.time() + POLL_TIMEOUT
        while True:
            data = self.get_replay(rid)
            st = data.get("status", "ok")
            if st == "ok":
                return data
            if st == "failed":
                raise BallchasingError(tr("o Ballchasing não conseguiu processar este replay"))
            if time.time() > deadline or (stop and stop.is_set()):
                return None                # fica 'uploaded' e tenta-se na proxima vez
            time.sleep(POLL_EVERY)


# ── Extracao das stats ───────────────────────────────────────────────────────

PLATFORM_KEYS = {"steam": "steam", "epic": "epic"}


def _num(d, group, key):
    v = ((d or {}).get("stats") or {}).get(group, {})
    v = v.get(key) if isinstance(v, dict) else None
    return v if isinstance(v, (int, float)) else None


def find_my_player(replay, profile):
    """(equipa, jogador) do perfil no replay, ou None. Compara o nome sem
    distinguir maiusculas e, se o perfil tiver plataforma, tambem essa."""
    ids = {x.lower() for x in getattr(profile, "replay_ids", [])}
    if ids:
        for team in ("blue", "orange"):
            for pl in (replay.get(team) or {}).get("players") or []:
                i = pl.get("id") or {}
                if f"{i.get('platform', '')}:{i.get('id', '')}".lower() in ids:
                    return team, pl
    name = (profile.name or "").strip().casefold()
    if not name:
        return None
    want = PLATFORM_KEYS.get(profile.platform)
    for team in ("blue", "orange"):
        for pl in (replay.get(team) or {}).get("players") or []:
            if str(pl.get("name", "")).strip().casefold() != name:
                continue
            plat = ((pl.get("id") or {}).get("platform") or "").lower()
            if want and plat and plat != want:
                continue
            return team, pl
    return None


def extract(replay, profile):
    """Dict plano com as stats do jogador, ou None se ele nao estiver no replay."""
    found = find_my_player(replay, profile)
    if not found:
        return None
    team, pl = found
    other = "orange" if team == "blue" else "blue"
    out = {}
    fields = [
        ("boost", ["bpm", "bcpm", "avg_amount", "percent_zero_boost", "percent_full_boost",
                   "amount_collected", "amount_stolen", "amount_overfill"]),
        ("movement", ["avg_speed", "percent_ground", "percent_low_air", "percent_high_air",
                      "percent_supersonic_speed", "percent_boost_speed", "percent_slow_speed"]),
        ("positioning", ["avg_distance_to_ball", "percent_defensive_third",
                         "percent_neutral_third", "percent_offensive_third",
                         "percent_behind_ball", "percent_infront_ball",
                         "percent_most_back", "percent_most_forward",
                         "percent_closest_to_ball", "percent_farthest_from_ball"]),
        ("demo", ["inflicted", "taken"]),
        ("core", ["shots", "goals", "saves", "assists", "score", "shooting_percentage"]),
    ]
    for group, keys in fields:
        for k in keys:
            v = _num(pl, group, k)
            if v is not None:
                out[k if group != "demo" else "demo_" + k] = v

    # posse de bola: tempo da equipa com a bola / total
    mine = _num_team(replay, team, "possession_time")
    theirs = _num_team(replay, other, "possession_time")
    if mine is not None and theirs is not None and mine + theirs > 0:
        out["possession_pct"] = 100.0 * mine / (mine + theirs)

    goals = {}
    for t in ("blue", "orange"):
        g = [_num(p, "core", "goals") for p in (replay.get(t) or {}).get("players") or []]
        goals[t] = sum(x for x in g if x is not None) if any(x is not None for x in g) else None
    won = None
    if goals["blue"] is not None and goals["orange"] is not None and goals["blue"] != goals["orange"]:
        won = int(goals[team] > goals[other])
    return {"won": won, "data": out}


def _num_team(replay, team, key):
    ball = (((replay.get(team) or {}).get("stats") or {}).get("ball") or {})
    v = ball.get(key)
    return v if isinstance(v, (int, float)) else None


# ── Armazenamento ────────────────────────────────────────────────────────────

class ReplayStore:
    def __init__(self, path=DB_PATH):
        self.path = path
        self.lock = threading.RLock()
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        try:
            with self._conn() as c:
                c.executescript("""
                CREATE TABLE IF NOT EXISTS files(
                    path TEXT PRIMARY KEY, mtime REAL, bc_id TEXT, state TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS replays(
                    id TEXT PRIMARY KEY, profile_id TEXT, date TEXT, playlist TEXT,
                    team_size INTEGER, duration REAL, won INTEGER, link TEXT, data TEXT);
                CREATE INDEX IF NOT EXISTS ix_replays_p ON replays(profile_id, date);
                CREATE TABLE IF NOT EXISTS candidates(
                    bc_id TEXT, platform TEXT, pid TEXT, name TEXT,
                    PRIMARY KEY(bc_id, platform, pid));
                """)
        except (sqlite3.Error, OSError):
            pass

    def file(self, path):
        try:
            with self._conn() as c:
                r = c.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
            return dict(r) if r else None
        except (sqlite3.Error, OSError):
            return None

    def set_file(self, path, mtime, bc_id, state, error=None):
        try:
            with self.lock, self._conn() as c:
                c.execute("INSERT OR REPLACE INTO files(path,mtime,bc_id,state,error) "
                          "VALUES(?,?,?,?,?)", (path, mtime, bc_id, state, error))
        except (sqlite3.Error, OSError):
            pass

    def save_replay(self, rid, profile_id, replay, ex):
        try:
            with self.lock, self._conn() as c:
                c.execute(
                    "INSERT OR REPLACE INTO replays(id,profile_id,date,playlist,team_size,"
                    "duration,won,link,data) VALUES(?,?,?,?,?,?,?,?,?)",
                    (rid, profile_id, replay.get("date") or replay.get("created") or "",
                     replay.get("playlist_name") or replay.get("playlist_id") or "",
                     replay.get("team_size"), replay.get("duration"), ex["won"],
                     replay.get("link") or "", json.dumps(ex["data"])))
        except (sqlite3.Error, OSError):
            pass

    def save_candidates(self, bc_id, replay):
        try:
            with self.lock, self._conn() as c:
                for team in ("blue", "orange"):
                    for pl in (replay.get(team) or {}).get("players") or []:
                        i = pl.get("id") or {}
                        c.execute("INSERT OR REPLACE INTO candidates VALUES(?,?,?,?)",
                                  (bc_id, i.get("platform", ""), str(i.get("id", "")),
                                   pl.get("name", "")))
        except (sqlite3.Error, OSError):
            pass

    def top_candidates(self, claimed, min_count=2, limit=3):
        """Contas que aparecem em varios replays sem dono (provavelmente tu).
        claimed: conjunto de 'plataforma:id' ja' associados a perfis."""
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT platform, pid, MAX(name) name, COUNT(*) n FROM candidates "
                    "WHERE bc_id IN (SELECT bc_id FROM files WHERE state='nomatch') "
                    "GROUP BY platform, pid HAVING n >= ? ORDER BY n DESC LIMIT ?",
                    (min_count, limit + len(claimed))).fetchall()
        except (sqlite3.Error, OSError):
            return []
        lowered = {x.lower() for x in claimed}
        return [dict(r) for r in rows
                if f"{r['platform']}:{r['pid']}".lower() not in lowered][:limit]

    def has_candidates(self, bc_id):
        try:
            with self._conn() as c:
                return c.execute("SELECT 1 FROM candidates WHERE bc_id=? LIMIT 1",
                                 (bc_id,)).fetchone() is not None
        except (sqlite3.Error, OSError):
            return True

    def nomatch_files(self):
        try:
            with self._conn() as c:
                return [dict(r) for r in c.execute(
                    "SELECT * FROM files WHERE state='nomatch' AND bc_id IS NOT NULL")]
        except (sqlite3.Error, OSError):
            return []

    def replays(self, profile_id=None, limit=200):
        sql, args = "SELECT * FROM replays", []
        if profile_id:
            sql += " WHERE profile_id=?"
            args.append(profile_id)
        sql += " ORDER BY date DESC LIMIT ?"
        args.append(limit)
        try:
            with self._conn() as c:
                rows = c.execute(sql, args).fetchall()
        except (sqlite3.Error, OSError):
            return []
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["data"] = json.loads(d["data"] or "{}")
            except ValueError:
                d["data"] = {}
            out.append(d)
        return out


# ── Sincronizacao ────────────────────────────────────────────────────────────

class ReplaySync:
    """Varre a pasta, envia os replays novos e guarda as stats.

    emit(kind, payload): "status" (texto), "data" (houve replays novos).
    """

    def __init__(self, settings, store, profiles, emit):
        self.settings, self.store, self.profiles, self.emit = settings, store, profiles, emit
        self._run_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._sizes = {}

    # -- auto ---------------------------------------------------------------

    def set_auto(self, enabled):
        if enabled and not (self._thread and self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        elif not enabled:
            self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            if self.settings.token:
                try:
                    self.run_once(manual=False)
                except Exception as e:     # a thread nunca pode morrer
                    self.emit("status", tr("Erro inesperado: {e}", e=e))
            self._stop.wait(SYNC_INTERVAL)

    def sync_async(self):
        threading.Thread(target=self._safe_manual, daemon=True).start()

    def _safe_manual(self):
        try:
            self.run_once(manual=True)
        except Exception as e:
            self.emit("status", tr("Erro inesperado: {e}", e=e))

    # -- trabalho -----------------------------------------------------------

    def pending_files(self, manual):
        cutoff, now, out = self.settings.cutoff(), time.time(), []
        paths, found_dir = [], False
        for d in list(self.settings.replay_dirs):
            try:
                names = [n for n in os.listdir(d) if n.lower().endswith(".replay")]
            except OSError:
                continue
            found_dir = True
            paths += [os.path.join(d, n) for n in names]
        if not found_dir:
            return None
        for p in paths:
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            prev = self._sizes.get(p)
            self._sizes[p] = st.st_size
            if now - st.st_mtime < STABLE_SECONDS or (not manual and prev != st.st_size):
                continue                    # ainda a ser escrito
            rec = self.store.file(p)
            if rec and rec["state"] in ("done", "nomatch"):
                continue
            if rec and rec["state"] == "failed" and not manual:
                continue
            out.append((st.st_mtime, p, rec))
        out.sort()
        return out

    def run_once(self, manual=True):
        if not self._run_lock.acquire(blocking=False):
            return
        try:
            self._run(manual)
        finally:
            self._run_lock.release()

    def _run(self, manual):
        s = self.settings
        if not s.token:
            self.emit("status", tr("Falta a chave da API do Ballchasing."))
            return
        files = self.pending_files(manual)
        if files is None:
            self.emit("status", tr("Não encontro nenhuma das pastas de replays: {d}", d="; ".join(s.replay_dirs or [tr("(nenhuma)")])))
            return
        client = Client(s.token)
        if manual:
            self._backfill_candidates(client)
        if not files:
            if manual:
                self.emit("status", tr("Tudo em dia: não há replays novos."))
            return
        try:
            info = client.ping()
        except BallchasingError as e:
            self.emit("status", str(e))
            return
        quota = (info.get("quota") or {}).get("uploads_in_24h") or {}
        left = None
        if isinstance(quota.get("max"), int) and isinstance(quota.get("used"), int):
            left = max(0, quota["max"] - quota["used"])

        done = 0
        changed = False
        for i, (mtime, path, rec) in enumerate(files, 1):
            label = f"{i}/{len(files)}"
            try:
                rid = rec["bc_id"] if rec and rec.get("bc_id") else None
                if not rid:
                    if left is not None and left <= 0:
                        self.emit("status", tr("Limite diário de uploads atingido; continua amanhã."))
                        break
                    self.emit("status", tr("A enviar {x}…", x=label))
                    rid = client.upload(path, s.visibility)
                    if left is not None:
                        left -= 1
                    self.store.set_file(path, mtime, rid, "uploaded")
                self.emit("status", tr("A processar {x}…", x=label))
                replay = client.wait_ready(rid, self._stop)
                if replay is None:
                    continue
                if self._store_stats(path, mtime, rid, replay):
                    done += 1
                changed = True            # tambem atualiza o aviso de replays sem dono
            except BallchasingError as e:
                if e.status == 401:
                    self.emit("status", str(e))
                    return
                self.store.set_file(path, mtime, rec["bc_id"] if rec else None, "failed", str(e))
                self.emit("status", tr("Falhou {f}: {e}", f=os.path.basename(path), e=e))
            except OSError as e:
                self.store.set_file(path, mtime, None, "failed", str(e))
        if changed:
            self.emit("data", None)
        self.emit("status", tr("Sincronizado: {n} replay(s) novo(s) com as tuas stats.", n=done))

    def _backfill_candidates(self, client, cap=40):
        """Replays sem dono guardados antes de existirem 'candidatos'."""
        n, changed = 0, False
        for rec in self.store.nomatch_files():
            if n >= cap:
                break
            if self.store.has_candidates(rec["bc_id"]):
                continue
            n += 1
            try:
                replay = client.get_replay(rec["bc_id"])
            except BallchasingError:
                return
            if replay.get("status") == "ok":
                self.store.save_candidates(rec["bc_id"], replay)
                changed = True
        if changed:
            self.emit("data", None)

    def _store_stats(self, path, mtime, rid, replay):
        for prof in list(self.profiles.profiles):
            ex = extract(replay, prof)
            if ex:
                self.store.save_replay(rid, prof.id, replay, ex)
                self.store.set_file(path, mtime, rid, "done")
                return True
        self.store.set_file(path, mtime, rid, "nomatch",
                            "nenhum perfil tem este nome no replay")
        self.store.save_candidates(rid, replay)
        return False

    def rematch_async(self):
        """Volta a tentar os replays sem dono (depois de associares uma conta)."""
        threading.Thread(target=self._safe_rematch, daemon=True).start()

    def _safe_rematch(self):
        if not self._run_lock.acquire(blocking=False):
            return
        try:
            client = Client(self.settings.token)
            done = 0
            for rec in self.store.nomatch_files():
                try:
                    replay = client.get_replay(rec["bc_id"])
                except BallchasingError as e:
                    self.emit("status", str(e))
                    return
                if replay.get("status") == "ok" and self._store_stats(
                        rec["path"], rec["mtime"], rec["bc_id"], replay):
                    done += 1
            self.emit("data", None)
            self.emit("status", tr("Associação feita: {n} replay(s) adicionados às tuas stats.", n=done))
        except Exception as e:
            self.emit("status", tr("Erro inesperado: {e}", e=e))
        finally:
            self._run_lock.release()
