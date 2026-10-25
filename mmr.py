"""
mmr.py

Calculo (puro, testavel) do MMR registado a mao. A Stats API do Rocket League
nao da' MMR nem rank, por isso o utilizador escreve o valor que ve no jogo e a
app calcula a evolucao e quanto costuma ganhar/perder por vitoria/derrota.
"""

from datetime import datetime, timedelta

FMT = "%Y-%m-%d %H:%M:%S"
MMR_MODES = ["duel", "doubles", "standard"]
MIN_GAIN_SAMPLES = 3


def _parse(ts):
    try:
        return datetime.strptime(ts, FMT)
    except (TypeError, ValueError):
        return None


def valid_mmr(text):
    """Converte o texto escrito pelo utilizador em MMR; None se invalido."""
    try:
        v = int(str(text).strip())
    except (TypeError, ValueError):
        return None
    return v if 0 < v < 5000 else None


def since_ts(days, now=None):
    now = now or datetime.now()
    if days == 0:
        return now.replace(hour=0, minute=0, second=0, microsecond=0).strftime(FMT)
    return (now - timedelta(days=days)).strftime(FMT)


def delta_since(entries, since):
    """Variacao desde `since`: ultimo valor menos o ultimo registo anterior
    (ou o primeiro dentro da janela). None se nao ha' dois pontos."""
    es = sorted(entries, key=lambda e: (e["ts"], e.get("id", 0)))
    if not es:
        return None
    before = [e for e in es if e["ts"] < since]
    inside = [e for e in es if e["ts"] >= since]
    if not inside:
        return None
    base = before[-1] if before else inside[0]
    d = es[-1]["mmr"] - base["mmr"]
    if base is es[-1]:
        return None
    return d


def series(entries):
    """[(n, mmr)] por ordem cronologica, n = 1, 2, ..."""
    es = sorted(entries, key=lambda e: (e["ts"], e.get("id", 0)))
    return [(i + 1, e["mmr"]) for i, e in enumerate(es)]


def gains(entries, matches):
    """Ganho medio por vitoria e perda media por derrota (mesmo modo).

    So' conta intervalos entre dois registos seguidos com EXATAMENTE uma
    partida no meio (senao nao da' para saber o que veio de cada jogo).
    Devolve dict: win_avg, win_n, loss_avg, loss_n (avg None sem amostras).
    """
    es = sorted(entries, key=lambda e: (e["ts"], e.get("id", 0)))
    ms = sorted(matches, key=lambda m: (m["ts"], m.get("id", 0)))
    won, lost = [], []
    for a, b in zip(es, es[1:]):
        between = [m for m in ms if a["ts"] < m["ts"] <= b["ts"]]
        if len(between) != 1:
            continue
        d = b["mmr"] - a["mmr"]
        (won if between[0]["won"] else lost).append(d)

    def avg(x):
        return sum(x) / len(x) if x else None
    return {"win_avg": avg(won), "win_n": len(won),
            "loss_avg": avg(lost), "loss_n": len(lost)}


def summary(entries):
    """Atual, melhor, pior e variacao de hoje / 7 dias."""
    if not entries:
        return None
    es = sorted(entries, key=lambda e: (e["ts"], e.get("id", 0)))
    vals = [e["mmr"] for e in es]
    return {"now": vals[-1], "best": max(vals), "worst": min(vals), "n": len(vals),
            "today": delta_since(es, since_ts(0)), "week": delta_since(es, since_ts(7))}


def table_rows(entries, limit=50):
    """[(ts, mmr, variacao_ou_None)] do mais recente para o mais antigo."""
    es = sorted(entries, key=lambda e: (e["ts"], e.get("id", 0)))
    rows = []
    for i, e in enumerate(es):
        rows.append((e["ts"], e["mmr"], e["mmr"] - es[i - 1]["mmr"] if i else None))
    return list(reversed(rows))[:limit]
