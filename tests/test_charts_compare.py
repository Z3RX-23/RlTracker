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
