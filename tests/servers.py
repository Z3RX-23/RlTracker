"""Servidores HTTP simulados (Ballchasing e LLM) para os testes -- porta livre, thread de fundo."""
import hashlib
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def _serve(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _json(h, code, obj):
    raw = json.dumps(obj).encode()
    h.send_response(code)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(raw)))
    h.end_headers()
    h.wfile.write(raw)


def start_ballchasing(key="chave-teste"):
    seen, state = {}, {"uploads": 0}

    def replay_json(rid, ok):
        if not ok:
            return {"id": rid, "status": "pending"}
        rnd = random.Random(rid)

        def player(name, me=False):
            return {"name": name, "id": {"platform": "steam", "id": "1"}, "stats": {
                "core": {"shots": 3, "goals": 1, "saves": 2, "assists": 1, "score": 300},
                "boost": {"bpm": 350.0, "percent_zero_boost": 20.0 if me else 8.0,
                          "percent_full_boost": 8.0, "avg_amount": 35.0},
                "movement": {"avg_speed": 1400.0, "percent_ground": 60},
                "positioning": {"percent_behind_ball": 40.0 if me else 55.0,
                                "percent_defensive_third": 38.0, "percent_offensive_third": 25.0,
                                "percent_neutral_third": 30, "percent_most_forward": 45.0,
                                "percent_most_back": 20.0},
                "demo": {"inflicted": 1, "taken": 2}}}
        return {"id": rid, "status": "ok", "link": f"http://x/replay/{rid}",
                "date": f"2026-10-{rnd.randint(10, 24):02d}T12:15:00+01:00", "duration": 330,
                "playlist_name": "Ranked Doubles", "team_size": 2,
                "blue": {"stats": {"ball": {"possession_time": 150}},
                         "players": [player("Z3RX", me=True), player("Mate")]},
                "orange": {"stats": {"ball": {"possession_time": 140}},
                           "players": [player("Opp1"), player("Opp2")]}}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _auth(self):
            if self.headers.get("Authorization") != key:
                _json(self, 401, {"error": "invalid API key"})
                return False
            return True

        def do_GET(self):
            if not self._auth():
                return
            if self.path.rstrip("/") == "/api":
                return _json(self, 200, {"name": "Teste", "quota": {"uploads_in_24h": {
                    "used": state["uploads"], "max": 100}}})
            if self.path.startswith("/api/replays/"):
                rid = self.path.rsplit("/", 1)[1]
                seen[rid] = seen.get(rid, 0) + 1
                return _json(self, 200, replay_json(rid, seen[rid] > 1))
            _json(self, 404, {"error": "nope"})

        def do_POST(self):
            if not self._auth():
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            rid = hashlib.md5(body.split(b"\r\n\r\n", 1)[1][:200]).hexdigest()[:12]
            if rid in seen:
                return _json(self, 409, {"id": rid, "error": "duplicate replay"})
            seen[rid] = 0
            state["uploads"] += 1
            _json(self, 201, {"id": rid, "location": f"/replay/{rid}"})

    return _serve(H)


def start_llm(key="k-ok", text="Resumo. [DATA]"):
    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                return _json(self, 404, {"error": {"message": "nope"}})
            if self.headers.get("Authorization") != "Bearer " + key:
                return _json(self, 401, {"error": {"message": "Invalid API Key"}})
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen["body"] = body
            _json(self, 200, {"choices": [{"message": {"role": "assistant", "content": text}}]})

    srv, url = _serve(H)
    srv.seen = seen
    return srv, url + "/v1"
