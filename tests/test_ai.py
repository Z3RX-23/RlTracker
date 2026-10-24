import ai_coach
import pytest

from servers import start_llm


def test_split_tags():
    parts = ai_coach.split_tags("Resumo.\n- A [DATA]\n- B [HYPOTHESIS]\nFim")
    assert parts == [("Resumo.\n", None), ("- A", "data"), ("\n", None), ("- B", "hyp"), ("\nFim", None)]
    assert ai_coach.split_tags("sem marcas") == [("sem marcas", None)]
    assert ai_coach.split_tags("x (DADO)")[0][1] == "data"


def test_preview_never_contains_key(tmp_path):
    s = ai_coach.AISettings(str(tmp_path / "ai.json"))
    s.api_key, s.base_url, s.model = "SEGREDO", "http://h/v1", "m"
    text = ai_coach.preview(s, "numeros")
    assert "SEGREDO" not in text and "http://h/v1/chat/completions" in text and "numeros" in text
    assert "[DATA]" in text and "[HYPOTHESIS]" in text         # as marcas vao nas instrucoes


def test_ask_success_and_errors(tmp_path):
    srv, url = start_llm("k-ok", "Boa [DATA]")
    s = ai_coach.AISettings(str(tmp_path / "ai.json"))
    s.base_url, s.model, s.api_key = url, "m", "k-ok"
    assert ai_coach.ask(s, "dados") == "Boa [DATA]"
    assert srv.seen["body"]["messages"][1]["content"].endswith("dados")
    s.api_key = "errada"
    with pytest.raises(ai_coach.AIError) as e:
        ai_coach.ask(s, "dados")
    assert "401" in str(e.value)
    s.api_key = ""
    with pytest.raises(ai_coach.AIError):
        ai_coach.ask(s, "dados")
    srv.shutdown()
