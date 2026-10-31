# Running Metrics Analyzer — Contexto & Status do Projeto

> **Instrução para o Agente / Desenvolvedor**: Sempre consulte este `README.md` antes de iniciar novas ações para entender o que já foi construído e atualize-o ao concluir qualquer alteração no projeto.

---

## 1. Sobre o Projeto
Sistema local de análise de métricas de corridas gravadas no **Amazfit Active 2** (arquivos `.FIT` exportados do app Zepp). O objetivo é transformar dados brutos fisiológicos e biomecânicos (*Running Dynamics*) em um documento JSON rico (`workout_json`), armazená-lo em um banco SQLite local e permitir que o **Google Gemini** atue como um treinador-professor didático, analisando o treino do dia e consultando os JSONs anteriores para avaliar a evolução.

### Documentação de Referência
- [`PLAN.md`](file:///home/jvnasc/USP/projetos/metrics-analyzer/PLAN.md): Plano geral, regras de negócio (filtro de semáforos $\le 60\text{s}$ vs. descansos $> 60\text{s}$, rotina Seg/Qua/Sex) e arquitetura.
- [`DESIGN.md`](file:///home/jvnasc/USP/projetos/metrics-analyzer/DESIGN.md): Sistema de design e tokens visuais (paleta atlética escura `#0B0C10` com acento `#FF5500`, tipografia `Plus Jakarta Sans` + `JetBrains Mono`, geometria esportiva e especificações da interface).
- [`docs/JSON_SCHEMA.md`](file:///home/jvnasc/USP/projetos/metrics-analyzer/docs/JSON_SCHEMA.md): Especificação técnica do documento JSON (`workout_json`) gerado pelo motor Python e salvo no banco.
- [`fit-archive-example/`](file:///home/jvnasc/USP/projetos/metrics-analyzer/fit-archive-example): 3 arquivos `.FIT` reais do usuário (`5km.fit`, `10km.fit`, `Intervalado.fit`) usados para validação.

---

## 2. Roadmap e Progresso de Desenvolvimento

- [x] **Fase 0 — Planejamento e Descoberta dos Dados `.FIT`** *(Concluído)*
  - Inspeção binária dos 3 arquivos `.FIT` do Amazfit Active 2.
  - Descoberta das métricas de *Running Dynamics* no pulso (potência, oscilação vertical, razão vertical, tempo de contato com o solo, comprimento de passada).
  - Definição da regra de filtragem de pausas: $\le 60\text{s}$ = Semáforo/Trânsito; $> 60\text{s}$ = Descanso/Intervalo de Tiro.
  - Definição do schema JSON ([`docs/JSON_SCHEMA.md`](file:///home/jvnasc/USP/projetos/metrics-analyzer/docs/JSON_SCHEMA.md)).
- [x] **Passo 1 — Motor de Extração `.FIT` → `JSON` (`src/parser.py` + `src/analyzer.py`)** *(Concluído)*
  - [`src/parser.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/parser.py): Classe `FitParser` com leitor binário nativo do protocolo `.FIT`, tratamento de sentinelas inválidas (`0xFFFFFFFF`, `0xFFFF`, `0xFF`), interpolação de distância e normalização de escalas para unidades humanas.
  - [`src/analyzer.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/analyzer.py): Classe `WorkoutAnalyzer` e função `process_fit_to_workout_json()` implementando filtro de semáforos ($\le 60\text{s}$) vs. descansos ($> 60\text{s}$), cálculo de `hr_recovery_drop`, segmentação automática de tiros/blocos ativos (`active_blocks_or_intervals`), cálculo de Deriva Cardíaca (`cardiac_drift_pct`) e detecção automática do tipo de treino.
  - [`tests/test_step1.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/tests/test_step1.py): Testes automatizados validando os 3 arquivos reais.
- [x] **Passo 2 — Banco de Dados Local SQLite (`src/database.py`)** *(Concluído)*
  - [`src/database.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/database.py): Classe `MetricsDatabase` gerenciando o banco SQLite local (`data/runs.db`):
    - Tabela `runner_profile`: armazena idade, peso, FC máxima (atualizada automaticamente caso um treino supere a máxima anterior), FC de repouso, meses de experiência, rotina semanal Seg/Qua/Sex e objetivos.
    - Tabela `workouts`: armazena metadados indexados, o documento `workout_json` completo, a série temporal segundo a segundo (`timeseries_json` para os gráficos do Dashboard) e o relatório cacheado da IA (`ai_report_md`).
    - Deduplicação inteligente por `start_time_iso`.
    - **Tools para Function Calling do Google Gemini** (`get_gemini_tools`): `consultar_ultimos_treinos`, `consultar_treinos_mesmo_tipo` e `consultar_evolucao_e_recordes`.
  - [`tests/test_step2.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/tests/test_step2.py): Testes unitários validando CRUD de perfil, importação `.FIT`, deduplicação e tools da IA.
- [x] **Passo 3 — Treinador IA com Google Gemini (`src/ai_coach.py`)** *(Concluído)*
  - [`.env`](file:///home/jvnasc/USP/projetos/metrics-analyzer/.env) e [`.env.example`](file:///home/jvnasc/USP/projetos/metrics-analyzer/.env.example): Configurados com **`gemini-3.8-flash`** como modelo principal (`GEMINI_MODEL`) e **`gemini-3.6-flash`** como fallback automático (`GEMINI_FALLBACK_MODEL`), utilizando **Streaming SSE (`streamGenerateContent?alt=sse`)** + troca imediata para o fallback quando a cota diária do principal esgota.
  - [`src/ai_coach.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/ai_coach.py):
    - Função `build_coach_system_prompt()`: monta o *System Prompt* didático personalizado.
    - Classe `GeminiCoach`: executa a análise completa do treino (`analyze_workout`) e o chat interativo (`chat_about_workouts`) com resolução automática de múltiplos turnos de **Function Calling (Tools)** direto no banco SQLite e cache no banco (`ai_report_md`).
  - [`test_ai.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/test_ai.py): Script CLI de teste rápido para rodar análises reais ou fazer perguntas no terminal.
  - [`tests/test_step3.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/tests/test_step3.py): Testes unitários validando o *System Prompt*, o loop de chamada de ferramentas da IA no banco SQLite e o cache de relatórios.
- [x] **Passo 4 — Dashboard Web Local (`app.py` + `web/`)** *(Concluído)*
  - [`app.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/app.py): Servidor web local nativo em Python (`ThreadingHTTPServer`, sem exigir instalação de pacotes externos via `pip`) rodando na porta `8501` e expondo API REST completa (`/api/workouts`, `/api/workout`, `/api/preview_fit`, `/api/upload_fit`, `/api/update_workout_context`, `/api/analyze_ai`, `/api/chat_ai`, `/api/evolution`, `/api/profile`).
  - [`web/index.html`](file:///home/jvnasc/USP/projetos/metrics-analyzer/web/index.html) e [`web/dashboard.js`](file:///home/jvnasc/USP/projetos/metrics-analyzer/web/dashboard.js): Interface web escura moderna com:
    - **Subpasso 4.1**: Barra lateral com histórico de treinos do SQLite, upload de `.FIT` com detecção automática de tipo de treino + RPE + notas, 6 cartões didáticos das métricas (Pace, FC, Deriva Cardíaca, Cadência/Passada, Razão/Oscilação Vertical e Potência/Tempo de Solo) e tabelas de Tiros/Blocos ($> 60\text{s}$) e Filtro de Semáforos ($\le 60\text{s}$).
    - **Subpasso 4.2**: Gráficos interativos com `Plotly.js` (Série temporal sincronizada Pace × FC × Cadência × Altitude, Parciais por Km, Zonas de FC e Evolução do Fator de Eficiência Aeróbica).
    - **Subpasso 4.3**: Painel do Relatório do Treinador IA renderizado em Markdown (mostrando quais Tools do SQLite foram consultadas) e Chat interativo ao vivo.
  - [`tests/test_step4.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/tests/test_step4.py): Testes automatizados validando o servidor HTTP e todas as rotas da API (`11/11` testes passando).

---

## 3. Como Executar o Projeto

### Opção 1: Abrir o Dashboard Web no Navegador (Recomendado)
Basta rodar no terminal:
```bash
python3 app.py
```
E abrir no seu navegador: **`http://localhost:8501`**

### Opção 2: Usar pelo Terminal (CLI)
```bash
# Analisar um arquivo .FIT direto no terminal
python3 test_ai.py fit-archive-example/Intervalado.fit

# Fazer uma pergunta direta ao Treinador IA consultando seu SQLite
python3 test_ai.py --ask "Compare meus 3 treinos salvos no banco"
```

### Opção 3: Rodar os Testes Automatizados
```bash
python3 -m unittest discover -s tests -v
```

---

## 4. Estrutura Atual de Arquivos Construídos

```text
metrics-analyzer/
├── .env                       # Arquivo onde o usuário coloca sua GEMINI_API_KEY
├── .env.example               # Modelo de variáveis de ambiente
├── .gitignore                 # Ignora .env, __pycache__, etc.
├── GEMINI.md                  # Regras de workspace para conexões de rede e streaming com Gemini
├── requirements.txt           # Dependências do projeto
├── app.py                     # Servidor do Dashboard Web Local (http://localhost:8501)
├── test_ai.py                 # Script CLI para testar a IA direto no terminal
├── README.md                  # Contexto vivo e status do projeto (sempre consultar/atualizar)
├── PLAN.md                    # Plano arquitetural e regras de negócio
├── DESIGN.md                  # Especificação visual, paleta e tokens do novo frontend esportivo
├── docs/
│   └── JSON_SCHEMA.md         # Especificação do workout_json
├── fit-archive-example/       # Arquivos .FIT de exemplo (5km.fit, 10km.fit, Intervalado.fit)
├── data/
│   ├── runs.db                # Banco SQLite populado com os 3 treinos reais e perfil
│   └── examples_json/         # JSONs reais gerados no Passo 1 (5km.json, 10km.json, Intervalado.json)
├── src/
│   ├── __init__.py
│   ├── parser.py              # Decodificador binário .FIT nativo para Amazfit Active 2
│   ├── analyzer.py            # Motor fisiológico/biomecânico e construtor do workout_json
│   ├── database.py            # Persistência SQLite + Function Calling Tools para a IA
│   └── ai_coach.py            # Cliente Google Gemini + System Prompt + Loop de Tools
├── web/
│   ├── index.html             # Interface visual do Dashboard Web
│   └── dashboard.js           # Lógica de gráficos Plotly, upload .FIT e chat IA
└── tests/
    ├── test_step1.py          # Testes unitários do Passo 1
    ├── test_step2.py          # Testes unitários do Passo 2
    ├── test_step3.py          # Testes unitários do Passo 3
    └── test_step4.py          # Testes unitários do Passo 4 (Web Server & API)
```

---

## 5. Histórico de Alterações (Changelog Interno)

- **2026-10-28 / 2026-10-29**:
  - Criação do [`PLAN.md`](file:///home/jvnasc/USP/projetos/metrics-analyzer/PLAN.md), [`docs/JSON_SCHEMA.md`](file:///home/jvnasc/USP/projetos/metrics-analyzer/docs/JSON_SCHEMA.md) e [`README.md`](file:///home/jvnasc/USP/projetos/metrics-analyzer/README.md).
  - **Conclusão do Passo 1**: Implementação de [`src/parser.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/parser.py), [`src/analyzer.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/analyzer.py) e [`tests/test_step1.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/tests/test_step1.py).
  - **Conclusão do Passo 2**: Implementação de [`src/database.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/database.py) e [`tests/test_step2.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/tests/test_step2.py); criação do banco `data/runs.db` já populado com os 3 treinos reais de exemplo.
  - **Conclusão do Passo 3**: Suporte a [`.env`](file:///home/jvnasc/USP/projetos/metrics-analyzer/.env), implementação de [`src/ai_coach.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/ai_coach.py), script de teste CLI [`test_ai.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/test_ai.py) e suíte de testes [`tests/test_step3.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/tests/test_step3.py).
  - **Conclusão do Passo 4**: Implementação do Dashboard Web completo em [`app.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/app.py), [`web/index.html`](file:///home/jvnasc/USP/projetos/metrics-analyzer/web/index.html), [`web/dashboard.js`](file:///home/jvnasc/USP/projetos/metrics-analyzer/web/dashboard.js) e testes em [`tests/test_step4.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/tests/test_step4.py).
  - **Suporte Cronológico a Treinos Antigos e Upload em Lote**:
    - [`src/database.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/database.py) e [`src/ai_coach.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/ai_coach.py): Separação explícita entre treinos realizados **antes** da data do treino analisado (`antes_de_iso`) e treinos realizados **depois** (`buscar_treinos_posteriores`), informando à IA a data de hoje vs. a data do treino para análises retroativas perfeitas.
    - [`web/index.html`](file:///home/jvnasc/USP/projetos/metrics-analyzer/web/index.html) e [`web/dashboard.js`](file:///home/jvnasc/USP/projetos/metrics-analyzer/web/dashboard.js): Suporte a seleção de múltiplos arquivos `.FIT` simultâneos (`multiple`) na tela de Upload.
  - **Streaming End-to-End em Tempo Real e Telemetria (`console.log` / Terminal / Badge)**:
    - [`src/ai_coach.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/ai_coach.py), [`app.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/app.py) (`/api/analyze_ai_stream`) e [`web/dashboard.js`](file:///home/jvnasc/USP/projetos/metrics-analyzer/web/dashboard.js): Implementação da **Solução 1 (Streaming End-to-End)** — os pedaços de texto (`chunks`) do Gemini são enviados em tempo real para o navegador à medida que são gerados (~6–8s para o primeiro token aparecer na tela, com zero perda de qualidade).
    - Adição de logs detalhados no terminal Python (`[GeminiCoach HH:MM:SS]`), no Console do Navegador (`F12` -> `console.log` estilizado + `console.table` com `modelo_que_respondeu`, `usou_fallback`, `tempo_primeiro_token_s`, `tempo_total_segundos` e `historico_tentativas`) e badge no topo do relatório mostrando exatamente qual modelo respondeu (`gemini-3.8-flash`, `gemini-3.6-flash` ou `Cache SQLite`).
  - **Fast-Path IPv4 & Diagnóstico Cirúrgico de Conexão**:
    - [`src/ai_coach.py`](file:///home/jvnasc/USP/projetos/metrics-analyzer/src/ai_coach.py): Forçamento de preferência estrita por `IPv4` no `urllib3` (`allowed_gai_family = socket.AF_INET`) e reuso de conexão com `requests.Session()`, eliminando timeouts silenciosos de `15s/30s/60s` em rotas IPv6 inativas.
    - Ativação de `"includeThoughts": True` no Gemini 3.x para destravamento imediato do `HTTP 200 OK` do Google e telemetria precisa que separa o tempo de *Thinking* interno do tempo de escrita do relatório.
    - Exibição de diagnóstico de rede (DNS ms, Socket TCP ms, tamanho do payload em KB) e tabela de tempos no console do navegador (`F12`).
- **2026-10-30**:
  - **Redesign Frontend de Alta Performance Esportiva (`web/index.html` + `web/dashboard.js`)**:
    - Aplicação integral do skill `impeccable` e das referências em `site-references/` (estilo Garmin Pro / Strava Premium / Apple Fitness).
    - **Cores & Superfícies**: Base profunda e tática (`#0B0C10`, `#101217`, `#14161E`) com acento esportivo vibrante em Laranja Atlético (`#FF5500`), bordas hairline (`#232530`), badges sutis com transparência e eliminação completa de gradientes genéricos.
    - **Geometria & Raios**: Adequação à estética esportiva com raios contidos e firmes (`8px` para cards, `6px` para botões/inputs, `4px` para badges), banindo cantos exageradamente arredondados ou "bubbly pills".
    - **Tipografia**: Banimento estrito da fonte Inter; introdução de `Plus Jakarta Sans` para textos, cabeçalhos e navegação, combinada com `JetBrains Mono` com `font-variant-numeric: tabular-nums` para todas as telemetrias, paces, frequências cardíacas e parciais.
    - **Ícones**: Eliminação completa de emojis informais no layout; implementação de conjunto proprietário de ícones SVG nítidos com traço técnico de 1.8px (tênis de corrida, pulso cardíaco, potência elétrica, bússola, cronômetro, chip de IA, etc.).
    - **AI Coach Studio**: Redesenho do contêiner do Treinador IA em formato de estúdio profissional com cabeçalho dedicado, badge de telemetria em tempo real, formatação de Markdown fluida e área de chat integrada e estilizada.
    - **Gráficos Plotly Esportivos**: Customização total dos gráficos com fundo transparente, linhas de grade discretas (`#1C1E28`), linha de pace e barras de parciais em `#FF5500`, FC em crimson `#F43F5E`, cadência em índigo `#818CF8` e curva de altitude suave.
    - Documentação completa das decisões e tokens criada em [`DESIGN.md`](file:///home/jvnasc/USP/projetos/metrics-analyzer/DESIGN.md). Suíte de testes 100% validada (`13/13` testes passando).
  - **Evolução para Cockpit de Alta Densidade Esportiva (Inspirado em `Inspo1.webp` e `a0df983e...`)**:
    - **Zero alteração no backend ou retorno da IA**: O prompt do sistema e os retornos do Gemini foram 100% preservados, focando a evolução exclusivamente na camada de apresentação visual.
    - **Micro-Sparklines SVG nos Stat Cards**: Geração nativa de curvas SVG nos 6 cartões de métricas (pace, frequência cardíaca, deriva, cadência, oscilação e potência) a partir da série temporal real do treino, eliminando ruído textual estático e trazendo a densidade visual das referências.
    - **AI Coach Cockpit Interativo**:
      - Barra de chips rápidos (*"⚡ Cadência & Passada"*, *"❤️ Deriva & Fadiga"*, *"⏱️ Tiros"*, *"👟 Próximo Treino"*) que dispara perguntas ágeis no chat com 1 clique.
      - Leitor dinâmico do relatório com controle sanfonado ("Ver Relatório Completo" / "Recolher"), mantendo a visualização dos gráficos e tabelas fluida.
    - **Matriz Segmentada de Equalizador (Tiros & Intervalos)**: Visualizador em barras segmentadas verticais para os tiros (estilo matriz de vendas de `Inspo1.webp`), com alturas pelo ritmo e iluminação colorida pelas zonas cardíacas.
    - **Medidor de Queda Cardíaca (Recovery Drop)**: Destaque visual na tabela de pausas exibindo a velocidade de recuperação cardiovascular pós-esforço em verde esportivo.
    - **Refinamento Tátil de Superfícies & Acessibilidade**: Inset border lighting (`inset 0 1px 0 rgba(255,255,255,0.07)`), brilho radial âmbar suave, elevação do contraste de `--text-dim` para cumprir WCAG 2.1 AA ($\ge 4.5:1$) e botões calibrados em 42px.
