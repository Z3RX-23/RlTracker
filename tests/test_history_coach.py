import datetime as dt
import os

import coach
import history as H


def _rec(i, won=True, mode="doubles", profile="p1", hours=0):
    ts = (dt.datetime(2026, 10, 20, 12, 0, 0) + dt.timedelta(hours=hours or i)).strftime("%Y-%m-%d %H:%M:%S")
    return dict(ts=ts, profile_id=profile, profile_name="Z", platform="steam", mode=mode, won=won,
                estimated=False, my_score=3 if won else 1, opp_score=1 if won else 3,
                goals=1, assists=1, saves=2, shots=3, demos=0, score=300)


def test_history_roundtrip_and_summary(tmp_path):
    h = H.MatchHistory(str(tmp_path / "h.db"))
    for i in range(10):
        assert h.add_match(_rec(i, won=i % 2 == 0))
    h.add_match(_rec(99, mode="duel", profile="p2"))
    s = h.summary("p1")
    assert s["total"]["n"] == 10 and s["total"]["wins"] == 5
    assert s["doubles"]["win_pct"] == 50
    assert h.summary()["total"]["n"] == 11
    assert len(h.recent("p1", None, None, limit=3)) == 3
    assert h.recent("p1", None, "duel") == []


def test_history_csv(tmp_path):
    h = H.MatchHistory(str(tmp_path / "h.db"))
    h.add_match(_rec(1))
    out = tmp_path / "x.csv"
    assert h.export_csv(str(out), None, None, None) == 1
    assert out.read_text(encoding="utf-8").count("\n") >= 2


def test_coach_needs_data():
    tips = coach.analyze([dict(_rec(i), id=i) for i in range(3)])
    assert tips[0]["level"] == "info"


def test_coach_streak_and_modes():
    rows = [dict(_rec(i, won=i < 14), id=i) for i in range(20)]       # ultimas 6 derrotas
    titles = [t["title"] for t in coach.analyze(rows)]
    assert any("6" in t for t in titles)
    rows = ([dict(_rec(i, won=i % 4 != 0, mode="doubles"), id=i) for i in range(12)] +
            [dict(_rec(100 + i, won=i % 4 == 0, mode="standard"), id=100 + i) for i in range(12)])
    assert any("ponto fraco" in t["title"] for t in coach.analyze(rows))


def test_replay_tips():
    rows = [{"won": i % 2, "team_size": 2, "data": {"percent_zero_boost": 25.0, "possession_pct": 50}}
            for i in range(8)]
    assert any("sem boost" in t["title"] for t in coach.analyze_replays(rows))
    assert coach.analyze_replays(rows[:2])[0]["level"] == "info"
