# Rocket League Live Dashboard / Session Tracker

Liga-se a **Stats API** local do Rocket League
(https://www.rocketleague.com/developer/stats-api) e mostra/regista em
tempo real as estatisticas da sessao/partida atual: golos, assistencias,
defesas, remates, demos, boost, velocidade, eventos (golos, demolicoes,
fim de partida), e totais da sessao (vitorias, derrotas, sequencia).

Ha duas formas de usar, no mesmo projeto:

1. **`app.py`** — dashboard com janela grafica propria, em **Tkinter**
   (biblioteca padrao do Python, sem motor de browser nenhum). Pode ser
   empacotado num `.exe` standalone com `build.bat`.
2. **`rl_session_tracker.py`** — versao simples em linha de comando
   (texto no terminal), util para debugging ou para gravar CSV/JSONL.

A logica de ligacao/estado (sem GUI) vive em `tracker_core.py`, partilhada
e testada de forma isolada.

## Sobre a versao anterior (pywebview) e o "Not Responding"

A primeira versao desta app usava `pywebview` (renderiza HTML/CSS via o
motor Edge WebView2 do Windows). Esse motor pode bloquear na
inicializacao quando empacotado com PyInstaller — e' um problema
conhecido da combinacao pywebview + WebView2 + PyInstaller, nao do teu
PC. A app foi reescrita em **Tkinter puro**, que vem incluido no proprio
Python e nao depende de nenhum motor de browser externo, eliminando essa
causa de bloqueio.

## Nota tecnica: nao e' bem um "WebSocket"

A documentacao oficial chama a isto "web socket", mas na pratica e' um
**socket TCP simples** que envia objetos JSON concatenados, sem o
handshake HTTP/Upgrade que um WebSocket real exige. Se ligares com uma
biblioteca de WebSocket (como a `websockets` que usei na primeira
versao), o handshake nunca completa e a app fica para sempre a tentar
ligar — exatamente o sintoma de "nao esta a detetar que o jogo esta
aberto". Por isso `app.py`, `tracker_core.py` e `rl_session_tracker.py`
ligam com `asyncio.open_connection` (TCP cru) e separam as mensagens
concatenadas com um "frame buffer" que conta a profundidade de chavetas
`{ }`. Isto ja nao precisa de nenhuma biblioteca externa (so a biblioteca
padrao do Python).

## Limitacoes importantes da API oficial

A Stats API so' transmite dados enquanto o proprio jogo tem uma partida
a decorrer na tua maquina:

- So funciona com o Rocket League aberto e uma partida em curso (online,
  LAN, treino ou contra bots).
- So mostra dados dos jogadores presentes nessa partida — nao existe
  forma oficial de consultar as stats de carreira de qualquer jogador da
  internet por nome.
- **Nao transmite MMR/rank, nem o teu nem o dos outros jogadores.** Isto
  e' uma limitacao da API oficial da Psyonix, nao desta app. Alternativas
  reais:
  - **O teu proprio MMR:** so e' possivel com
    [BakkesMod](https://bakkesmod.com) (ferramenta de terceiros que le a
    memoria do jogo), usando um plugin gratuito ja existente como
    *"RocketStats"* ou *"Session MMR and streak tracker"*
    (bakkesplugins.com). Isto e' uma ferramenta separada, nao Python.
  - **MMR de outros jogadores:** nao existe forma fiavel. Mesmo o
    BakkesMod so consegue o MMR do jogador local (e colegas de equipa na
    mesma party), nunca de adversarios — a propria Psyonix nao expoe
    isso a clientes. A API publica da Tracker Network (tracker.gg) esta
    bloqueada por Cloudflare desde abril de 2023; o que resta sao
    revendedores de terceiros pagos e pouco fiaveis.
  - Por isso, esta app foca-se em **vitorias, derrotas e sequencia
    (streak)**, que sao calculaveis com seguranca a partir dos proprios
    eventos da partida (`MatchEnded` + saber em que equipa estavas).

## Como o resultado (vitoria/derrota) e' detetado

Confiar so' no evento `MatchEnded` nao chega sempre — por exemplo, se a
ligacao TCP fechar muito rapido a seguir ao fim da partida, essa mensagem
pode nunca chegar a ser processada. Por isso a app tenta tres niveis,
por ordem, sempre que sais de uma partida:

1. **`MatchEnded` oficial** — o proprio jogo anuncia o vencedor
   (`WinnerTeamNum`). E' o caso normal, sempre fiavel.
2. **Rede de seguranca via `bHasWinner`/`Winner`** — se o `MatchEnded`
   nao for recebido a tempo, a app usa o ultimo `UpdateState` conhecido
   (que tambem inclui se ja' havia um vencedor decidido) no momento em
   que saires da partida (`MatchDestroyed`). Tao fiavel quanto o
   `MatchEnded`, so' chega mais tarde.
3. **Estimativa pelo placar (ultimo recurso)** — se saires ANTES de
   qualquer vencedor ser oficialmente decidido (ex.: abandono/FF a meio
   do jogo), a app nao tem como saber o resultado real. Nesse caso usa o
   ultimo placar conhecido como estimativa (quem estava a ganhar quando
   saiste). Isto e' marcado claramente no feed de eventos como
   "ESTIMATIVA pelo placar", porque **pode estar errado**: sair a ganhar
   nao significa necessariamente vitoria oficial (a Psyonix pode registar
   isso como derrota do lado dela, algo que esta API local nao mostra).

Se nem isso for possivel (ex.: saiste antes de haver qualquer placar, ou
as equipas estavam empatadas), a partida simplesmente nao e' contada na
sessao, e o feed de eventos explica o motivo.

Adicionalmente, a Stats API **nao diz qual e' o playlist/modo de jogo**
(ranked, casual, treino, exibicao). Por isso a app usa dois sinais para
nao contar sessoes sem significado:

- **Sem adversario real (Free Play, treino personalizado):** se so'
  houver jogadores numa unica equipa (ninguem na equipa adversaria), a
  partida NUNCA conta -- isto nao e' configuravel, porque o jogo por
  vezes ainda emite `MatchEnded` com um "vencedor" mesmo em Free Play
  (declarando-te vencedor por nao haver ninguem para perder), e isso
  nao tem significado nenhum.
- **Partidas com bots:** bots reportam sempre `PrimaryId` "Unknown|0|0".
  Com a caixa "Nao contar partidas com bots (treino)" ligada (por
  defeito), partidas de exibicao contra IA tambem ficam de fora da
  sessao -- esta sim e' configuravel, ve a secao seguinte.

## 1. Ativar a Stats API no jogo

Antes de abrir o Rocket League, edita o ficheiro:

```
<Pasta de instalacao do RL>\TAGame\Config\DefaultStatsAPI.ini
```

Localizacoes tipicas:

- Steam: `C:\Program Files (x86)\Steam\steamapps\common\rocketleague\TAGame\Config\DefaultStatsAPI.ini`
- Epic Games: `C:\Program Files\Epic Games\rocketleague\TAGame\Config\DefaultStatsAPI.ini`

Adiciona/edita estas linhas (cria a seccao se nao existir):

```ini
[TAGame.MatchStatsExporter_TA]
PacketSendRate=10
Port=49123
```

**Atencao ao nome da seccao** — tem de ser exatamente
`[TAGame.MatchStatsExporter_TA]`. Se a seccao estiver errada ou nao
existir, o jogo nunca ativa o socket, `PacketSendRate` e `Port` sao
ignorados, e a app fica sempre a tentar ligar sem sucesso (este foi o
motivo mais provavel de a app "nao detetar que o jogo esta aberto").

- `PacketSendRate` tem de ser maior que 0 para ativar o socket (10 a 30
  e' um bom valor; maximo 120).
- `Port` e' a porta local onde o socket fica disponivel (por defeito
  49123).

**Depois de um update do jogo:** o Steam/Epic repoe este ficheiro e a
configuracao perde-se. A app verifica o `DefaultStatsAPI.ini` ao abrir e
de 30 em 30 segundos (fora de partidas) e, se a secao tiver desaparecido,
repara-a sozinha e avisa na janela ("Stats API ... reparada"). Tens de
fechar e voltar a abrir o Rocket League depois disso. Se a pasta do jogo
nao for detetada (Steam/Epic em sitios pouco usuais), define no
`config.ini`:

```ini
[game]
install_dir = D:\Jogos\rocketleague
```

Se o jogo estiver em `Program Files` e a reparacao falhar por permissoes,
corre a app como administrador uma vez. Tambem podes verificar/reparar a
partir da linha de comandos: `python stats_api_config.py --fix`.

**Fecha o jogo completamente antes de editar o ficheiro, e so abre o
jogo depois de gravares as alteracoes** — a configuracao so e' lida no
arranque do cliente. Depois de abrir o jogo, entra numa partida real
(treino, contra bots, ou online) — o socket so fica ativo durante uma
partida, nao no menu principal.

## 2. Opcao A — App com dashboard (janela grafica)

### Correr em modo desenvolvimento

```bash
python app.py
```

Nao precisas de instalar nada — `app.py` so usa Tkinter (vem com o
Python no Windows) e a biblioteca padrao (`asyncio`, `socket`). O
`requirements.txt` so e' preciso para gerar o `.exe` (PyInstaller).

Na janela:

- Topo: placar, tempo de jogo, mapa e estado da ligacao.
- Campo **"O teu nome no jogo"** — escreve aqui o teu nome exatamente
  como aparece no Rocket League, para a app saber identificar-te e
  contar vitorias/derrotas corretamente.
- **Por modo** (linha por baixo das stats): resultado da sessao separado
  por modo, ex. `1v1 2-1 · 2v2 5-3 · 3v3 0-1`. O modo e' inferido pelo
  maior tamanho de equipa visto na partida (1 = 1v1, 2 = 2v2, 3 = 3v3,
  outro = "Outro"). A Stats API nao diz a playlist, por isso **nao
  distingue ranked de casual** (nem Hoops/Rumble, que aparecem como
  2v2/3v3).
- **Histórico** (separador "Histórico", dentro da janela principal): cada partida contada fica gravada em
  `history.db` (SQLite, ao lado da app/.exe) e sobrevive a fechar a app.
  O separador mostra stats por modo (jogos, V/D, win%, golos/assist./defesas/
  remates por jogo, precisao de remate, pontos), as ultimas partidas, e
  filtros por perfil/periodo/modo, com **Exportar CSV** (separador `;`,
  abre bem no Excel). `~` marca resultados estimados pelo placar.
  "Reiniciar sessao" nao apaga o historico.
- **Perfis** (uma por conta, ex. a tua conta Steam e a tua conta Epic):
  - O menu **Perfil** escolhe o perfil ativo; **+** cria um novo e
    **Apagar** remove o ativo. O campo **nome** e a **plataforma**
    (Qualquer/Steam/Epic) editam o perfil ativo.
  - Cada perfil tem a **sua propria sessao** (vitorias, derrotas, streak,
    totais). "Reiniciar sessao" so afeta o perfil ativo.
  - Com **"Trocar auto"** ligado, quando comeca uma partida a app procura
    um perfil cujo nome (igual, sem distinguir maiusculas) e plataforma
    batam com um jogador da partida (a Stats API da' a plataforma no
    `PrimaryId`, ex. `Steam|...` / `Epic|...`) e muda sozinha para ele,
    avisando no feed de eventos. So' usa correspondencia exata -- se o teu
    nome no jogo tiver sufixos, escreve-o exatamente como aparece.
  - Os perfis ficam em `profiles.json`, ao lado da app/.exe. Na primeira
    execucao o nome que tinhas em `config.ini` e' importado como perfil
    "Qualquer" -- define-lhe a plataforma (Steam ou Epic).
- Campo **"Destacar jogador"** — escreve um nome para destacar essa
  linha na tabela (sem esconder os outros).
- **Painel SESSAO ATUAL** — jogos, vitorias, derrotas, sequencia
  (streak) e totais de golos/assistencias/defesas do teu jogador, desde
  que abriste a app (ou desde o ultimo "Reiniciar sessao").
- Caixa **"Nao contar partidas com bots (treino)"** (ligada por
  defeito) — a Stats API nao diz qual e' o playlist/modo de jogo, por
  isso nao ha forma oficial de distinguir ranked/casual/treino. O sinal
  disponivel e' que bots reportam sempre `PrimaryId` "Unknown|0|0"; com
  esta caixa ligada, partidas onde aparece pelo menos um bot (treino
  contra IA, exibicao com bots a preencher vagas, etc.) ficam de fora da
  sessao. Desliga-a se quiseres mesmo contar essas partidas.
- Colunas Azul / Laranja com cartoes de cada jogador (pontos, golos,
  assistencias, defesas, remates, demos, boost, velocidade).
- Feed de eventos ao vivo (golos, demolicoes, fim de partida).

A app liga-se automaticamente e fica em espera/retry enquanto o jogo nao
abrir uma partida — nao precisas de ter o Rocket League aberto antes de
correr a app.

### Gerar o .exe

Eu desenvolvo este projeto num ambiente Linux, por isso nao consigo
compilar um `.exe` Windows diretamente — tens de gerar o `.exe` **na tua
maquina Windows** (a mesma onde corre o Rocket League):

```bash
build.bat
```

Este script cria um ambiente virtual, instala o `pyinstaller` e gera o
executavel em:

```
dist\RL-Live-Dashboard.exe
```

Esse `.exe` e' standalone — podes copia-lo para qualquer pasta e correr
sem teres Python instalado. So precisa de estar na mesma maquina onde o
Rocket League esta a correr (porque liga a um socket local).

Se o `.exe` ja existir de uma build anterior e o build.bat nao conseguir
substitui-lo, fecha primeiro a app antiga (pode estar ainda aberta ou
bloqueada por antivirus) e corre `build.bat` outra vez.

## 3. Opcao B — Script em linha de comando

```bash
python rl_session_tracker.py
```

(Tambem nao precisa de nenhuma instalacao extra.)

Opcoes uteis:

```bash
# Seguir so um jogador especifico (o teu nome, por exemplo)
python rl_session_tracker.py --player "OTeuNomeNoJogo"

# Modo "dashboard" de texto que limpa o ecra a cada atualizacao
python rl_session_tracker.py --live

# Gravar stats por tick num CSV e todos os eventos em bruto num JSONL
python rl_session_tracker.py --csv sessao.csv --log eventos.jsonl

# Mostrar tambem eventos menos relevantes (BallHit, ClockUpdatedSeconds, ...)
python rl_session_tracker.py --verbose

# Mudar porta/host (se alteraste o Port no ini)
python rl_session_tracker.py --port 49123
```

## Ficheiros

- `app.py` — app com dashboard grafico (Tkinter).
- `tracker_core.py` — logica de ligacao/estado/sessao, sem GUI (testavel
  isoladamente).
- `stats_api_config.py` — deteta o jogo e repara o `DefaultStatsAPI.ini`.
- `history.py` — historico SQLite das partidas (`history.db`, criado pela app).
- `history_page.py` — separador Histórico (stats por modo, lista, filtros, CSV).
- `ui_kit.py` — tema e componentes visuais (cartões, botões, abas, switches).
- `profiles.py` — perfis (Steam/Epic) e deteccao automatica do perfil.
- `profiles.json` — os teus perfis (criado pela app).
- `config.ini` — opcional: `[game] install_dir` (ver acima). O nome antigo `[player]` so' e' lido uma vez, para migrar.
- `build.bat` — gera o `.exe` da app no Windows via PyInstaller (e copia
  `config.ini` para `dist\`).
- `rl_session_tracker.py` — versao em linha de comando.
- `requirements.txt` — dependencia so' para o build (`pyinstaller`).
- `README.md` — este guia.

- `ballchasing.py` / `replays_page.py` — separador Replays: envia os replays para o Ballchasing e guarda as tuas stats (ballchasing.json + replays.db, ao lado do .exe).
- `coach.py` / `coach_page.py` / `ai_coach.py` — separador Treinador: dicas offline por regras e análise opcional com IA na cloud (`ai.json`).
- `settings_page.py` / `appsettings.py` — separador Definições: idioma (PT/EN), escala da interface, modo compacto ao iniciar, pastas dos replays, chave e visibilidade do Ballchasing, serviço de IA, abrir a pasta dos dados e exportar (zip sem chaves). Gravado em `settings.json`, ao lado do .exe. Idioma e escala mudam logo, sem reiniciar a app. Três secções: Geral (idioma, escala, bandeja, avisos da sessão), Replays e IA, Dados (ficheiros, exportar, cópia automática).
- `i18n.py` / `i18n_en.py` — traduções. Os textos no código estão em português e servem de chave; `i18n_en.py` tem o dicionário inglês. Para acrescentar um texto, usa `tr("texto")` e junta a tradução ao `EN`. Se faltar uma chave, aparece o português.
- `maintenance.py` — cópia de segurança diária (zip sem chaves, pasta e nº de cópias nas Definições), exportação e instância única (porta local 49199; a 2.ª instância só traz a 1.ª para a frente).
- `tray.py` — ícone na bandeja (opcional, precisa de `pystray` e `pillow`; "Fechar para a bandeja" nas Definições).
- `charts.py` / `compare.py` — gráficos do Histórico (win% móvel, por hora e por dia da semana) e a comparação "esta partida/replay vs a tua média".
- `tests/` — testes automáticos: `pip install -r requirements-dev.txt` e depois `python -m pytest`.

## Avisos da sessão
Em Definições > Geral podes pedir um aviso (banner + som) ao chegar a N derrotas seguidas ou a N vitórias na sessão. Ao abrir a app só se regista o estado atual, não se avisa.

## Análise com IA
O botão "Ver dados enviados" mostra exatamente o que sai para o serviço (destino, instruções e números; a chave nunca). A resposta marca cada ponto como (dado) ou (hipótese).

## Git
O repositório ignora os teus dados e chaves (`profiles.json`, `settings.json`, `ballchasing.json`, `ai.json`, `*.db`, `backups/`, `dist/`, `venv/`). Primeiro commit: `git add .` e `git commit -m "RL Live Dashboard"`.
