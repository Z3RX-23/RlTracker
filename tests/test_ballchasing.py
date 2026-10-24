import os
import sqlite3
import time

import ballchasing as bc
import pytest
from profiles import ProfileManager

from servers import start_ballchasing


@pytest.fixture
def env(tmp_path, monkeypatch):
    srv, url = start_ballchasing()
    monkeypatch.setenv("BALLCHASING_URL", url)
    monkeypatch.setattr(bc, "POLL_EVERY", 0.05)
    rdir = tmp_path / "Demos"
    rdir.mkdir()
    for i in range(4):
        p = rdir / f"r{i}.replay"
        p.write_bytes(os.urandom(500) + bytes([i]) * 300)
        os.utime(p, (time.time() - 100, time.time() - 100))
    pm = ProfileManager(str(tmp_path / "p.json"), str(tmp_path / "none.ini"))
    pm.update(pm.active().id, name="z3rx")
    st = bc.Settings(str(tmp_path / "bc.json"))
    st.replay_dirs, st.since, st.token = [str(rdir)], "Tudo", "chave-teste"
    store = bc.ReplayStore(str(tmp_path / "r.db"))
    msgs = []
    sync = bc.ReplaySync(st, store, pm, lambda k, p: msgs.append((k, p)))
    yield sync, st, store, pm, msgs, tmp_path
    srv.shutdown()


def test_missing_and_wrong_key(env):
    sync, st, store, pm, msgs, _ = env
    st.token = ""
    sync.run_once()
    assert "chave" in msgs[-1][1].lower()
    st.token = "errada"
    sync.run_once()
    assert "401" in msgs[-1][1]


def test_sync_matches_and_is_idempotent(env):
    sync, st, store, pm, msgs, tmp = env
    sync.run_once()
    rows = store.replays(pm.active().id)
    assert len(rows) == 4 and rows[0]["data"]["percent_zero_boost"] == 20.0
    msgs.clear()
    sync.run_once()
    assert "em dia" in msgs[-1][1]                         # nada novo
    sqlite3.connect(store.path).execute("DELETE FROM files").connection.commit()
    sync.run_once()                                       # 409 duplicado: mesmo id, sem duplicar
    assert len(store.replays()) == 4


def test_claim_account_by_id(env):
    sync, st, store, pm, msgs, _ = env
    pm.update(pm.active().id, name="outro nome")            # nome nao bate -> replays sem dono
    sync.run_once()
    assert store.replays(pm.active().id) == []
    cands = store.top_candidates(set())
    assert cands and cands[0]["pid"] == "1"
    pm.add_replay_id(pm.active().id, f"{cands[0]['platform']}:{cands[0]['pid']}")
    sync.rematch_async()
    for _ in range(100):
        if store.replays(pm.active().id):
            break
        time.sleep(0.05)
    assert len(store.replays(pm.active().id)) == 4
