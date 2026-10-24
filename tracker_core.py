"""
tracker_core.py

Logica pura (sem GUI) de ligacao a Stats API do Rocket League e de
calculo dos totais da sessao (vitorias, derrotas, streak). Mantido
separado de app.py para poder ser testado sem abrir nenhuma janela.

https://www.rocketleague.com/developer/stats-api

NOTA TECNICA IMPORTANTE:
    A pagina oficial chama a isto "web socket", mas na pratica e' um
    socket TCP simples que envia objetos JSON concatenados, sem fazer o
    handshake HTTP/Upgrade que um WebSocket real exige. Se ligares com
    uma biblioteca de WebSocket (ex. `websockets`), a ligacao nunca
    completa o handshake e a app fica para sempre a tentar ligar -- e'
    exatamente o sintoma de "nao detetar que o jogo esta aberto".
    Por isso aqui usamos `asyncio.open_connection` (TCP cru) e um
    "frame buffer" que separa os objetos JSON concatenados pela
    profundidade de chavetas `{ }`.
"""

import asyncio
import codecs
import json
import queue
import threading
import time

from history import MODES, MODE_LABELS, MatchHistory, mode_from_team_size
from i18n import tr
from profiles import ProfileManager, platform_matches

HOST = "127.0.0.1"
PORT = 49123


class JsonFrameBuffer:
    """Acumula bytes recebidos do socket TCP e extrai objetos JSON
    completos, mesmo que cheguem concatenados (sem separador) ou
    fragmentados a meio entre duas leituras do socket.

    Funciona contando a profundidade de chavetas `{ }`, ignorando
    chavetas que estejam dentro de strings (e respeitando aspas
    escapadas \\").
    """

    def __init__(self):
        self._buf = ""

    def push(self, text):
        self._buf += text

    def drain(self):
        frames = []
        buf = self._buf
        n = len(buf)
        i = 0
        start = None
        depth = 0
        in_string = False
        escape = False

        while i < n:
            c = buf[i]
            if start is None:
                if c == "{":
                    start = i
                    depth = 1
                    in_string = False
                    escape = False
                i += 1
                continue

            if in_string:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_string = False
            else:
                if c == '"':
                    in_string = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        frames.append(buf[start:i + 1])
                        start = None
            i += 1

        self._buf = buf[start:] if start is not None else ""
        return frames


def decode_envelope(raw_frame):
    """Decodifica um frame JSON em (event_name, data_dict).

    Lida com as duas variantes possiveis do campo "Data": um objeto
    aninhado (como mostrado na documentacao oficial) ou uma string
    JSON escapada (como observado em implementacoes de terceiros
    contra o socket real). Em caso de erro devolve (None, {}).
    """
    try:
        obj = json.loads(raw_frame)
    except json.JSONDecodeError:
        return None, {}

    event_name = obj.get("Event")
    data = obj.get("Data", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    return event_name, data


class SessionStats:
    """Totais acumulados ao longo da sessao atual (desde que a app abriu,
    ou desde o ultimo 'Reiniciar sessao')."""

    def __init__(self):
        self.games = 0
        self.wins = 0
        self.losses = 0
        self.streak = 0  # positivo = sequencia de vitorias, negativo = derrotas
        self.goals = 0
        self.assists = 0
        self.saves = 0
        self.shots = 0
        self.demos = 0
        self.score = 0   # soma do Score (pontos) do jogador em cada partida contada
        self.by_mode = {}  # modo -> [vitorias, derrotas]

    def register_result(self, won, player_snapshot, mode=None):
        self.games += 1
        if mode:
            wl = self.by_mode.setdefault(mode, [0, 0])
            wl[0 if won else 1] += 1
        if won:
            self.wins += 1
            self.streak = self.streak + 1 if self.streak >= 0 else 1
        else:
            self.losses += 1
            self.streak = self.streak - 1 if self.streak <= 0 else -1
        if player_snapshot:
            self.goals += player_snapshot.get("Goals", 0)
            self.assists += player_snapshot.get("Assists", 0)
            self.saves += player_snapshot.get("Saves", 0)
            self.shots += player_snapshot.get("Shots", 0)
            self.demos += player_snapshot.get("Demos", 0)
            self.score += player_snapshot.get("Score", 0)

    def streak_text(self):
        if self.streak > 0:
            return f"+{self.streak}"
        if self.streak < 0:
            return f"-{abs(self.streak)}"
        return "-"

    def modes_text(self):
        parts = [f"{MODE_LABELS[m]} {self.by_mode[m][0]}-{self.by_mode[m][1]}"
                 for m in MODES if m in self.by_mode]
        return "   ·   ".join(parts) if parts else "-"

    def score_avg_text(self):
        if not self.games:
            return "-"
        return f"{self.score / self.games:.0f}"

    def snapshot(self):
        return {
            "games": self.games, "wins": self.wins, "losses": self.losses,
            "streak_text": self.streak_text(), "goals": self.goals,
            "assists": self.assists, "saves": self.saves, "shots": self.shots,
            "demos": self.demos, "score_avg": self.score_avg_text(),
            "modes_text": self.modes_text(),
            "by_mode": {m: list(v) for m, v in self.by_mode.items()},
        }


class TrackerCore:
    """Liga-se a Stats API local (TCP cru) e mantem o estado (jogo/
    jogadores/eventos/sessao). Publica atualizacoes numa queue.Queue
    thread-safe para que a GUI (noutra thread) as possa consumir sem
    chamar widgets diretamente a partir desta thread.
    """

    def __init__(self, profiles=None, host=HOST, port=PORT, history=None):
        self.host = host
        self.port = port
        self.lock = threading.Lock()
        self.status = "connecting"
        self.game = {}
        self.players = []
        self.events = []
        # Perfis (ex. conta Steam e conta Epic). Cada perfil tem a sua
        # propria sessao (vitorias/derrotas/streak/totais).
        self.profiles = profiles if profiles is not None else ProfileManager()
        self.sessions = {}
        self.session = self.sessions.setdefault(
            self.profiles.active().id, SessionStats())
        # Verdadeiro quando ja' se confirmou (ou se tentou) que perfil esta'
        # a jogar nesta partida. Reset em cada partida nova/saida.
        self._profile_resolved = False
        # Historico persistente (SQLite) e modo de jogo da partida atual
        # (inferido pelo maior tamanho de equipa visto durante a partida).
        self.history = history if history is not None else MatchHistory()
        self._max_team_size = 0
        self.out_queue = queue.Queue()
        self.last_error = ""
        # Verdadeiro se a partida atual ja' teve o resultado contado na
        # sessao (via MatchEnded ou via a rede de seguranca no
        # MatchDestroyed). Evita contar a mesma partida duas vezes e
        # controla quando a rede de seguranca deve atuar.
        self._counted_this_match = True
        # Verdadeiro se em algum momento desta partida existiram jogadores
        # em pelo menos 2 equipas. Reset em cada nova partida. Evita
        # ignorar o resultado quando os adversarios saem antes do fim e o
        # UpdateState final so' tem 1 equipa.
        self._had_real_opponent = False
        # Deduplicacao de golos: mapa scorer -> timestamp do ultimo golo
        # emitido. O Stats API reenvia GoalScored durante o replay -- se o
        # mesmo marcador voltar a aparecer dentro de 15s ignoramos.
        self._last_goal_ts: dict = {}

        # A Stats API nao diz qual e' o playlist/modo de jogo (ranked,
        # casual, treino, exibicao...), por isso nao ha forma oficial de
        # excluir "treino" da sessao. O melhor sinal disponivel e' que os
        # bots reportam sempre PrimaryId "Unknown|0|0" -- por isso,
        # partidas com bots (treino/exibicao contra IA) podem ser
        # excluidas por defeito.
        self.exclude_bot_matches = True

    def _emit(self, kind, payload):
        self.out_queue.put((kind, payload))

    def set_status(self, status):
        with self.lock:
            self.status = status
        self._emit("status", status)

    def set_exclude_bot_matches(self, enabled):
        self.exclude_bot_matches = bool(enabled)

    @staticmethod
    def _is_bot(player):
        return (player.get("PrimaryId") or "").strip().lower().startswith("unknown")

    def _has_bot_players(self):
        return any(self._is_bot(p) for p in self.players)

    def _has_real_opponent(self):
        """Free Play e treinos personalizados nao tem adversario nenhum
        -- so' tu, numa unica equipa. Mesmo assim, o jogo por vezes ainda
        emite MatchCreated/MatchEnded/MatchDestroyed para essas sessoes.
        Usa a flag _had_real_opponent (atualizada durante UpdateState) para
        nao ignorar partidas onde os adversarios sairam antes do fim e o
        ultimo UpdateState so' tinha 1 equipa."""
        return self._had_real_opponent

    def handle_update_state(self, data):
        with self.lock:
            self.game = data.get("Game", {})
            self.players = data.get("Players", [])
            self.status = "in_match"
            # Atualiza a flag se vemos 2+ equipas em qualquer UpdateState
            team_nums = {p.get("TeamNum") for p in self.players
                         if p.get("TeamNum") is not None}
            if len(team_nums) >= 2:
                self._had_real_opponent = True
            sizes = {}
            for _p in self.players:
                _t = _p.get("TeamNum")
                if _t is not None:
                    sizes[_t] = sizes.get(_t, 0) + 1
            if sizes:
                self._max_team_size = max(self._max_team_size, max(sizes.values()))
        self._maybe_autoswitch_profile()
        found = self._find_my_player() is not None
        self._emit("state", {
            "game": self.game, "players": self.players, "status": "in_match",
            "my_player_found": found,
        })

    def _find_my_player(self):
        """Procura o jogador local na lista atual de jogadores.

        Tenta primeiro uma correspondencia exata (sem distinguir
        maiusculas/minusculas/acentos), e se nao encontrar nada tenta uma
        correspondencia parcial (um nome contido no outro) -- util quando
        o nome no jogo tem sufixos/prefixos (ex. tags de clube, codigos
        Epic do tipo "Nome#1234") que o campo "O teu nome no jogo" nao
        inclui exatamente.
        """
        prof = self.profiles.active()
        name = (prof.name or "").strip().casefold()
        if not name:
            return None

        # So' considera jogadores da plataforma do perfil (Steam/Epic/...).
        candidates = [p for p in self.players
                      if platform_matches(prof.platform, p.get("PrimaryId"))]

        for p in candidates:
            if p.get("Name", "").strip().casefold() == name:
                return p

        for p in candidates:
            p_name = p.get("Name", "").strip().casefold()
            if p_name and (name in p_name or p_name in name):
                return p

        return None

    def _maybe_autoswitch_profile(self):
        """Uma vez por partida: se algum perfil (nome + plataforma exatos)
        corresponder a um jogador da partida e nao for o ativo, troca para
        ele. Assim, jogar na conta Epic ou Steam muda o perfil sozinho."""
        if self._profile_resolved or not self.profiles.auto_switch:
            return
        players = self.players
        if not players:
            return
        prof = self.profiles.detect(players)
        if prof is None:
            return  # ainda nao ha' correspondencia -- tenta no proximo tick
        self._profile_resolved = True
        if prof.id != self.profiles.active().id:
            self.switch_profile(prof.id)
            ts = time.strftime("%H:%M:%S")
            ev = {"ts": ts, "kind": "info",
                  "text": tr("Perfil mudou automaticamente para {name}", name=prof.display())}
            with self.lock:
                self.events.append(ev)
                self.events = self.events[-200:]
            self._emit("event", ev)

    def switch_profile(self, pid):
        """Muda o perfil ativo (chamado pela GUI ou pela deteccao
        automatica) e passa para a sessao desse perfil."""
        with self.lock:
            if not self.profiles.set_active(pid):
                return
            self.session = self.sessions.setdefault(pid, SessionStats())
            snap = self.session.snapshot()
        self._emit("session", snap)
        self._emit("profile", pid)

    def _winner_team_num_from_game(self):
        """Tenta determinar o TeamNum vencedor a partir do ultimo estado
        de jogo conhecido (campos bHasWinner/Winner, presentes em todos
        os UpdateState). Serve de rede de seguranca para quando o evento
        MatchEnded nao chega a tempo de ser processado -- por exemplo, se
        a ligacao TCP fechar muito rapido a seguir ao fim da partida.
        Devolve None se a partida saiu sem um vencedor ter sido decidido
        (ex.: abandonaste/fizeste FF antes do fim).
        """
        if not self.game.get("bHasWinner"):
            return None
        winner_name = self.game.get("Winner")
        for t in self.game.get("Teams", []):
            if t.get("Name") == winner_name:
                return t.get("TeamNum")
        return None

    def _estimate_winner_from_score(self):
        """Ultimo recurso: se a partida saiu sem um vencedor oficial
        decidido (bHasWinner nunca chegou a True), usa o ultimo placar
        conhecido (Game.Teams[].Score) para adivinhar quem estava a
        ganhar. Devolve None se as equipas estiverem empatadas (sem
        forma de estimar) ou se nao houver pelo menos 2 equipas.

        ATENCAO: isto e' so' uma estimativa, nao um resultado oficial.
        Se saiste a meio por desistencia/FF, o placar nesse momento pode
        nao corresponder ao resultado que a Psyonix regista do lado dela
        (ex.: sair a ganhar pode ainda contar como derrota oficialmente).
        """
        teams = self.game.get("Teams", [])
        if len(teams) < 2:
            return None
        ranked = sorted(teams, key=lambda t: t.get("Score", 0), reverse=True)
        if ranked[0].get("Score", 0) == ranked[1].get("Score", 0):
            return None
        return ranked[0].get("TeamNum")

    def _register_or_skip(self, won, my_player, base_text, estimated=False):
        """Regista o resultado na sessao e devolve o texto final do
        evento -- a nao ser que: (a) nao haja adversario real (Free Play
        ou treino sem oponente -- isto aplica-se sempre, nao e'
        configuravel, porque um resultado sem adversario nao tem
        significado), ou (b) a partida tenha bots e a opcao 'excluir
        partidas com bots' esteja ativa. Nesses casos NAO conta e
        devolve um texto a explicar porque'."""
        if not self._has_real_opponent():
            return None  # Free Play / treino sem adversario -- nao emitir evento
        if self.exclude_bot_matches and self._has_bot_players():
            return tr("{text} -- NÃO contada na sessão (partida com bots/treino)", text=base_text)
        mode = mode_from_team_size(self._max_team_size)
        with self.lock:
            self.session.register_result(won, my_player, mode)
        self._record_history(won, my_player, mode, estimated)
        self._emit("session", self.session.snapshot())
        return base_text

    def _record_history(self, won, my_player, mode, estimated):
        """Grava a partida contada no historico persistente."""
        my_team = (my_player or {}).get("TeamNum")
        my_score = opp_score = None
        for t in self.game.get("Teams", []):
            if t.get("TeamNum") == my_team:
                my_score = t.get("Score")
            else:
                opp_score = t.get("Score")
        prof = self.profiles.active()
        snap = my_player or {}
        ok = self.history.add_match({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "profile_id": prof.id, "profile_name": prof.name,
            "platform": prof.platform, "mode": mode, "won": won,
            "estimated": estimated, "my_score": my_score,
            "opp_score": opp_score,
            "goals": snap.get("Goals", 0), "assists": snap.get("Assists", 0),
            "saves": snap.get("Saves", 0), "shots": snap.get("Shots", 0),
            "demos": snap.get("Demos", 0), "score": snap.get("Score", 0),
        })
        if ok:
            self._emit("history", None)

    def _finalize_unclosed_match(self):
        """Se a partida anterior nunca chegou a ser formalmente encerrada
        (nem MatchEnded nem MatchDestroyed foram processados antes de uma
        partida nova comecar -- ex.: foste direto de uma partida para a
        seguinte sem passar pelo menu), tenta finalizar o resultado agora,
        usando o ultimo estado de jogo conhecido, antes que seja
        substituido pelos dados da partida nova. Devolve o texto do
        evento a registar, ou None se nao havia nada pendente (a partida
        anterior ja' tinha sido contada normalmente)."""
        if self._counted_this_match:
            return None
        # Free Play / treino sem adversario -- nao mostrar nenhum evento
        if not self._had_real_opponent:
            self._counted_this_match = True
            return None

        my_player = self._find_my_player()
        winner_team_num = self._winner_team_num_from_game()
        is_estimate = False
        if winner_team_num is None:
            winner_team_num = self._estimate_winner_from_score()
            is_estimate = winner_team_num is not None

        # Marca como tratada de qualquer forma -- nao vale a pena tentar
        # outra vez mais tarde com dados que ja' vao ter sido substituidos
        # pela partida nova.
        self._counted_this_match = True

        if winner_team_num is None:
            return tr("Partida anterior terminou sem resultado decidido e sem "
                      "placar para estimar -- sessão NÃO contada")
        if my_player is None:
            return tr("Partida anterior terminou mas não foi possível "
                      "identificar o teu jogador -- sessão NÃO contada")

        won = my_player.get("TeamNum") == winner_team_num
        result_text = tr("VITÓRIA") if won else tr("DERROTA")
        if is_estimate:
            base_text = tr("{result} (ESTIMATIVA pelo placar -- a partida anterior "
                           "não fechou formalmente, pode não corresponder ao resultado real)",
                           result=result_text)
        else:
            base_text = tr("{result} -- resultado da partida anterior detetado", result=result_text)
        return self._register_or_skip(won, my_player, base_text,
                                      estimated=is_estimate)

    def handle_event(self, event_name, data):
        ts = time.strftime("%H:%M:%S")
        text, kind = None, "info"

        if event_name == "GoalScored":
            scorer = data.get("Scorer", {}).get("Name", "?")
            now = time.time()
            if now - self._last_goal_ts.get(scorer, 0) < 15:
                # Duplicado do replay -- ignorar
                return
            self._last_goal_ts[scorer] = now
            assister = data.get("Assister", {}).get("Name")
            text = tr("GOLO de {name}", name=scorer) + (tr(" (assist. {name})", name=assister) if assister else "")
            kind = "goal"
        elif event_name == "StatfeedEvent":
            who = data.get("MainTarget", {}).get("Name", "?")
            label = data.get("Type", data.get("EventName", "?"))
            # "Goal" ja' e' coberto pelo evento GoalScored -- ignorar para
            # evitar duplicado com cor diferente
            if label.lower() == "goal":
                return
            other = data.get("SecondaryTarget", {}).get("Name")
            is_demo = "demol" in label.lower()
            text = f"{label}: {who}" + (f" -> {other}" if other else "")
            kind = "demo" if is_demo else "stat"
        elif event_name == "MatchEnded":
            winner = data.get("WinnerTeamNum")
            my_player = self._find_my_player()
            if my_player is not None and winner is not None:
                won = my_player.get("TeamNum") == winner
                self._counted_this_match = True
                base_text = tr("Partida terminada -- {result}",
                               result=tr("VITÓRIA") if won else tr("DERROTA"))
                text = self._register_or_skip(won, my_player, base_text)
            elif winner is not None:
                my_name = (self.profiles.active().name or "").strip()
                if not my_name:
                    text = tr("Partida terminada (equipa {team} venceu) -- "
                              "sessão NÃO contada: preenche o 'Nome no jogo' no topo", team=winner)
                else:
                    nomes = ", ".join(p.get("Name", "?") for p in self.players) or tr("(nenhum)")
                    text = tr("Partida terminada (equipa {team} venceu) -- sessão NÃO "
                              "contada: '{name}' não corresponde a nenhum jogador da "
                              "partida ({names})", team=winner, name=my_name, names=nomes)
            else:
                text = tr("Partida terminada")
            kind = "match"
        elif event_name in ("MatchCreated", "MatchInitialized"):
            # Rede de seguranca: se foste direto de uma partida para esta
            # nova sem que MatchEnded/MatchDestroyed tivessem chegado a
            # ser processados para a anterior (ex.: nao saiste para o
            # menu, o jogo encadeou logo a partida seguinte), tenta
            # finalizar o resultado dela agora, ANTES de qualquer dado
            # ser substituido pelo da partida nova.
            pending_text = self._finalize_unclosed_match()
            if pending_text:
                pending_ev = {"ts": ts, "text": pending_text, "kind": "match"}
                with self.lock:
                    self.events.append(pending_ev)
                    self.events = self.events[-200:]
                self._emit("event", pending_ev)

            text = tr("Nova partida iniciada")
            kind = "match"
            with self.lock:
                self.status = "in_match"
                self._counted_this_match = False
                self._had_real_opponent = False
                self._profile_resolved = False
                self._max_team_size = 0
                self._last_goal_ts = {}
            self._emit("status", "in_match")
        elif event_name == "MatchDestroyed":
            # Rede de seguranca: se ainda nao contamos esta partida (o
            # MatchEnded pode nao ter chegado a tempo -- ex.: a ligacao
            # fechou-se demasiado rapido), tenta usar o ultimo estado de
            # jogo conhecido (bHasWinner/Winner) antes de o limparmos. Se
            # nem isso houver, usa o placar como ultima estimativa.
            text = self._finalize_unclosed_match() or tr("Saiu da partida")
            kind = "match"
            with self.lock:
                self.status = "waiting"
                self.players = []
                self.game = {}
                self._profile_resolved = False
                self._max_team_size = 0
            self._emit("state", {"game": {}, "players": [], "status": "waiting"})
        elif event_name == "RoundStarted":
            text = tr("Round começou")
            kind = "match"

        if text:
            ev = {"ts": ts, "text": text, "kind": kind}
            with self.lock:
                self.events.append(ev)
                self.events = self.events[-200:]
            self._emit("event", ev)

    def reset_session(self):
        with self.lock:
            self.session = SessionStats()
            self.sessions[self.profiles.active().id] = self.session
        self._emit("session", self.session.snapshot())

    def handle_message(self, event_name, data):
        if event_name == "UpdateState":
            self.handle_update_state(data)
        elif event_name is not None:
            self.handle_event(event_name, data)

    async def _connect_loop(self):
        backoff = 2
        while True:
            writer = None
            try:
                self.set_status("connecting")
                reader, writer = await asyncio.open_connection(self.host, self.port)
                self.set_status("waiting")
                backoff = 2
                frame_buffer = JsonFrameBuffer()
                # Decoder incremental: guarda bytes de caracteres multi-byte
                # partidos entre dois reads (acentos, emojis) em vez de os perder.
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

                while True:
                    chunk = await reader.read(8192)
                    if not chunk:
                        raise ConnectionResetError("ligacao fechada pelo jogo")
                    frame_buffer.push(decoder.decode(chunk))
                    for raw_frame in frame_buffer.drain():
                        event_name, data = decode_envelope(raw_frame)
                        self.handle_message(event_name, data)

            except ConnectionResetError as e:
                self.last_error = str(e)
                self.set_status("waiting")
                await asyncio.sleep(backoff)
            except (ConnectionRefusedError, OSError) as e:
                self.last_error = str(e)
                self.set_status("error")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
            finally:
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

    def start_background_loop(self):
        import threading
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._connect_loop())
        t = threading.Thread(target=_run, daemon=True)
        t.start()
