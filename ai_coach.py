"""
ai_coach.py

Analise com IA (cloud): junta as tuas stats (historico + replays) num resumo
e pede a um modelo de linguagem conclusoes e dicas em portugues.

Usa o formato "OpenAI compativel" (POST {base}/chat/completions), que
Groq, Google Gemini, OpenRouter e outros aceitam -- por isso o servico,
o modelo e a chave sao definicoes tuas, em ai.json (ao lado da app/.exe).
A chave fica em texto simples nesse ficheiro: nao o partilhes.

So' vai para o servico um resumo numerico (medias, percentagens, as dicas
do treinador). Nao vai o nome do perfil nem ficheiros de replays.
"""

import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request

import coach
from history import MODE_LABELS, MODES
from i18n import get_language, tr

if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_PATH = os.path.join(_BASE_DIR, "ai.json")
USER_AGENT = "RL-Live-Dashboard/1.0"

# nome -> (base_url, modelo sugerido). O modelo e' sempre editavel: os
# servicos mudam os modelos disponiveis (e os planos gratuitos) com frequencia.
PRESETS = {
    "Groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
    "Google Gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash"),
    "OpenRouter": ("https://openrouter.ai/api/v1", ""),
    "Outro": ("", ""),
}

AI_LANGUAGES = {"auto": "Como a app", "pt": "Português", "en": "English", "es": "Español"}
_LANG_NAMES = {"pt": "European Portuguese (Portugal)", "en": "English", "es": "Spanish"}

SYSTEM_PROMPT = (
    "You are a Rocket League coach. You receive aggregated statistics for one player "
    "(match history and, if present, replay data). Reply in {lang}, directly and concretely.\n"
    "Rules: use ONLY the numbers provided and never invent data; if something is not in the "
    "data, do not comment on it. If there are few matches, say the conclusions are "
    "provisional. You have no information about mechanics or rotations beyond what is in "
    "the data.\n"
    "Mark the nature of every statement in sections 2 and 3 with a tag at the end of the "
    "sentence: [DATA] when it only restates a number that was provided (quote the number), "
    "[HYPOTHESIS] when it is your interpretation or a guess about the cause. Use these two "
    "tags exactly, in English, whatever language you reply in.\n"
    "Structure, in plain text (no heavy markdown):\n"
    "1) Summary in 2 sentences.\n"
    "2) Strengths (up to 3).\n"
    "3) Things to improve (up to 3): for each one, the number that supports it and one "
    "concrete action to practise.\n"
    "4) Focus for the next 10 matches: a single thing.\n"
    "At most 250 words.")


def system_prompt(settings):
    code = settings.language
    if code == "auto":
        code = get_language()
    return SYSTEM_PROMPT.format(lang=_LANG_NAMES.get(code, "European Portuguese (Portugal)"))


class AIError(Exception):
    pass


_TAG_RE = re.compile(r"\s*[\[(](DATA|DADO|HYPOTHESIS|HIP[OÓ]TESE)[\])]", re.IGNORECASE)


def split_tags(text):
    """Separa o texto da IA em [(texto, marca)]; marca = None | "data" | "hyp".

    A marca vem no fim da frase ([DATA]/[HYPOTHESIS]); o texto antes dela
    (desde a ultima marca) fica com essa marca.
    """
    parts, pos = [], 0
    for m in _TAG_RE.finditer(text):
        chunk = text[pos:m.start()]
        mark = "data" if m.group(1).upper() in ("DATA", "DADO") else "hyp"
        cut = chunk.rfind("\n") + 1        # so' a ultima linha leva a marca
        if cut:
            parts.append((chunk[:cut], None))
        if chunk[cut:].strip():
            parts.append((chunk[cut:], mark))
        pos = m.end()
    rest = text[pos:]
    if rest:
        parts.append((rest, None))
    return parts


def preview(settings, summary):
    """Tudo o que sai para o servico (sem a chave)."""
    return (tr("Destino: {url}", url=settings.base_url.rstrip("/") + "/chat/completions") + "\n" +
            tr("Modelo: {m}", m=settings.model) + "\n\n" +
            tr("INSTRUÇÕES (sistema)") + "\n" + system_prompt(settings) + "\n\n" +
            tr("DADOS (as tuas stats)") + "\n" + summary)


class AISettings:
    def __init__(self, path=SETTINGS_PATH):
        self.path = path
        self.provider = "Groq"
        self.base_url, self.model = PRESETS["Groq"]
        self.api_key = ""
        self.language = "auto"
        self.last_error = None
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(d, dict):
            return
        self.provider = d.get("provider") if d.get("provider") in PRESETS else "Outro"
        self.base_url = str(d.get("base_url", self.base_url)).strip()
        self.model = str(d.get("model", self.model)).strip()
        self.api_key = str(d.get("api_key", "")).strip()
        self.language = d.get("language") if d.get("language") in AI_LANGUAGES else "auto"

    def save(self):
        text = json.dumps({"provider": self.provider, "base_url": self.base_url,
                           "model": self.model, "api_key": self.api_key,
                           "language": self.language},
                          ensure_ascii=False, indent=2)
        self.last_error = None
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.path)
            return True
        except OSError:
            pass
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(text)
            return True
        except OSError as e:
            self.last_error = f"{self.path}: {e}"
            return False

    def pick_provider(self, name):
        self.provider = name
        url, model = PRESETS[name]
        if name != "Outro":
            self.base_url, self.model = url, model

    def ready(self):
        return bool(self.api_key and self.base_url and self.model)


# ── Resumo dos dados ────────────────────────────────────────────────────────

def _f(v, digits=1, suffix=""):
    return "n/d" if v is None else f"{v:.{digits}f}{suffix}"


def build_summary(history, replay_store, profile_id, since=None):
    """Texto com os numeros do jogador (sem nomes)."""
    lines = []
    summ = history.summary(profile_id, since)
    tot = summ["total"]
    lines.append(f"HISTÓRICO DE PARTIDAS (último período): {tot['n']} partidas, "
                 f"{tot['wins']} vitórias, {tot['losses']} derrotas, win% {tot['win_pct']:.0f}%.")
    for m in list(MODES) + [k for k in summ if k not in MODES and k != "total"]:
        d = summ.get(m)
        if not d or not d["n"]:
            continue
        lines.append(f"- {MODE_LABELS.get(m, m)}: {d['n']} jogos, win% {d['win_pct']:.0f}%, "
                     f"golos/jogo {d['goals_avg']:.2f}, assistências/jogo {d['assists_avg']:.2f}, "
                     f"defesas/jogo {d['saves_avg']:.2f}, remates/jogo {d['shots_avg']:.2f}, "
                     f"precisão {d['accuracy']:.0f}%, pontos/jogo {d['score_avg']:.0f}")
    recent = history.recent(profile_id, since, None, limit=10)
    if recent:
        seq = "".join("V" if r["won"] else "D" for r in recent)     # mais recente primeiro
        lines.append(f"Últimas {len(recent)} partidas (mais recente primeiro): {seq}")
    rows = history.recent(profile_id, since, None, limit=500)
    for t in coach.analyze(rows)[:6]:
        lines.append(f"Observação automática: {t['title']} — {t['text']}")

    if replay_store is not None:
        rrows = replay_store.replays(profile_id, limit=300)
        if rrows:
            avg = coach.replay_averages(rrows)
            lines.append("")
            lines.append(f"REPLAYS ANALISADOS (Ballchasing): {len(rrows)} replays.")
            lines.append("Médias: posse " + _f(avg.get("possession_pct"), 0, "%") +
                         ", boost/min " + _f(avg.get("bpm"), 0) +
                         ", tempo sem boost " + _f(avg.get("percent_zero_boost"), 0, "%") +
                         ", boost cheio " + _f(avg.get("percent_full_boost"), 0, "%") +
                         ", atrás da bola " + _f(avg.get("percent_behind_ball"), 0, "%") +
                         ", mais avançado da equipa " + _f(avg.get("percent_most_forward"), 0, "%") +
                         ", mais recuado " + _f(avg.get("percent_most_back"), 0, "%") +
                         ", terço defensivo/neutro/ofensivo " +
                         _f(avg.get("percent_defensive_third"), 0, "%") + "/" +
                         _f(avg.get("percent_neutral_third"), 0, "%") + "/" +
                         _f(avg.get("percent_offensive_third"), 0, "%") +
                         ", velocidade média " + _f(avg.get("avg_speed"), 0) +
                         ", demos feitas/sofridas por jogo " + _f(avg.get("demo_inflicted")) + "/" +
                         _f(avg.get("demo_taken")))
            wins = [r for r in rrows if r.get("won") == 1]
            losses = [r for r in rrows if r.get("won") == 0]
            if len(wins) >= 2 and len(losses) >= 2:
                wa, la = coach.replay_averages(wins), coach.replay_averages(losses)
                parts = []
                for key, label in (("possession_pct", "posse"), ("percent_zero_boost", "sem boost"),
                                   ("percent_behind_ball", "atrás da bola"), ("bpm", "boost/min")):
                    if key in wa and key in la:
                        parts.append(f"{label}: vitórias {wa[key]:.0f} vs derrotas {la[key]:.0f}")
                if parts:
                    lines.append(f"Vitórias ({len(wins)}) vs derrotas ({len(losses)}) nos replays: " +
                                 "; ".join(parts))
            for t in coach.analyze_replays(rrows)[:6]:
                lines.append(f"Observação automática (replays): {t['title']} — {t['text']}")
    return "\n".join(lines)


# ── Pedido ao modelo ────────────────────────────────────────────────────────

def ask(settings, summary, timeout=90):
    if not settings.ready():
        raise AIError(tr("Falta a chave, o endereço ou o modelo."))
    url = settings.base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": settings.model,
        "messages": [{"role": "system", "content": system_prompt(settings)},
                     {"role": "user", "content": "These are my statistics:\n\n" + summary}],
        "temperature": 0.3, "max_tokens": 900}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + settings.api_key,
        "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            err = json.loads(e.read().decode("utf-8"))
            if isinstance(err, list) and err:
                err = err[0]
            detail = (err.get("error") or {}).get("message") if isinstance(err, dict) else ""
        except (ValueError, UnicodeDecodeError, AttributeError):
            pass
        reason = {401: tr("chave inválida"), 403: tr("sem permissão (verifica a chave e o plano)"),
                  404: tr("modelo ou endereço não encontrado"), 429: tr("limite de pedidos atingido, tenta mais tarde")
                  }.get(e.code, tr("erro do serviço"))
        raise AIError(f"{reason} ({e.code})" + (f": {detail[:200]}" if detail else ""))
    except (urllib.error.URLError, OSError) as e:
        raise AIError(tr("Sem ligação ao serviço: {r}", r=getattr(e, 'reason', e)))
    except ValueError:
        raise AIError(tr("Resposta inválida do serviço."))
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AIError(tr("O serviço não devolveu texto."))
    return (text or "").strip() or "(resposta vazia)"


def ask_async(settings, summary, callback):
    """callback(texto, erro) chamado numa thread de fundo."""
    def work():
        try:
            callback(ask(settings, summary), None)
        except AIError as e:
            callback(None, str(e))
        except Exception as e:           # nunca deixar a thread morrer em silencio
            callback(None, f"Erro inesperado: {e}")
    threading.Thread(target=work, daemon=True).start()
