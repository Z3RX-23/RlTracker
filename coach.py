"""
coach.py

Treinador offline: le as partidas do historico e devolve dicas por regras.
Sem rede e sem IA -- so' compara as tuas stats entre modos, entre vitorias
e derrotas e entre jogos recentes e mais antigos.

Limite honesto: a Stats API so' da' golos, assistencias, defesas, remates,
pontos e placar. Nao ha' posicionamento nem boost, por isso as dicas falam
de tendencias e pontos fracos, nao de mecanica.

Cada dica e' um dict: {"level": "good"|"warn"|"info", "title", "text"}.
"""

from history import MODE_LABELS
from i18n import tr

MIN_GAMES = 8          # abaixo disto so' avisamos que faltam dados
MIN_MODE_GAMES = 5     # jogos minimos num modo para o comparar


def _avg(rows, key):
    return sum(r[key] or 0 for r in rows) / len(rows) if rows else 0.0


def _win_pct(rows):
    return 100.0 * sum(1 for r in rows if r["won"]) / len(rows) if rows else 0.0


def _tip(level, title, text):
    return {"level": level, "title": title, "text": text}


def analyze(rows):
    """rows: partidas do historico (qualquer ordem). Devolve lista de dicas."""
    rows = sorted(rows, key=lambda r: (r["ts"], r.get("id", 0)))  # antigas -> recentes
    n = len(rows)
    if n < MIN_GAMES:
        return [_tip("info", tr("Ainda há poucos dados"),
                     tr("Tens {n} partida(s) neste filtro. Com pelo menos {m} "
                        "consigo começar a comparar modos e tendências.", n=n, m=MIN_GAMES))]

    tips = []
    total_pct = _win_pct(rows)

    # --- sequencia atual ------------------------------------------------------
    streak, last = 0, rows[-1]["won"]
    for r in reversed(rows):
        if r["won"] != last:
            break
        streak += 1
    if not last and streak >= 3:
        tips.append(_tip("warn", tr("{n} derrotas seguidas", n=streak),
                         tr("Depois de uma série má costuma compensar fazer uma pausa curta "
                            "antes da próxima partida.")))
    elif last and streak >= 4:
        tips.append(_tip("good", tr("{n} vitórias seguidas", n=streak), tr("Estás em boa fase, continua.")))

    # --- forma recente vs antes ---------------------------------------------
    if n >= 20:
        recent, older = rows[-10:], rows[:-10]
        d = _win_pct(recent) - _win_pct(older)
        if d >= 15:
            tips.append(_tip("good", tr("Estás a melhorar"),
                             tr("Nas últimas 10 partidas ganhaste {a:.0f}%, contra {b:.0f}% antes.",
                                a=_win_pct(recent), b=_win_pct(older))))
        elif d <= -15:
            tips.append(_tip("warn", tr("Quebra recente"),
                             tr("Nas últimas 10 partidas ganhaste {a:.0f}%, contra {b:.0f}% antes. "
                                "Vê se mudaste alguma coisa (modo, horário, cansaço).",
                                a=_win_pct(recent), b=_win_pct(older))))

    # --- melhor e pior modo ---------------------------------------------------
    by_mode = {}
    for r in rows:
        by_mode.setdefault(r["mode"], []).append(r)
    ranked = [(m, rs) for m, rs in by_mode.items() if len(rs) >= MIN_MODE_GAMES]
    if len(ranked) >= 2:
        ranked.sort(key=lambda x: _win_pct(x[1]))
        (wm, wrs), (bm, brs) = ranked[0], ranked[-1]
        if _win_pct(brs) - _win_pct(wrs) >= 15:
            tips.append(_tip("warn", tr("O teu ponto fraco é {m}", m=tr(MODE_LABELS.get(wm, wm))),
                             tr("Ganhas {a:.0f}% em {m} ({n} jogos) contra {b:.0f}% em {m2}. "
                                "Vale a pena treinar mais esse modo.",
                                a=_win_pct(wrs), m=tr(MODE_LABELS.get(wm, wm)), n=len(wrs),
                                b=_win_pct(brs), m2=tr(MODE_LABELS.get(bm, bm)))))
        else:
            tips.append(_tip("info", tr("Rendimento equilibrado entre modos"),
                             tr("A diferença entre o teu melhor e pior modo é de "
                                "{d:.0f} pontos percentuais.", d=_win_pct(brs) - _win_pct(wrs))))

    # --- remates ----------------------------------------------------------------
    shots, goals = _avg(rows, "shots"), _avg(rows, "goals")
    acc = 100.0 * goals / shots if shots else 0.0
    if shots >= 3 and acc < 25:
        tips.append(_tip("warn", tr("Finalização"),
                         tr("Rematas {s:.1f}x por jogo mas só {a:.0f}% entram. "
                            "Tenta preparar melhor o remate (esperar pela bola, procurar o canto) "
                            "em vez de rematar sempre que podes.", s=shots, a=acc)))
    elif shots < 2 and n >= MIN_GAMES:
        tips.append(_tip("info", tr("Remata mais"),
                         tr("Só fazes {s:.1f} remates por jogo. Mais remates dão mais "
                            "hipóteses de golo e rebotes para os colegas.", s=shots)))
    elif acc >= 45 and shots >= 2:
        tips.append(_tip("good", tr("Boa pontaria"), tr("{a:.0f}% dos teus remates são golo.", a=acc)))

    # --- passes (assistencias por golo) em modos de equipa ----------------------
    team = [r for r in rows if r["mode"] in ("doubles", "standard")]
    if len(team) >= MIN_MODE_GAMES:
        g, a = _avg(team, "goals"), _avg(team, "assists")
        if g >= 1 and a / g < 0.3:
            tips.append(_tip("info", tr("Joga mais pela equipa"),
                             tr("Fazes {g:.1f} golos mas só {a:.1f} assistências por jogo "
                                "em 2v2/3v3. Tenta mais passes para os colegas em vez de "
                                "resolver tudo sozinho.", g=g, a=a)))

    # --- defesas ---------------------------------------------------------------
    if len(team) >= MIN_MODE_GAMES:
        losses = [r for r in team if not r["won"]]
        wins = [r for r in team if r["won"]]
        if len(losses) >= 3 and len(wins) >= 3:
            sv_l, sv_w = _avg(losses, "saves"), _avg(wins, "saves")
            if sv_w - sv_l >= 0.7:
                tips.append(_tip("warn", tr("Defesa nas derrotas"),
                                 tr("Nas derrotas fazes {l:.1f} defesas por jogo, contra "
                                    "{w:.1f} nas vitórias. Perdes mais quando defendes menos: "
                                    "volta mais cedo à baliza.", l=sv_l, w=sv_w)))

    # --- pontos nas derrotas vs vitorias (quanto contribuis) -----------------
    losses_all = [r for r in rows if not r["won"]]
    wins_all = [r for r in rows if r["won"]]
    if len(losses_all) >= 3 and len(wins_all) >= 3:
        if _avg(losses_all, "score") >= _avg(wins_all, "score") * 0.9:
            tips.append(_tip("info", tr("Contribuis mesmo a perder"),
                             tr("A tua pontuação nas derrotas é parecida com a das vitórias. "
                                "A diferença costuma estar na equipa, não só em ti.")))

    # --- resultados apertados --------------------------------------------------
    close = [r for r in rows
             if r.get("my_score") is not None and r.get("opp_score") is not None
             and abs(r["my_score"] - r["opp_score"]) == 1]
    if len(close) >= 8:
        cp = _win_pct(close)
        if cp <= 35:
            tips.append(_tip("warn", tr("Jogos decididos por 1 golo"),
                             tr("Perdes a maioria dos jogos apertados (ganhas {c:.0f}% de "
                                "{n}). Mantém a calma no final: menos riscos e "
                                "mais controlo quando o jogo está empatado.", c=cp, n=len(close))))
        elif cp >= 65:
            tips.append(_tip("good", tr("Fechas bem os jogos"),
                             tr("Ganhas {c:.0f}% dos {n} jogos decididos por 1 golo.", c=cp, n=len(close))))

    if not tips:
        tips.append(_tip("info", tr("Sem alertas"),
                         tr("Ganhas {p:.0f}% em {n} partidas e nada se destaca. "
                            "Continua a jogar para eu afinar as comparações.", p=total_pct, n=n)))
    order = {"warn": 0, "good": 1, "info": 2}
    tips.sort(key=lambda t: order[t["level"]])
    return tips


# ── Dicas a partir dos replays (Ballchasing) ────────────────────────────────

MIN_REPLAYS = 5


def replay_averages(rows):
    """Media de cada stat dos replays (so' dos que a tem)."""
    sums, counts = {}, {}
    for r in rows:
        for k, v in (r.get("data") or {}).items():
            if isinstance(v, (int, float)):
                sums[k] = sums.get(k, 0.0) + v
                counts[k] = counts.get(k, 0) + 1
    return {k: sums[k] / counts[k] for k in sums}


def analyze_replays(rows):
    """rows: linhas de ReplayStore.replays(). Devolve dicas (mesmo formato)."""
    n = len(rows)
    if n < MIN_REPLAYS:
        return [_tip("info", tr("Replays: ainda há poucos"),
                     tr("Tens {n} replay(s) analisado(s). Com pelo menos {m} "
                        "consigo falar de boost e posicionamento.", n=n, m=MIN_REPLAYS))]
    avg = replay_averages(rows)
    team = [r for r in rows if (r.get("team_size") or 0) >= 2]
    tavg = replay_averages(team) if len(team) >= MIN_REPLAYS else {}
    tips = []

    zero = avg.get("percent_zero_boost")
    if zero is not None and zero >= 15:
        tips.append(_tip("warn", tr("Ficas muitas vezes sem boost"),
                         tr("Passas {z:.0f}% do tempo com 0 de boost. Apanha as bolinhas "
                            "pequenas no caminho e evita gastar tudo em ataques sem apoio.", z=zero)))
    full = avg.get("percent_full_boost")
    if full is not None and full >= 18:
        tips.append(_tip("info", tr("Boost cheio parado"),
                         tr("Estás {f:.0f}% do tempo com o boost cheio. Gastá-lo mais "
                            "(velocidade, desafios) dá-te mais presença no jogo.", f=full)))

    behind = tavg.get("percent_behind_ball")
    if behind is not None and behind < 45:
        tips.append(_tip("warn", tr("Estás muito à frente da bola"),
                         tr("Só ficas atrás da bola {b:.0f}% do tempo em 2v2/3v3. "
                            "Isto costuma ser sinal de perseguir a bola: recua para dar "
                            "cobertura ao colega.", b=behind)))
    fwd, back = tavg.get("percent_most_forward"), tavg.get("percent_most_back")
    if fwd is not None and back is not None and (fwd - back) >= 15:
        tips.append(_tip("info", tr("Jogas sempre à frente da equipa"),
                         tr("És o jogador mais avançado {f:.0f}% do tempo e o mais recuado "
                            "{b:.0f}%. Alterna mais de posição com os colegas.", f=fwd, b=back)))
    dfn, off = avg.get("percent_defensive_third"), avg.get("percent_offensive_third")
    if dfn is not None and off is not None and dfn - off >= 15:
        tips.append(_tip("info", tr("Muito tempo no teu terço"),
                         tr("{d:.0f}% do tempo no terço defensivo contra {o:.0f}% no "
                            "ofensivo: o jogo passa-se mais do teu lado do campo.", d=dfn, o=off)))

    poss = avg.get("possession_pct")
    if poss is not None and poss <= 44:
        tips.append(_tip("warn", tr("Pouca posse de bola"),
                         tr("A tua equipa tem a bola {p:.0f}% do tempo. Tenta controlar "
                            "mais o ritmo (dribles curtos, passes) em vez de despachar a bola.", p=poss)))
    elif poss is not None and poss >= 56:
        tips.append(_tip("good", tr("Dominas a posse"), tr("A tua equipa tem a bola {p:.0f}% do tempo.", p=poss)))

    inf, tak = avg.get("demo_inflicted"), avg.get("demo_taken")
    if inf is not None and tak is not None and tak - inf >= 1:
        tips.append(_tip("info", tr("Levas mais demos do que fazes"),
                         tr("{t:.1f} demos sofridas contra {i:.1f} feitas por jogo. "
                            "Fica atento aos adversários em supersónico.", t=tak, i=inf)))

    # vitorias vs derrotas
    wins = [r for r in rows if r.get("won") == 1]
    losses = [r for r in rows if r.get("won") == 0]
    if len(wins) >= 3 and len(losses) >= 3:
        wa, la = replay_averages(wins), replay_averages(losses)
        for key, label, worse_when_higher, gap in (
                ("percent_zero_boost", "tempo sem boost", True, 4),
                ("percent_behind_ball", "tempo atrás da bola", False, 5),
                ("possession_pct", "posse de bola", False, 5)):
            if key in wa and key in la:
                d = la[key] - wa[key]
                bad = d >= gap if worse_when_higher else -d >= gap
                if bad:
                    tips.append(_tip("warn", tr("Diferença nas derrotas: {x}", x=tr(label)),
                                     tr("Nas derrotas o teu {x} é {a:.0f}% contra "
                                        "{b:.0f}% nas vitórias.", x=tr(label), a=la[key], b=wa[key])))
                    break

    if not tips:
        tips.append(_tip("good", tr("Replays sem alertas"),
                         tr("Nos {n} replays analisados nada se destaca pela negativa.", n=n)))
    order = {"warn": 0, "good": 1, "info": 2}
    tips.sort(key=lambda t: order[t["level"]])
    return tips
