#!/usr/bin/env python3
"""
rl_session_tracker.py

Tracker em tempo real (modo terminal/CLI) para a Rocket League Stats API
local (https://www.rocketleague.com/developer/stats-api).

Esta e' a versao simples em linha de comando. Para uma interface grafica
tipo dashboard, usa app.py (ver README.md).

NOTA TECNICA: a pagina oficial chama a isto "web socket", mas na pratica
e' um socket TCP simples que envia objetos JSON concatenados, sem o
handshake HTTP/Upgrade de um WebSocket real. Por isso ligamos com
asyncio.open_connection (TCP cru) e separamos os objetos JSON pela
profundidade de chavetas, em vez de usar uma biblioteca de WebSocket.

IMPORTANTE: isto NAO permite consultar qualquer jogador da internet por
nome, nem MMR/rank (nem o teu, nem o de outros) -- so funciona com a
partida que estiver a decorrer na tua maquina, e tens de ativar a API no
ficheiro de configuracao do jogo primeiro (ver README.md).

Uso:
    python rl_session_tracker.py
    python rl_session_tracker.py --player "NomeDoJogador"
    python rl_session_tracker.py --csv sessao.csv --log eventos.jsonl
    python rl_session_tracker.py --live

Requisitos: nenhum extra -- so a biblioteca padrao do Python.
"""

import argparse
import asyncio
import codecs
import csv
import json
import os
import sys
import time
from datetime import datetime


HOST_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 49123


# --------------------------------------------------------------------------- #
# Frame buffer / parsing (ver nota tecnica no topo do ficheiro)
# --------------------------------------------------------------------------- #

class JsonFrameBuffer:
    """Extrai objetos JSON completos de um stream TCP de JSON concatenado,
    mesmo que cheguem fragmentados entre leituras do socket."""

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


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def player_matches(player_name, filter_name):
    if not filter_name:
        return True
    return filter_name.lower() in player_name.lower()


def fmt_table(players, team_names):
    if not players:
        return "  (sem jogadores na partida ainda)"

    headers = ["Jogador", "Equipa", "Pontos", "Golos", "Assist.", "Defesas",
               "Remates", "Demos", "Boost", "Vel."]
    rows = []
    for p in players:
        team = team_names.get(p.get("TeamNum"), str(p.get("TeamNum", "?")))
        rows.append([
            p.get("Name", "?"),
            team,
            str(p.get("Score", 0)),
            str(p.get("Goals", 0)),
            str(p.get("Assists", 0)),
            str(p.get("Saves", 0)),
            str(p.get("Shots", 0)),
            str(p.get("Demos", 0)),
            f"{p.get('Boost', 0)}",
            f"{p.get('Speed', 0):.0f}" if isinstance(p.get("Speed"), (int, float)) else "-",
        ])

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    sep = "-" * len(line)
    out = [line, sep]
    for r in rows:
        out.append("  ".join(c.ljust(w) for c, w in zip(r, widths)))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Tracker
# --------------------------------------------------------------------------- #

class SessionTracker:
    def __init__(self, args):
        self.args = args
        self.csv_writer = None
        self.csv_file = None
        self.log_file = None
        self.last_print = 0.0
        self.match_guid = None

    def setup_outputs(self):
        if self.args.csv:
            is_new = not os.path.exists(self.args.csv)
            self.csv_file = open(self.args.csv, "a", newline="", encoding="utf-8")
            self.csv_writer = csv.writer(self.csv_file)
            if is_new:
                self.csv_writer.writerow([
                    "timestamp", "match_guid", "player", "team", "score",
                    "goals", "assists", "saves", "shots", "touches",
                    "demos", "boost", "speed", "supersonic", "time_seconds",
                ])
        if self.args.log:
            self.log_file = open(self.args.log, "a", encoding="utf-8")

    def close_outputs(self):
        if self.csv_file:
            self.csv_file.close()
        if self.log_file:
            self.log_file.close()

    def log_raw(self, event_name, data):
        if self.log_file:
            self.log_file.write(json.dumps(
                {"received_at": now_iso(), "Event": event_name, "Data": data}) + "\n")
            self.log_file.flush()

    def write_csv_rows(self, data):
        if not self.csv_writer:
            return
        game = data.get("Game", {})
        for p in data.get("Players", []):
            if not player_matches(p.get("Name", ""), self.args.player):
                continue
            self.csv_writer.writerow([
                now_iso(), data.get("MatchGuid", ""), p.get("Name", ""),
                p.get("TeamNum", ""), p.get("Score", 0), p.get("Goals", 0),
                p.get("Assists", 0), p.get("Saves", 0), p.get("Shots", 0),
                p.get("Touches", 0), p.get("Demos", 0), p.get("Boost", ""),
                p.get("Speed", ""), p.get("bSupersonic", ""),
                game.get("TimeSeconds", ""),
            ])
        self.csv_file.flush()

    def handle_update_state(self, data):
        self.write_csv_rows(data)

        throttle = self.args.refresh
        if time.time() - self.last_print < throttle:
            return
        self.last_print = time.time()

        game = data.get("Game", {})
        team_names = {t.get("TeamNum"): t.get("Name", str(t.get("TeamNum")))
                      for t in game.get("Teams", [])}
        players = [p for p in data.get("Players", [])
                   if player_matches(p.get("Name", ""), self.args.player)]

        if self.args.live:
            os.system("cls" if os.name == "nt" else "clear")

        clock = game.get("TimeSeconds", "?")
        arena = game.get("Arena", "?")
        overtime = " (PRORROGACAO)" if game.get("bOvertime") else ""
        print(f"[{now_iso()}] Arena: {arena} | Tempo restante: {clock}s{overtime}")
        print(fmt_table(players, team_names))
        print()

    def handle_event(self, event_name, data):
        ts = now_iso()
        if event_name == "GoalScored":
            scorer = data.get("Scorer", {}).get("Name", "?")
            assister = data.get("Assister", {}).get("Name")
            speed = data.get("GoalSpeed", "?")
            msg = f"[{ts}] GOLO! {scorer} marcou (velocidade {speed})"
            if assister:
                msg += f" -- assistencia de {assister}"
            print(msg)
        elif event_name == "StatfeedEvent":
            who = data.get("MainTarget", {}).get("Name", "?")
            label = data.get("Type", data.get("EventName", "?"))
            other = data.get("SecondaryTarget", {}).get("Name")
            msg = f"[{ts}] {label}: {who}"
            if other:
                msg += f" -> {other}"
            print(msg)
        elif event_name == "MatchEnded":
            print(f"[{ts}] Partida terminada. Equipa vencedora (TeamNum): "
                  f"{data.get('WinnerTeamNum')}")
        elif event_name in ("MatchCreated", "MatchInitialized"):
            self.match_guid = data.get("MatchGuid")
            print(f"[{ts}] Nova partida iniciada ({event_name}).")
        elif event_name == "MatchDestroyed":
            print(f"[{ts}] Saiu da partida.")
        elif event_name == "RoundStarted":
            print(f"[{ts}] Round comecou.")
        else:
            if self.args.verbose:
                print(f"[{ts}] {event_name}: {json.dumps(data)}")

    def handle_message(self, event_name, data):
        self.log_raw(event_name, data)
        if event_name == "UpdateState":
            self.handle_update_state(data)
        elif event_name is not None:
            self.handle_event(event_name, data)

    async def run(self):
        self.setup_outputs()
        print(f"A tentar ligar a {self.args.host}:{self.args.port} (TCP) ...")
        print("(Certifica-te que o Rocket League esta aberto, com uma partida")
        print(" em curso, e que a Stats API foi ativada no DefaultStatsAPI.ini")
        print(" com a seccao [TAGame.MatchStatsExporter_TA])")
        print()

        backoff = 2
        try:
            while True:
                writer = None
                try:
                    reader, writer = await asyncio.open_connection(self.args.host, self.args.port)
                    print(f"[{now_iso()}] Ligado a {self.args.host}:{self.args.port}. "
                          f"A aguardar dados...\n")
                    backoff = 2
                    frame_buffer = JsonFrameBuffer()
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
                    print(f"[{now_iso()}] Ligacao fechada ({e}). A tentar reconectar "
                          f"em {backoff}s...")
                    await asyncio.sleep(backoff)
                except (ConnectionRefusedError, OSError) as e:
                    print(f"[{now_iso()}] Nao foi possivel ligar ({e}). "
                          f"A tentar novamente em {backoff}s...")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                finally:
                    if writer is not None:
                        writer.close()
        except KeyboardInterrupt:
            print("\nInterrompido pelo utilizador. A encerrar...")
        finally:
            self.close_outputs()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_args():
    parser = argparse.ArgumentParser(
        description="Tracker em tempo real da sessao de Rocket League "
                     "via Stats API local.")
    parser.add_argument("--host", default=HOST_DEFAULT,
                         help=f"Host do socket (padrao: {HOST_DEFAULT})")
    parser.add_argument("--port", type=int, default=PORT_DEFAULT,
                         help=f"Porta do socket (padrao: {PORT_DEFAULT}, tem de "
                              f"corresponder ao DefaultStatsAPI.ini)")
    parser.add_argument("--player", default=None,
                         help="Filtrar apenas um jogador (nome ou parte do nome)")
    parser.add_argument("--csv", default=None,
                         help="Caminho para ficheiro CSV onde gravar stats por tick")
    parser.add_argument("--log", default=None,
                         help="Caminho para ficheiro JSONL com todas as mensagens em bruto")
    parser.add_argument("--refresh", type=float, default=1.0,
                         help="Intervalo minimo (segundos) entre atualizacoes "
                              "impressas no ecra (padrao: 1.0)")
    parser.add_argument("--live", action="store_true",
                         help="Limpa o ecra a cada atualizacao (modo 'dashboard')")
    parser.add_argument("--verbose", action="store_true",
                         help="Mostra tambem eventos menos relevantes "
                              "(BallHit, ClockUpdatedSeconds, etc.)")
    return parser.parse_args()


def main():
    args = parse_args()
    tracker = SessionTracker(args)
    asyncio.run(tracker.run())


if __name__ == "__main__":
    main()
