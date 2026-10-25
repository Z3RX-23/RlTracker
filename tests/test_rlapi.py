import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rlapi
from history import MatchHistory

SAMPLE = {"username": "x", "ranked": [
    {"playlistId": 10, "rating": 873, "tier": "Diamond I", "division": "Division IV", "matchesPlayed": 0},
    {"playlistId": 11, "rating": 1344, "tier": "Champion III", "division": "Division II", "matchesPlayed": 169},
    {"playlistId": 13, "rating": 1134, "tier": "Champion I", "division": "Division III", "matchesPlayed": 78},
    {"playlistId": 27, "rating": 900, "matchesPlayed": 5}]}


class P:
    id, name, platform = "p1", "Nome", "epic"


def test_parse_skips_unplayed_and_other_playlists():
    r = rlapi.parse_ranked(SAMPLE)
    assert set(r) == {"doubles", "standard"} and r["doubles"]["mmr"] == 1344
    assert rlapi.parse_ranked(None) == {} and rlapi.parse_ranked({"ranked": [{"playlistId": 11}]}) == {}


def test_refresh_dedupes_and_counts(tmp_path, monkeypatch):
    h = MatchHistory(str(tmp_path / "h.db"))
    st = rlapi.RLApiSettings(str(tmp_path / "r.json")); st.api_key = "k"; st.daily_limit = 3
    monkeypatch.setattr(rlapi, "fetch_stats", lambda k, p, n: SAMPLE)
    assert rlapi.refresh_mmr(h, P, st) == {"doubles": 1344, "standard": 1134}
    assert rlapi.refresh_mmr(h, P, st) == {}                   # nada mudou: nao duplica
    assert len(h.mmr_entries("doubles", "p1")) == 1 and st.used_today() == 2
    rlapi.refresh_mmr(h, P, st)
    try:
        rlapi.refresh_mmr(h, P, st); assert False
    except rlapi.RLApiError:
        pass


def test_settings_roundtrip(tmp_path):
    p = str(tmp_path / "r.json")
    a = rlapi.RLApiSettings(p); a.api_key = " abc "; a.count_call(); a.save()
    b = rlapi.RLApiSettings(p)
    assert b.api_key == "abc" and b.used_today() == 1 and b.left_today() == 9


def test_clean_id_and_lookup(tmp_path):
    assert rlapi.clean_id("https://steamcommunity.com/id/mcguizinho/") == "mcguizinho"
    assert rlapi.clean_id("steamcommunity.com/profiles/76561198000000000?x=1") == "76561198000000000"
    assert rlapi.clean_id("  Nome Com Espaços ") == "Nome Com Espaços"
    st = rlapi.RLApiSettings(str(tmp_path / "r.json")); st.ids["p1"] = "mcguizinho"; st.save()
    assert rlapi.lookup_name(P, rlapi.RLApiSettings(str(tmp_path / "r.json"))) == "mcguizinho"
    assert rlapi.lookup_name(P, rlapi.RLApiSettings(str(tmp_path / "x.json"))) == "Nome"


def test_interval_roundtrip(tmp_path):
    p = str(tmp_path / "r.json")
    a = rlapi.RLApiSettings(p); assert a.interval == 0
    a.interval = 60; a.save()
    assert rlapi.RLApiSettings(p).interval == 60
    a.interval = 45; a.save()                        # valor invalido -> volta ao padrao
    assert rlapi.RLApiSettings(p).interval == 0


def test_server_limits_override_local_count(tmp_path):
    st = rlapi.RLApiSettings(str(tmp_path / "r.json")); st.api_key = "k"
    st.note_headers({"x-ratelimit-requests-limit": "10", "x-ratelimit-requests-remaining": "3",
                     "x-ratelimit-requests-reset": "3600"})
    assert st.left_today() == 3 and st.used_today() == 7
    again = rlapi.RLApiSettings(str(tmp_path / "r.json"))      # persiste
    assert again.left_today() == 3
    st.note_headers({"x-ratelimit-requests-remaining": "0"})   # ex.: resposta 429 sem o resto
    assert st.left_today() == 0
    st.srv_reset_at = 1.0                                      # servidor ja' repos: volta ao contador local
    assert st.left_today() == st.daily_limit - st.used_today()
    st.note_headers({"lixo": "x"})                             # cabecalhos invalidos nao estragam nada
