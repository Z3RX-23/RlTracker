import charts
import compare


def _r(ts, won, i=0):
    return {"ts": ts, "won": won, "id": i}


def test_rolling_and_buckets():
    rows = [_r(f"2026-10-0{1 + i // 4} 2{i % 4}:00:00", i % 2 == 0, i) for i in range(12)]
    pts = charts.rolling_win_pct(rows, window=10, min_games=5)
    assert pts[0][0] == 5 and all(0 <= p <= 100 for _, p in pts)
    assert charts.rolling_win_pct(rows[:3]) == []
    hours = charts.by_hour(rows)
    assert sum(b[0] for b in hours) == 12 and hours[20][0] == 3
    assert sum(b[0] for b in charts.by_weekday(rows)) == 12
    assert charts.by_hour([_r("lixo", True)])[0] == [0, 0]       # ts invalido ignorado


def test_best_worst():
    buckets = [[5, 5], [5, 0], [1, 1], [0, 0]]
    assert charts.best_worst(buckets) == (0, 1)
    assert charts.best_worst([[5, 5], [1, 0]]) is None            # so' um balde com jogos suficientes
    assert charts.best_worst([[4, 2], [4, 2]]) is None            # iguais


def test_compare_match_verdicts():
    row = {"goals": 3, "assists": 0, "saves": 2, "shots": 9, "score": 300}
    avg = {"goals_avg": 1.0, "assists_avg": 1.5, "saves_avg": 2.0, "shots_avg": 3.0, "score_avg": 300.0}
    by = {i["label"]: i for i in compare.compare_match(row, avg)}
    assert by["Golos"]["good"] is True and by["Assistências"]["good"] is False
    assert by["Defesas"]["good"] is None and by["Remates"]["good"] is None   # remates: neutro


def test_compare_replay_zero_boost_lower_is_better():
    items = {i["label"]: i for i in compare.compare_replay(
        {"percent_zero_boost": 30.0, "possession_pct": 60.0}, {"percent_zero_boost": 20.0, "possession_pct": 50.0})}
    assert items["Sem boost"]["good"] is False and items["Posse"]["good"] is True
    assert compare.compare_replay({}, {"possession_pct": 50}) == []


def _mk(ts, won, score=100, **kw):
    r = {"id": 0, "ts": ts, "won": won, "score": score, "goals": 1}
    r.update(kw)
    return r


def test_sessions_split_by_gap():
    rows = [_mk("2026-10-24 10:00:00", 1), _mk("2026-10-24 10:20:00", 0),
            _mk("2026-10-24 12:30:00", 1), _mk("2026-10-24 12:40:00", 1)]
    s = charts.sessions(rows)
    assert [len(x) for x in s] == [2, 2]


def test_by_session_position_and_cap():
    rows = [_mk("2026-10-24 10:%02d:00" % i, i % 2) for i in range(0, 12)]
    b = charts.by_session_position(rows, cap=4)
    assert [x[0] for x in b] == [1, 1, 1, 9]          # o ultimo junta os restantes
    assert sum(x[1] for x in b) == 6


def test_after_result():
    rows = [_mk("2026-10-24 10:00:00", 1), _mk("2026-10-24 10:10:00", 0),
            _mk("2026-10-24 10:20:00", 1), _mk("2026-10-24 10:30:00", 1),
            _mk("2026-10-24 15:00:00", 0)]
    first, aw, al = charts.after_result(rows)
    assert first == [2, 1]        # 10:00 (ganhou) e 15:00 (perdeu)
    assert aw == [2, 1]           # depois de ganhar: 10:10 (perdeu) e 10:30 (ganhou)
    assert al == [1, 1]           # depois de perder: 10:20 (ganhou)


def test_rolling_avg():
    rows = [_mk("2026-10-24 10:%02d:00" % i, 1, score=i * 10) for i in range(8)]
    pts = charts.rolling_avg(rows, "score", window=4, min_games=4)
    assert pts[0] == (4, 15.0) and pts[-1] == (8, 55.0)
    assert charts.rolling_avg(rows[:2], "score") == []
