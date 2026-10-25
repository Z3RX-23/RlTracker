import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mmr
from history import MatchHistory


def E(ts, v, i=0):
    return {"ts": ts, "mmr": v, "id": i}


def M(ts, won, i=0):
    return {"ts": ts, "won": won, "id": i}


def test_valid():
    assert mmr.valid_mmr(" 1043 ") == 1043
    assert mmr.valid_mmr("abc") is None and mmr.valid_mmr("0") is None and mmr.valid_mmr("99999") is None


def test_gains_single_game_only():
    es = [E("2026-01-01 10:00:00", 1000, 1), E("2026-01-01 10:10:00", 1010, 2),
          E("2026-01-01 10:20:00", 1000, 3), E("2026-01-01 10:50:00", 1005, 4)]
    ms = [M("2026-01-01 10:05:00", 1), M("2026-01-01 10:15:00", 0),
          M("2026-01-01 10:30:00", 1), M("2026-01-01 10:40:00", 1)]   # 2 jogos no ultimo intervalo
    g = mmr.gains(es, ms)
    assert g["win_n"] == 1 and g["win_avg"] == 10
    assert g["loss_n"] == 1 and g["loss_avg"] == -10


def test_delta_and_summary():
    es = [E("2026-01-01 10:00:00", 1000, 1), E("2026-01-05 10:00:00", 1050, 2), E("2026-01-06 09:00:00", 1030, 3)]
    assert mmr.delta_since(es, "2026-01-05 00:00:00") == 30   # base = ultimo antes da janela (1000)
    assert mmr.delta_since(es, "2026-02-01 00:00:00") is None
    assert mmr.delta_since(es[:1], "2026-01-01 00:00:00") is None
    assert mmr.series(es) == [(1, 1000), (2, 1050), (3, 1030)]


def test_db(tmp_path):
    h = MatchHistory(str(tmp_path / "h.db"))
    assert h.add_mmr("doubles", 1000, "p1", "2026-01-01 10:00:00")
    assert h.add_mmr("doubles", 1020, "p1", "2026-01-01 11:00:00")
    assert h.add_mmr("duel", 900, "p1")
    assert [e["mmr"] for e in h.mmr_entries("doubles", "p1")] == [1000, 1020]
    assert h.delete_last_mmr("doubles", "p1")
    assert [e["mmr"] for e in h.mmr_entries("doubles", "p1")] == [1000]
    assert h.mmr_entries("doubles", "outro") == []


def test_table_rows():
    es = [E("2026-01-01 10:00:00", 1000, 1), E("2026-01-02 10:00:00", 1015, 2), E("2026-01-03 10:00:00", 1005, 3)]
    r = mmr.table_rows(es)
    assert r[0] == ("2026-01-03 10:00:00", 1005, -10) and r[-1][2] is None and len(r) == 3
    assert len(mmr.table_rows(es, limit=2)) == 2
