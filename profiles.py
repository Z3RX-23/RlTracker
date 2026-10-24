"""
profiles.py

Perfis do jogador (um por conta: ex. a conta Steam e a conta Epic) e
deteccao automatica do perfil pela plataforma + nome que a Stats API
reporta em cada partida (campo PrimaryId, ex. "Steam|7656...|0" ou
"Epic|<guid>|0").

Os perfis ficam em profiles.json, ao lado da app/.exe. Na primeira
execucao importa o nome antigo de config.ini ([player] name).
"""

import configparser
import json
import os
import sys
import threading
import uuid

from i18n import tr

if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILES_PATH = os.path.join(_BASE_DIR, "profiles.json")
LEGACY_CONFIG_PATH = os.path.join(_BASE_DIR, "config.ini")

# valor guardado -> texto mostrado
PLATFORMS = {"any": "Qualquer", "steam": "Steam", "epic": "Epic"}


def platform_of(primary_id):
    """'Steam|123|0' -> 'steam'; 'Epic|abc|0' -> 'epic'; '' -> ''."""
    return (primary_id or "").split("|")[0].strip().lower()


def platform_matches(profile_platform, primary_id):
    return profile_platform == "any" or platform_of(primary_id) == profile_platform


class Profile:
    __slots__ = ("id", "name", "platform", "replay_ids")

    def __init__(self, name="", platform="any", pid=None):
        self.id = pid or uuid.uuid4().hex[:8]
        self.name = (name or "").strip()
        self.platform = platform if platform in PLATFORMS else "any"
        self.replay_ids = []     # "plataforma:id" da conta nos replays do Ballchasing

    def display(self):
        base = self.name or tr("(sem nome)")
        return base if self.platform == "any" else f"{base}  [{PLATFORMS[self.platform]}]"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "platform": self.platform,
                "replay_ids": list(self.replay_ids)}


class ProfileManager:
    def __init__(self, path=PROFILES_PATH, legacy_config=LEGACY_CONFIG_PATH):
        self.path = path
        self._legacy = legacy_config
        self._lock = threading.RLock()
        self.profiles = []
        self.active_id = None
        self.auto_switch = True
        self.last_error = None
        self.load()

    # ---- persistencia ------------------------------------------------------

    def load(self):
        with self._lock:
            data = None
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = None

            self.profiles = []
            if isinstance(data, dict):
                for d in data.get("profiles", []):
                    if isinstance(d, dict):
                        prof = Profile(d.get("name", ""), d.get("platform", "any"), d.get("id"))
                        ids = d.get("replay_ids")
                        if isinstance(ids, list):
                            prof.replay_ids = [x for x in ids if isinstance(x, str)]
                        self.profiles.append(prof)
                self.active_id = data.get("active")
                self.auto_switch = bool(data.get("auto_switch", True))

            if not self.profiles:
                self.profiles = [Profile(self._legacy_name(), "any")]
                self.active_id = self.profiles[0].id
                self.save()
            if self.active_id not in {p.id for p in self.profiles}:
                self.active_id = self.profiles[0].id

    def _legacy_name(self):
        try:
            parser = configparser.ConfigParser()
            parser.read(self._legacy, encoding="utf-8")
            return parser.get("player", "name", fallback="").strip()
        except (configparser.Error, OSError):
            return ""

    def save(self):
        """Grava profiles.json. Tenta tmp+replace (atomico); se o Windows
        recusar (antivirus/OneDrive a segurar o ficheiro), grava direto.
        Devolve True se gravou; senao guarda o erro em self.last_error."""
        with self._lock:
            data = {"active": self.active_id, "auto_switch": self.auto_switch,
                    "profiles": [p.to_dict() for p in self.profiles]}
            text = json.dumps(data, ensure_ascii=False, indent=2)
            self.last_error = None
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
                return True
            except OSError:
                pass
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.write(text)
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                return True
            except OSError as e:
                self.last_error = f"{self.path}: {e}"
                return False

    def get(self, pid):
        with self._lock:
            for p in self.profiles:
                if p.id == pid:
                    return p
            return None

    def active(self):
        with self._lock:
            return self.get(self.active_id) or self.profiles[0]

    def set_active(self, pid):
        with self._lock:
            if self.get(pid) is None:
                return False
            self.active_id = pid
            self.save()
            return True

    def set_auto_switch(self, enabled):
        with self._lock:
            self.auto_switch = bool(enabled)
            self.save()

    def add(self, name="", platform="any"):
        with self._lock:
            p = Profile(name, platform)
            self.profiles.append(p)
            self.save()
            return p

    def update(self, pid, name=None, platform=None):
        with self._lock:
            p = self.get(pid)
            if p is None:
                return
            if name is not None:
                p.name = name.strip()
            if platform in PLATFORMS:
                p.platform = platform
            self.save()

    def add_replay_id(self, pid, replay_id):
        """Associa uma conta ('plataforma:id' do Ballchasing) a um perfil."""
        with self._lock:
            p = self.get(pid)
            if p is None:
                return False
            for other in self.profiles:          # uma conta so' pertence a um perfil
                if replay_id in other.replay_ids:
                    other.replay_ids.remove(replay_id)
            p.replay_ids.append(replay_id)
            self.save()
            return True

    def delete(self, pid):
        """Apaga um perfil (nunca o ultimo). Devolve o id ativo resultante."""
        with self._lock:
            if len(self.profiles) <= 1:
                return self.active_id
            self.profiles = [p for p in self.profiles if p.id != pid]
            if self.active_id == pid:
                self.active_id = self.profiles[0].id
            self.save()
            return self.active_id

    # ---- deteccao ----------------------------------------------------------

    def detect(self, players):
        """Devolve o perfil cujo nome (igual, sem distinguir maiusculas) e
        plataforma batem com algum jogador da partida, ou None. Se o perfil
        ativo tambem bater, e' esse que ganha (evita trocas desnecessarias).
        Usa so' correspondencia exata -- uma troca automatica errada e'
        pior do que nao trocar."""
        with self._lock:
            ordered = sorted(self.profiles, key=lambda p: p.id != self.active_id)
            for prof in ordered:
                name = prof.name.casefold()
                if not name:
                    continue
                for pl in players:
                    if (pl.get("Name", "").strip().casefold() == name and
                            platform_matches(prof.platform, pl.get("PrimaryId"))):
                        return prof
            return None
