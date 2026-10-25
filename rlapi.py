"""
rlapi.py

MMR automatico via API externa (RapidAPI "Rocket League", rocket-league10).
E' uma consulta publica ao perfil -- nao toca no jogo nem na Stats API.

Ficheiro (ao lado da app/.exe):
  rlapi.json -- chave da API, contador diario de pedidos e opcoes.
A chave fica em texto simples: nao partilhes esse ficheiro (esta no .gitignore
e fica fora das copias/exportacoes).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from i18n import tr

if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

INTERVALS = [30, 60, 120, 0]          # minutos entre consultas; 0 = so' no fim da sessao
INTERVAL_LABELS = {30: "30 min", 60: "1 h", 120: "2 h", 0: "Só no fim da sessão"}
LAST_HEADERS = {}                     # cabecalhos da ultima resposta (limites reais do servidor)
LAST_SYNC = 0.0                       # time.time() da ultima consulta (qualquer origem)

SETTINGS_PATH = os.path.join(_BASE_DIR, "rlapi.json")
HOST = "rocket-league10.p.rapidapi.com"
BASE_URL = "https://" + HOST
USER_AGENT = "RL-Live-Dashboard/1.0"
PLAYLIST_MODES = {10: "duel", 11: "doubles", 13: "standard"}


class RLApiError(Exception):
    pass


class RLApiSettings:
    def __init__(self, path=SETTINGS_PATH):
        self.path = path
        self.api_key = ""
        self.auto = True
        self.daily_limit = 10
        self.interval = 0
        self.srv_remaining = None      # pedidos que o servidor diz que restam
        self.srv_reset_at = 0.0        # time.time() em que o servidor repoe o limite
        self.day = ""
        self.used = 0
        self.ids = {}                  # id do perfil -> nome/ID a usar na consulta do MMR
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
        if isinstance(d.get("api_key"), str):
            self.api_key = d["api_key"].strip()
        if isinstance(d.get("auto"), bool):
            self.auto = d["auto"]
        if isinstance(d.get("daily_limit"), int) and 1 <= d["daily_limit"] <= 100000:
            self.daily_limit = d["daily_limit"]
        if isinstance(d.get("srv_remaining"), int) and isinstance(d.get("srv_reset_at"), (int, float)):
            self.srv_remaining, self.srv_reset_at = d["srv_remaining"], float(d["srv_reset_at"])
        if d.get("interval") in INTERVALS:
            self.interval = d["interval"]
        if isinstance(d.get("ids"), dict):
            self.ids = {str(k): v.strip() for k, v in d["ids"].items() if isinstance(v, str) and v.strip()}
        if isinstance(d.get("day"), str) and isinstance(d.get("used"), int):
            self.day, self.used = d["day"], max(0, d["used"])

    def save(self):
        self.last_error = None
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"api_key": self.api_key, "auto": self.auto, "daily_limit": self.daily_limit, "interval": self.interval, "srv_remaining": self.srv_remaining,
                           "srv_reset_at": self.srv_reset_at,
                           "day": self.day, "used": self.used, "ids": self.ids}, f, indent=2)
            os.replace(tmp, self.path)
        except OSError as e:
            self.last_error = str(e)

    def _server_known(self):
        return self.srv_remaining is not None and time.time() < self.srv_reset_at

    def used_today(self):
        if self._server_known():
            return max(0, self.daily_limit - self.srv_remaining)
        return self.used if self.day == date.today().isoformat() else 0

    def left_today(self):
        if self._server_known():
            return max(0, self.srv_remaining)
        return max(0, self.daily_limit - self.used_today())

    def note_headers(self, h):
        """Usa os limites reais que a RapidAPI devolve (x-ratelimit-requests-*)."""
        try:
            rem = int(h.get("x-ratelimit-requests-remaining"))
        except (TypeError, ValueError, AttributeError):
            return
        try:
            lim = int(h.get("x-ratelimit-requests-limit"))
        except (TypeError, ValueError):
            lim = self.daily_limit
        try:
            reset = float(h.get("x-ratelimit-requests-reset"))
        except (TypeError, ValueError):
            reset = 3600.0
        self.daily_limit, self.srv_remaining = lim, max(0, rem)
        self.srv_reset_at = time.time() + reset
        self.save()

    def count_call(self):
        today = date.today().isoformat()
        if self.day != today:
            self.day, self.used = today, 0
        self.used += 1
        self.save()


def clean_id(text):
    """Aceita o nome, o custom URL ou o link do perfil Steam
    (steamcommunity.com/id/xxx ou /profiles/7656...) e devolve so' o identificador."""
    t = (text or "").strip().rstrip("/")
    for marker in ("steamcommunity.com/id/", "steamcommunity.com/profiles/"):
        if marker in t:
            return t.split(marker, 1)[1].split("/")[0].split("?")[0]
    return t


def lookup_name(profile, settings):
    """O que se envia 'a API: o identificador definido para o perfil (ex. o custom URL
    da Steam) ou, se nao houver, o nome do perfil."""
    return settings.ids.get(profile.id) or profile.name


def parse_ranked(data):
    """Resposta da API -> {modo: {mmr, tier, division, matches}} (so' 1v1/2v2/3v3
    com partidas jogadas; um modo sem jogos vem com um valor por omissao)."""
    out = {}
    for r in (data or {}).get("ranked") or []:
        mode = PLAYLIST_MODES.get(r.get("playlistId"))
        mmr = r.get("rating")
        if not mode or not isinstance(mmr, int) or mmr <= 0 or not r.get("matchesPlayed"):
            continue
        out[mode] = {"mmr": mmr, "tier": r.get("tier") or "", "division": r.get("division") or "",
                     "matches": r.get("matchesPlayed")}
    return out


def fetch_stats(api_key, platform, name, timeout=25):
    if not api_key:
        raise RLApiError(tr("Falta a chave da API (Definições > MMR)."))
    url = f"{BASE_URL}/stats/{urllib.parse.quote(platform)}/{urllib.parse.quote(name, safe='')}"
    req = urllib.request.Request(url, headers={"x-rapidapi-host": HOST, "x-rapidapi-key": api_key,
                                               "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            LAST_HEADERS.clear()
            LAST_HEADERS.update({k.lower(): v for k, v in r.headers.items()})
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        LAST_HEADERS.clear()
        LAST_HEADERS.update({k.lower(): v for k, v in (e.headers or {}).items()})
        if e.code in (401, 403):
            raise RLApiError(tr("Chave da API recusada (ou sem subscrição ao plano)."))
        if e.code == 404:
            raise RLApiError(tr("Jogador não encontrado ({p}: {n}). Confirma o nome e a plataforma.",
                                p=platform, n=name))
        if e.code == 429:
            if "x-ratelimit-requests-remaining" not in LAST_HEADERS:
                LAST_HEADERS["x-ratelimit-requests-remaining"] = "0"
            raise RLApiError(tr("Limite de pedidos da API atingido."))
        raise RLApiError(tr("Erro da API (HTTP {c}).", c=e.code))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RLApiError(tr("Sem ligação à API: {err}", err=getattr(e, "reason", e)))


def platforms_for(profile):
    return ["epic", "steam"] if profile.platform == "any" else [profile.platform]


def refresh_mmr(history, profile, settings):
    """Consulta o MMR do perfil e grava os modos que mudaram. Devolve
    {modo: mmr_novo} (vazio se nada mudou). Levanta RLApiError."""
    who = lookup_name(profile, settings)
    if not who:
        raise RLApiError(tr("O perfil não tem nome no jogo."))
    if settings.left_today() <= 0:
        raise RLApiError(tr("Já usaste os {n} pedidos de hoje.", n=settings.daily_limit))
    last_err, ranked = None, None
    for plat in platforms_for(profile):
        if settings.left_today() <= 0:
            break
        settings.count_call()
        LAST_HEADERS.clear()
        try:
            ranked = parse_ranked(fetch_stats(settings.api_key, plat, who))
            settings.note_headers(LAST_HEADERS)
            break
        except RLApiError as e:
            settings.note_headers(LAST_HEADERS)
            last_err = e
    if ranked is None:
        raise last_err or RLApiError(tr("Sem resposta da API."))
    changed = {}
    for mode, d in ranked.items():
        es = history.mmr_entries(mode, profile.id)
        if not es or es[-1]["mmr"] != d["mmr"]:
            if history.add_mmr(mode, d["mmr"], profile.id):
                changed[mode] = d["mmr"]
    return changed


SETTINGS = RLApiSettings()
ACTIVE = None          # ProfileManager (definido pela app)
