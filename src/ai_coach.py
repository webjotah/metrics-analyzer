"""Módulo do Treinador IA com Google Gemini (`src/ai_coach.py`).

Responsabilidades:
1. Carregar automaticamente a chave `GEMINI_API_KEY` e o modelo `GEMINI_MODEL` do arquivo `.env`
   na raiz do projeto (usando `python-dotenv`).
2. Construir o *System Prompt* de Treinador e Fisiologista de Corrida didático, personalizado
   para o perfil do corredor (2 meses de experiência, rotina Seg/Qua/Sex, Amazfit Active 2).
3. Executar o ciclo de análise do treino (`analyze_workout`) e chat interativo (`chat_about_workouts`)
   com suporte completo a **Function Calling (Tools)** no banco SQLite (`MetricsDatabase`):
   - `consultar_ultimos_treinos`
   - `consultar_treinos_mesmo_tipo`
   - `consultar_evolucao_e_recordes`
4. Suportar tanto o SDK `google-genai` (se instalado) quanto chamada direta via REST API oficial
   do Google Gemini (`generativelanguage.googleapis.com` via `requests`), funcionando imediatamente
   sem depender de compilação de pacotes extras.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import requests
import urllib3.util.connection as urllib3_conn
from dotenv import load_dotenv

from src.database import MetricsDatabase

# Força preferência estrita por IPv4 no urllib3/requests para evitar timeouts silenciosos
# de 15s/30s/60s em redes/ISPs onde rotas IPv6 locais não possuem conectividade externa ativa
def _force_ipv4_socket():
    return socket.AF_INET

urllib3_conn.allowed_gai_family = _force_ipv4_socket


def diagnose_network_to_google(host: str = "generativelanguage.googleapis.com", port: int = 443) -> Dict[str, Any]:
    """Testa a conectividade DNS e abertura de socket TCP para o endpoint da Google AI Studio."""
    t0 = time.monotonic()
    try:
        addrinfo = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        dns_ms = round((time.monotonic() - t0) * 1000, 1)
        ipv4s = [ai[4][0] for ai in addrinfo if ai[0] == socket.AF_INET]
        ipv6s = [ai[4][0] for ai in addrinfo if ai[0] == socket.AF_INET6]
        primary_ip = ipv4s[0] if ipv4s else (ipv6s[0] if ipv6s else host)

        t_tcp0 = time.monotonic()
        with socket.create_connection((primary_ip, port), timeout=2.0):
            tcp_ms = round((time.monotonic() - t_tcp0) * 1000, 1)

        return {
            "ok": True,
            "dns_ms": dns_ms,
            "tcp_connect_ms": tcp_ms,
            "ipv4_count": len(ipv4s),
            "ipv6_count": len(ipv6s),
            "primary_ip": primary_ip,
        }
    except Exception as exc:
        return {
            "ok": False,
            "dns_ms": round((time.monotonic() - t0) * 1000, 1),
            "tcp_connect_ms": None,
            "error": str(exc),
        }

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_FALLBACK_MODEL = "gemini-3.6-flash"


def load_gemini_config(
    override_api_key: Optional[str] = None,
    override_model: Optional[str] = None,
) -> Dict[str, str]:
    """Recarrega o arquivo `.env` e retorna `api_key`, `model` e `fallback_model` configurados."""
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    api_key = (override_api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    model = (override_model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
    fallback_model = (os.getenv("GEMINI_FALLBACK_MODEL") or DEFAULT_FALLBACK_MODEL).strip()
    return {"api_key": api_key, "model": model, "fallback_model": fallback_model}


def build_coach_system_prompt(runner_profile: Dict[str, Any]) -> str:
    """Constrói o System Prompt detalhado do Treinador-Professor de Corrida."""
    name = runner_profile.get("name", "Corredor")
    age = runner_profile.get("age", 25)
    weight = runner_profile.get("weight_kg", 75.0)
    max_hr = runner_profile.get("max_hr_bpm", 195)
    rest_hr = runner_profile.get("resting_hr_bpm", 60)
    exp_months = runner_profile.get("running_experience_months", 2)
    routine = runner_profile.get("weekly_routine_description", "")
    goals = runner_profile.get("current_goals", "")

    return f"""Você é um Treinador de Corrida e Fisiologista do Exercício extremamente didático, motivador e técnico na medida certa, especializado em ajudar corredores iniciantes/intermediários a entenderem cada métrica do relógio **Amazfit Active 2**.

### PERFIL DO CORREDOR
- **Nome**: {name} ({age} anos, {weight} kg)
- **Experiência na corrida**: {exp_months} meses
- **Frequência Cardíaca**: Máxima conhecida de **{max_hr} bpm** | Repouso de **{rest_hr} bpm**
- **Rotina Semanal Planejada**: {routine}
- **Objetivos Atuais**: {goals}

### REGRAS DE OURO DA SUA ANÁLISE
1. **Consciência Cronológica Real (Treino de Hoje vs. Treino Antigo Revisado)**:
   - Sempre verifique o campo `metadata.date` do treino em foco e compare com a data atual informada no prompt e com as datas dos outros treinos no banco.
   - Se o corredor estiver analisando um **treino antigo do histórico** (ex: existe treino mais recente no banco depois dele), deixe claro que você sabe que aquele treino ocorreu no passado, avalie como ele estava naquele momento comparado aos treinos **anteriores** àquela data (`treinos_anteriores_a_este`), e se houver `treinos_posteriores_a_este` comente como ele evoluiu desde então!
2. **Avalie o Treino pelo OBJETIVO do Dia**:
   - Se o treino for **Intervalado / Tiros** ou **Fartlek** (quarta-feira forte), FC alta (Zona 4 e Zona 5, 180–195 bpm) e Training Effect Anaeróbico alto (> 2.5) são **excelentes e esperados**. Analise a consistência entre os tiros (`active_blocks_or_intervals`) e a recuperação cardíaca nas pausas (`hr_recovery_drop`).
   - Se o treino for **Rodagem Leve (5 km)** ou **Treino Longo (10–15 km)**, o foco deveria ser base aeróbica (Zonas 2 e 3, conversa confortável). Se a FC ficou muito alta o tempo todo ou houve muitas paradas de descanso (> 60s), explique de forma construtiva como diminuir o ritmo no início ajuda a correr contínuo sem precisar parar.
3. **Diferencie Semáforos de Descansos Reais**:
   - O sistema já separou em `pauses_analysis`:
     - `traffic_lights_under_60s`: paradas rápidas (<= 60s) em semáforos/trânsito. **Nunca critique nem trate paradas <= 60s como falta de fôlego!**
     - `rest_stops_over_60s`: paradas > 60s (descanso real, hidratação ou intervalo entre tiros). Olhe o campo `hr_recovery_drop` (quantos bpm o coração caiu durante a parada — quedas > 30-50 bpm em 2-3 min mostram ótima recuperação parassimpática!).
4. **Traduza e Ensine TODAS as Métricas do Amazfit Active 2 usando os números do treino**:
   - O corredor disse que antes só entendia *Pace*, *Tempo* e *BPM*. Seu papel é explicar de forma simples e prática o que aconteceu no treino dele com:
     - **Cadência (spm) + Comprimento de Passada (m)**: explique a relação entre frequência de passos e amplitude (e como ele ajusta isso quando cansa ou acelera).
     - **Oscilação Vertical (cm) + Razão Vertical (%)**: explique que mostra quanto da energia foi para frente vs. pulando para cima (ex: Razão Vertical < 7% é excelente eficiência; > 8-9% é mais salto vertical).
     - **Tempo de Contato com o Solo (ms)**: quanto tempo o pé fica no chão a cada passo (< 270ms é bem reativo; ~290-300ms é típico de trote mais lento).
     - **Potência (Watts) + Altimetria (`elev_gain_m` / `elev_loss_m`)**: se o pace caiu num km específico, olhe se tinha subida (`elev_gain_m`) e se a potência em Watts se manteve alta!
     - **Training Effect (Aeróbico vs. Anaeróbico)** e **Deriva Cardíaca (`cardiac_drift_pct`)**: explique o que o número daquele treino revela sobre a resistência dele.

### FORMATO ESPERADO DO RELATÓRIO DE TREINO (EM MARKDOWN)
Organize o relatório com títulos claros e leitura agradável:
1. **🎯 Veredito Geral do Treino**: Resumo direto sobre como foi o treino dentro da proposta do dia (Seg/Qua/Sex) e considerando o que ele anotou em `user_context` (RPE e observações).
2. **🔍 Traduzindo Suas Métricas de Hoje (O que cada uma significa)**:
   - Explicação didática com os números exatos do treino para: *Coração & Deriva Cardíaca*, *Biomecânica (Cadência, Passada, Oscilação/Razão Vertical e Tempo de Solo)*, *Potência & Relevo*, e *Análise dos Blocos/Tiros ou Parciais por Km*.
3. **✅ O Que Foi Muito Bom vs. ⚠️ Pontos de Atenção**: Bullet points diretos e honestos.
4. **📈 Comparação com Seus Treinos Anteriores (Histórico do Banco)**: Conclusões que você tirou ao consultar os JSONs anteriores no banco.
5. **🚀 Dica Prática para o Próximo Treino**: 1 ou 2 conselhos acionáveis para a próxima sessão da rotina dele.
"""


# Declarações JSON Schema das Tools para a API do Gemini
GEMINI_TOOLS_DECLARATIONS = [
    {
        "name": "consultar_ultimos_treinos",
        "description": (
            "Retorna os documentos JSON completos (workout_json) dos últimos treinos realizados pelo corredor "
            "no banco SQLite (excluindo o treino que está sendo analisado agora). Use para ver a carga recente "
            "da semana (Seg/Qua/Sex) e comparar métricas."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "limite": {
                    "type": "INTEGER",
                    "description": "Quantidade de treinos recentes para buscar (padrão 5, máximo 15).",
                }
            },
        },
    },
    {
        "name": "consultar_treinos_mesmo_tipo",
        "description": (
            "Retorna os documentos JSON completos (workout_json) de treinos anteriores do mesmo tipo "
            "(ex: 'Intervalado', 'Longo', 'Rodagem', 'Fartlek') para comparar evolução tiro a tiro e km a km."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "tipo_treino": {
                    "type": "STRING",
                    "description": "Tipo do treino para filtrar (ex: 'Intervalado', 'Longo', 'Rodagem', 'Fartlek').",
                },
                "limite": {
                    "type": "INTEGER",
                    "description": "Quantidade máxima de treinos daquele tipo para retornar (padrão 5).",
                },
            },
            "required": ["tipo_treino"],
        },
    },
    {
        "name": "consultar_evolucao_e_recordes",
        "description": (
            "Retorna o panorama completo de evolução do corredor: total de treinos, km acumulados, recordes "
            "e a linha do tempo cronológica com o Fator de Eficiência Aeróbica (Velocidade / FC)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        },
    },
]


class GeminiCoach:
    """Cliente do Treinador IA que conecta o banco SQLite ao Google Gemini com Function Calling."""

    def __init__(
        self,
        db: Optional[MetricsDatabase] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        fallback_model: Optional[str] = None,
    ) -> None:
        self.db = db if db is not None else MetricsDatabase()
        cfg = load_gemini_config(override_api_key=api_key, override_model=model)
        self.api_key = cfg["api_key"]
        self.model = cfg["model"]
        self.fallback_model = fallback_model or cfg["fallback_model"]
        self.last_model_used: Optional[str] = None
        self.last_tools_called: List[str] = []
        self.last_call_metadata: Dict[str, Any] = {}
        self._session = requests.Session()

    @staticmethod
    def _log(msg: str) -> None:
        """Exibe log imediato no terminal Python com timestamp para rastreio de modelo e latência."""
        ts = time.strftime("%H:%M:%S")
        sys.stderr.write(f"[GeminiCoach {ts}] {msg}\n")
        sys.stderr.flush()

    def is_configured(self) -> bool:
        """Verifica se há uma GEMINI_API_KEY válida configurada no `.env` ou instância."""
        cfg = load_gemini_config(override_api_key=self.api_key, override_model=self.model)
        self.api_key = cfg["api_key"]
        self.model = cfg["model"]
        self.fallback_model = self.fallback_model or cfg["fallback_model"]
        return bool(self.api_key and self.api_key != "SUA_CHAVE_AQUI")

    def _build_tool_map(self, current_workout_id: Optional[str] = None) -> Dict[str, Callable[..., Any]]:
        tools_list = self.db.get_gemini_tools(current_workout_id=current_workout_id)
        return {fn.__name__: fn for fn in tools_list}

    def _build_workout_analysis_prompt(self, workout_json: Dict[str, Any]) -> Tuple[str, str]:
        """Monta o `system_prompt` e o `user_prompt` completo (incluindo JSONs anteriores, posteriores e evolução)."""
        import datetime

        workout_id = workout_json.get("workout_id")
        profile = self.db.get_runner_profile()
        system_prompt = build_coach_system_prompt(profile)
        workout_date_iso = workout_json.get("metadata", {}).get("date")
        today_iso = datetime.date.today().isoformat()

        # Busca separadamente os treinos ANTERIORES à data deste treino e (se for um treino antigo) os POSTERIORES
        older_workouts = self.db.buscar_ultimos_treinos(
            limite=5,
            excluir_workout_id=workout_id,
            antes_de_iso=workout_date_iso,
        )
        newer_workouts = (
            self.db.buscar_treinos_posteriores(
                depois_de_iso=workout_date_iso,
                limite=5,
                excluir_workout_id=workout_id,
            )
            if workout_date_iso
            else []
        )
        evolution_summary = self.db.buscar_evolucao_e_recordes()
        self.last_tools_called = [
            f"treinos_anteriores({len(older_workouts)})",
            f"treinos_posteriores({len(newer_workouts)})",
            "consultar_evolucao_e_recordes()",
        ]

        is_historical = len(newer_workouts) > 0
        temporal_status = (
            f"ATENÇÃO CRONOLÓGICA: Este treino ocorreu em `{workout_date_iso}` (Data de hoje: `{today_iso}`). "
            f"Existem {len(newer_workouts)} treino(s) mais recente(s) no banco feitos DEPOIS dele — portanto, "
            "trata-se de um **treino antigo do histórico** que o corredor subiu/abriu para análise retroativa!"
            if is_historical
            else f"CONTEXTO CRONOLÓGICO: Este treino ocorreu em `{workout_date_iso}` (Data de hoje: `{today_iso}`) "
            "e é o treino mais recente registrado no banco de dados do corredor."
        )

        user_prompt = (
            f"{temporal_status}\n\n"
            "Analise de forma completa e didática o treino abaixo (documento JSON extraído do Amazfit Active 2).\n"
            "Logo abaixo do treino em foco, você tem os JSONs completos dos treinos realizados ANTES dele "
            "(para avaliar como ele estava até aquela data), os treinos realizados DEPOIS dele (se houver, para "
            "mostrar como ele evoluiu depois desse dia) e a linha do tempo cronológica completa.\n\n"
            "### 1. JSON DO TREINO EM ANÁLISE (FOCO):\n"
            f"```json\n{json.dumps(workout_json, ensure_ascii=False, separators=(',', ':'))}\n```\n\n"
            f"### 2. JSONS COMPLETOS DOS TREINOS ANTERIORES A `{workout_date_iso}` ({len(older_workouts)} treino(s)):\n"
            f"```json\n{json.dumps(older_workouts, ensure_ascii=False, separators=(',', ':'))}\n```\n\n"
            f"### 3. JSONS COMPLETOS DOS TREINOS POSTERIORES A `{workout_date_iso}` ({len(newer_workouts)} treino(s)):\n"
            f"```json\n{json.dumps(newer_workouts, ensure_ascii=False, separators=(',', ':'))}\n```\n\n"
            "### 4. PANORAMA CRONOLÓGICO DE EVOLUÇÃO E RECORDES (`consultar_evolucao_e_recordes`):\n"
            f"```json\n{json.dumps(evolution_summary, ensure_ascii=False, separators=(',', ':'))}\n```"
        )
        return system_prompt, user_prompt

    def analyze_workout(
        self,
        workout_json: Dict[str, Any],
        save_to_db: bool = True,
        force_regenerate: bool = False,
    ) -> str:
        """Analisa um `workout_json` completo usando o Gemini + consulta de JSONs antigos no banco.
        Se o treino já tiver relatório salvo no banco e `force_regenerate=False`, retorna do cache.
        """
        workout_id = workout_json.get("workout_id")
        if workout_id and not force_regenerate:
            existing = self.db.get_workout(workout_id)
            if existing and existing.get("ai_report_md"):
                self.last_model_used = "Cache SQLite"
                self.last_tools_called = ["cache_sqlite_hit()"]
                self.last_call_metadata = {
                    "model_used": "Cache SQLite",
                    "primary_model": self.model,
                    "fallback_model": self.fallback_model,
                    "used_fallback": False,
                    "from_cache": True,
                    "elapsed_sec": 0.0,
                    "ttft_sec": 0.0,
                    "attempts_log": ["Relatório recuperado instantaneamente do banco SQLite (0.0s)"],
                }
                self._log(f"⚡ Relatório retornado instantaneamente do Cache SQLite (workout_id={workout_id}).")
                return existing["ai_report_md"]

        if not self.is_configured():
            raise RuntimeError(
                "Chave GEMINI_API_KEY não configurada! "
                "Abra o arquivo `.env` na raiz do projeto e cole sua chave gratuita do Google AI Studio."
            )

        system_prompt, user_prompt = self._build_workout_analysis_prompt(workout_json)
        contents: List[Dict[str, Any]] = [
            {"role": "user", "parts": [{"text": user_prompt}]}
        ]

        # Como já entregamos todos os JSONs do banco na mesma mensagem, fazemos 1 única chamada rápida sem precisar de round-trips extras
        response_data = self._call_gemini_api(
            system_instruction=system_prompt,
            contents=contents,
            tools_declarations=None,
        )
        candidates = response_data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Resposta vazia da API do Gemini: {response_data}")
        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p and not p.get("thought")]
        if not text_parts:
            text_parts = [p.get("text", "") for p in parts if "text" in p]
        report_md = "\n".join(text_parts).strip()

        if save_to_db and workout_id and report_md:
            self.db.save_ai_report(workout_id, report_md)

        return report_md

    def analyze_workout_stream(
        self,
        workout_json: Dict[str, Any],
        save_to_db: bool = True,
        force_regenerate: bool = False,
    ) -> Iterator[Dict[str, Any]]:
        """Gera o relatório do treino transmitindo os pedaços (chunks) ao vivo para o navegador
        assim que cada frase é escrita pelo Gemini (Solução 1: Streaming End-to-End),
        além de emitir eventos detalhados de telemetria (`status`, `model_selected`, `chunk`, `done`).
        """
        t_start = time.monotonic()
        workout_id = workout_json.get("workout_id")

        if workout_id and not force_regenerate:
            existing = self.db.get_workout(workout_id)
            if existing and existing.get("ai_report_md"):
                cached_md = existing["ai_report_md"]
                self.last_model_used = "Cache SQLite"
                self.last_tools_called = ["cache_sqlite_hit()"]
                meta = {
                    "model_used": "Cache SQLite",
                    "primary_model": self.model,
                    "fallback_model": self.fallback_model,
                    "used_fallback": False,
                    "from_cache": True,
                    "elapsed_sec": 0.0,
                    "ttft_sec": 0.0,
                    "tools_called": self.last_tools_called,
                    "attempts_log": ["Relatório recuperado instantaneamente do Cache SQLite (0.0s)"],
                }
                self.last_call_metadata = meta
                self._log(f"⚡ [Stream] Relatório carregado do Cache SQLite para workout_id={workout_id}.")
                yield {
                    "type": "model_selected",
                    "model_used": "Cache SQLite",
                    "primary_model": self.model,
                    "used_fallback": False,
                    "from_cache": True,
                    "tools_called": self.last_tools_called,
                }
                yield {"type": "chunk", "text": cached_md, "ttft_sec": 0.0}
                yield {"type": "done", "ai_report_md": cached_md, **meta}
                return

        if not self.is_configured():
            raise RuntimeError(
                "Chave GEMINI_API_KEY não configurada! "
                "Abra o arquivo `.env` na raiz do projeto e cole sua chave gratuita do Google AI Studio."
            )

        system_prompt, user_prompt = self._build_workout_analysis_prompt(workout_json)
        contents: List[Dict[str, Any]] = [
            {"role": "user", "parts": [{"text": user_prompt}]}
        ]

        models_to_try = []
        for candidate in [self.model, self.fallback_model]:
            if candidate and "3.1-pro" not in candidate and candidate not in models_to_try:
                models_to_try.append(candidate)
        if not models_to_try:
            models_to_try = ["gemini-3.8-flash", "gemini-3.6-flash"]

        payload: Dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0.3,
                "thinkingConfig": {
                    "thinkingBudget": 1024,
                    "includeThoughts": True,
                },
            },
        }

        # Diagnóstico prévio de rede e medição de tamanho do payload
        payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        payload_kb = round(payload_bytes / 1024.0, 1)

        net_diag = diagnose_network_to_google()
        if net_diag.get("ok"):
            self._log(
                f"🌐 [Rede/DNS] {net_diag['dns_ms']}ms ({net_diag.get('ipv4_count', 0)}x IPv4, {net_diag.get('ipv6_count', 0)}x IPv6) | "
                f"Socket IPv4 ({net_diag.get('primary_ip')}:443): {net_diag.get('tcp_connect_ms')}ms OK | "
                f"Payload POST: {payload_kb} KB"
            )
        else:
            self._log(f"⚠️ [Rede/DNS] Teste rápido de socket falhou ({net_diag.get('error')}). Prosseguindo com requests...")

        errors_log: List[str] = []
        attempts_log: List[str] = []

        for idx, target_model in enumerate(models_to_try):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:streamGenerateContent"
            params = {"key": self.api_key, "alt": "sse"}
            is_fallback = idx > 0

            for attempt in range(3):
                attempt_label = f"{target_model} (tentativa {attempt + 1}/3)"
                status_msg = (
                    f"Conectando ao modelo {'FALLBACK ' if is_fallback else 'PRINCIPAL '}[{target_model}] "
                    f"(tentativa {attempt + 1})..."
                )
                self._log(f"🚀 {status_msg}")
                yield {
                    "type": "status",
                    "message": status_msg,
                    "model": target_model,
                    "attempt": attempt + 1,
                    "is_fallback": is_fallback,
                    "payload_kb": payload_kb,
                    "dns_tcp_ms": net_diag.get("tcp_connect_ms"),
                }

                req_t0 = time.monotonic()
                try:
                    resp = self._session.post(
                        url,
                        params=params,
                        json=payload,
                        stream=True,
                        timeout=(8.0, 95.0),
                    )
                except requests.exceptions.Timeout as exc:
                    elapsed_req = round(time.monotonic() - req_t0, 2)
                    msg = f"{attempt_label} -> Timeout após {elapsed_req}s: {exc}"
                    errors_log.append(f"[{msg}]")
                    attempts_log.append(msg)
                    self._log(f"⚠️ {msg}")
                    if attempt < 2:
                        wait_sec = 4 * (attempt + 1)
                        yield {
                            "type": "status",
                            "message": f"Timeout em {target_model}. Aguardando {wait_sec}s para nova tentativa...",
                            "model": target_model,
                            "attempt": attempt + 1,
                        }
                        time.sleep(wait_sec)
                        continue
                    resp = None
                    break
                except requests.exceptions.RequestException as exc:
                    msg = f"{attempt_label} -> Erro de rede: {exc}"
                    errors_log.append(f"[{msg}]")
                    attempts_log.append(msg)
                    self._log(f"❌ {msg}")
                    resp = None
                    break

                http_elapsed = round(time.monotonic() - req_t0, 2)

                if resp.status_code == 200:
                    self.last_model_used = target_model
                    attempts_log.append(f"{attempt_label} -> HTTP 200 OK em {http_elapsed}s")
                    self._log(
                        f"⚡ [HTTP 200 OK] Conectado a [{target_model}] ({'FALLBACK' if is_fallback else 'PRINCIPAL'}) "
                        f"em {http_elapsed}s! Aguardando tokens (includeThoughts=True)..."
                    )
                    yield {
                        "type": "model_selected",
                        "model_used": target_model,
                        "primary_model": self.model,
                        "fallback_model": self.fallback_model,
                        "used_fallback": is_fallback,
                        "from_cache": False,
                        "http_connect_sec": http_elapsed,
                        "payload_kb": payload_kb,
                        "dns_tcp_ms": net_diag.get("tcp_connect_ms"),
                        "tools_called": self.last_tools_called,
                    }

                    resp.encoding = "utf-8"
                    text_chunks: List[str] = []
                    thought_chunks_count = 0
                    t_first_thought: Optional[float] = None
                    ttft_sec: Optional[float] = None
                    thinking_dur: float = 0.0

                    for raw_line in resp.iter_lines(decode_unicode=False):
                        if not raw_line:
                            continue
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        try:
                            chunk_obj = json.loads(data_str)
                        except Exception:
                            continue

                        for cand in chunk_obj.get("candidates", []):
                            parts = cand.get("content", {}).get("parts", [])
                            for p in parts:
                                # Captura tokens de raciocínio interno (Thinking) em tempo real
                                if p.get("thought"):
                                    thought_chunks_count += 1
                                    if t_first_thought is None:
                                        t_first_thought = round(time.monotonic() - t_start, 2)
                                        self._log(
                                            f"🧠 [Thinking] 1º token de raciocínio interno recebido de [{target_model}] "
                                            f"em {t_first_thought}s! Modelo analisando métricas..."
                                        )
                                        yield {
                                            "type": "thinking_start",
                                            "first_thought_sec": t_first_thought,
                                            "model_used": target_model,
                                        }
                                    yield {
                                        "type": "thinking_chunk",
                                        "thought_index": thought_chunks_count,
                                        "elapsed_sec": round(time.monotonic() - t_start, 2),
                                    }
                                    continue

                                # Captura tokens do relatório final em Markdown
                                if "text" in p and p["text"]:
                                    chunk_text = p["text"]
                                    if ttft_sec is None:
                                        ttft_sec = round(time.monotonic() - t_start, 2)
                                        thinking_dur = round(ttft_sec - (t_first_thought or ttft_sec), 2)
                                        self._log(
                                            f"✍️ [Texto] Raciocínio finalizado ({thinking_dur}s, {thought_chunks_count} blocos)! "
                                            f"1º pedaço de texto visível recebido em {ttft_sec}s. Transmitindo ao vivo..."
                                        )
                                        yield {
                                            "type": "thinking_done",
                                            "thinking_duration_sec": thinking_dur,
                                            "thought_chunks_count": thought_chunks_count,
                                            "ttft_sec": ttft_sec,
                                        }
                                    text_chunks.append(chunk_text)
                                    yield {
                                        "type": "chunk",
                                        "text": chunk_text,
                                        "model_used": target_model,
                                        "ttft_sec": ttft_sec,
                                        "thinking_duration_sec": thinking_dur,
                                    }

                    report_md = "".join(text_chunks).strip()
                    total_elapsed = round(time.monotonic() - t_start, 2)
                    if ttft_sec is None:
                        ttft_sec = total_elapsed
                    generation_dur = round(total_elapsed - ttft_sec, 2)

                    if save_to_db and workout_id and report_md:
                        self.db.save_ai_report(workout_id, report_md)

                    meta = {
                        "model_used": target_model,
                        "primary_model": self.model,
                        "fallback_model": self.fallback_model,
                        "used_fallback": is_fallback,
                        "from_cache": False,
                        "dns_tcp_ms": net_diag.get("tcp_connect_ms"),
                        "dns_ms": net_diag.get("dns_ms"),
                        "primary_ip": net_diag.get("primary_ip"),
                        "payload_kb": payload_kb,
                        "http_connect_sec": http_elapsed,
                        "first_thought_sec": t_first_thought or 0.0,
                        "thinking_duration_sec": thinking_dur,
                        "thought_chunks_count": thought_chunks_count,
                        "ttft_sec": ttft_sec,
                        "generation_duration_sec": generation_dur,
                        "elapsed_sec": total_elapsed,
                        "tools_called": self.last_tools_called,
                        "attempts_log": attempts_log,
                    }
                    self.last_call_metadata = meta
                    self._log(
                        f"🏁 Relatório concluído por [{target_model}] em {total_elapsed}s "
                        f"(HTTP/Prefill: {http_elapsed}s | Thinking: {thinking_dur}s | Escrita: {generation_dur}s | {len(report_md)} caracteres)."
                    )
                    yield {
                        "type": "done",
                        "ai_report_md": report_md,
                        **meta,
                    }
                    return

                # Tratamento de erros HTTP (429, 503, etc.)
                try:
                    err_short = resp.json().get("error", {}).get("message", resp.text)[:160]
                except Exception:
                    err_short = resp.text[:160]

                attempts_log.append(f"{attempt_label} -> HTTP {resp.status_code} em {http_elapsed}s ({err_short})")
                self._log(f"⚠️ {attempt_label} retornou HTTP {resp.status_code}: {err_short}")

                # Se a cota diária acabou ("per day"), pula imediatamente para o fallback
                if resp.status_code == 429 and "per day" in resp.text.lower():
                    self._log(
                        f"🔄 Cota diária de [{target_model}] atingida! Pulando imediatamente para o fallback [{self.fallback_model}]..."
                    )
                    yield {
                        "type": "status",
                        "message": f"Cota diária de {target_model} atingida. Alternando imediatamente para {self.fallback_model}...",
                        "model": target_model,
                        "attempt": attempt + 1,
                    }
                    break

                if resp.status_code in (429, 503) and attempt < 2:
                    wait_sec = 6 * (attempt + 1)
                    self._log(f"⏳ Aguardando {wait_sec}s antes de tentar [{target_model}] novamente...")
                    yield {
                        "type": "status",
                        "message": f"{target_model} retornou HTTP {resp.status_code}. Aguardando {wait_sec}s para tentar novamente...",
                        "model": target_model,
                        "attempt": attempt + 1,
                    }
                    time.sleep(wait_sec)
                    continue
                break

            if resp is not None:
                try:
                    err_msg = resp.json().get("error", {}).get("message", resp.text)
                except Exception:
                    err_msg = resp.text
                errors_log.append(f"[{target_model} -> HTTP {resp.status_code}: {err_msg}]")
                if resp.status_code in (429, 500, 503, 404) and idx + 1 < len(models_to_try):
                    next_model = models_to_try[idx + 1]
                    self._log(f"🔄 Alternando de [{target_model}] para o modelo de fallback [{next_model}]...")
                    yield {
                        "type": "status",
                        "message": f"Alternando para o modelo de fallback {next_model}...",
                        "model": next_model,
                        "attempt": 1,
                        "is_fallback": True,
                    }
                    continue
            elif idx + 1 < len(models_to_try):
                continue
            break

        raise RuntimeError("Erro na chamada da API do Gemini: " + " | ".join(errors_log))

    def chat_about_workouts(
        self,
        user_question: str,
        current_workout_json: Optional[Dict[str, Any]] = None,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Permite conversar livremente com o Treinador IA sobre o treino atual ou qualquer treino do histórico."""
        if not self.is_configured():
            raise RuntimeError(
                "Chave GEMINI_API_KEY não configurada! "
                "Adicione sua chave no arquivo `.env` para conversar com o Treinador IA."
            )

        profile = self.db.get_runner_profile()
        system_prompt = build_coach_system_prompt(profile)
        current_id = current_workout_json.get("workout_id") if current_workout_json else None
        tool_map = self._build_tool_map(current_workout_id=current_id)

        contents: List[Dict[str, Any]] = []

        if current_workout_json:
            context_msg = (
                "Contexto do treino aberto atualmente na tela pelo corredor:\n"
                f"```json\n{json.dumps(current_workout_json, ensure_ascii=False, separators=(',', ':'))}\n```"
            )
            contents.append({"role": "user", "parts": [{"text": context_msg}]})
            contents.append(
                {
                    "role": "model",
                    "parts": [
                        {
                            "text": "Entendido! Estou com os dados completos deste treino e tenho acesso às ferramentas do banco SQLite para consultar qualquer outro treino do seu histórico."
                        }
                    ],
                }
            )

        if chat_history:
            for msg in chat_history:
                role = "model" if msg.get("role") in ("assistant", "model") else "user"
                text = msg.get("content", "")
                if text:
                    contents.append({"role": role, "parts": [{"text": text}]})

        contents.append({"role": "user", "parts": [{"text": user_question}]})

        return self._run_gemini_with_tools(
            system_instruction=system_prompt,
            contents=contents,
            tool_map=tool_map,
        )

    def _run_gemini_with_tools(
        self,
        system_instruction: str,
        contents: List[Dict[str, Any]],
        tool_map: Dict[str, Callable[..., Any]],
        max_tool_rounds: int = 5,
    ) -> str:
        """Executa a conversa com a API do Gemini resolvendo chamadas de função (Tools) automaticamente."""
        conversation = list(contents)
        self.last_tools_called = []

        for _round in range(max_tool_rounds):
            response_data = self._call_gemini_api(
                system_instruction=system_instruction,
                contents=conversation,
                tools_declarations=GEMINI_TOOLS_DECLARATIONS,
            )

            candidates = response_data.get("candidates", [])
            if not candidates:
                raise RuntimeError(f"Resposta vazia da API do Gemini: {response_data}")

            model_content = candidates[0].get("content", {})
            parts = model_content.get("parts", [])
            # Preserva exatamente o objeto `parts` retornado pelo modelo (incluindo thoughtSignature do Gemini 3.x)
            conversation.append({"role": "model", "parts": parts})

            # Verifica se o modelo solicitou chamadas de função (functionCall)
            function_calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not function_calls:
                # Extrai o texto final da resposta (ignorando partes internas de thought se houver)
                text_parts = [p.get("text", "") for p in parts if "text" in p and not p.get("thought")]
                if not text_parts:
                    text_parts = [p.get("text", "") for p in parts if "text" in p]
                return "\n".join(text_parts).strip()

            # Executa cada tool solicitada pela IA no banco SQLite e devolve o resultado como functionResponse
            tool_response_parts: List[Dict[str, Any]] = []
            for fc in function_calls:
                fn_name = fc.get("name", "")
                fn_args = fc.get("args", {}) or {}
                self.last_tools_called.append(f"{fn_name}({json.dumps(fn_args, ensure_ascii=False)})")
                fn = tool_map.get(fn_name)
                if fn is not None:
                    try:
                        result = fn(**fn_args)
                    except Exception as exc:
                        result = {"error": str(exc)}
                else:
                    result = {"error": f"Ferramenta '{fn_name}' não encontrada."}

                fc_resp: Dict[str, Any] = {
                    "name": fn_name,
                    "response": {"result": result},
                }
                if "id" in fc:
                    fc_resp["id"] = fc["id"]

                tool_response_parts.append({"functionResponse": fc_resp})

            conversation.append({"role": "user", "parts": tool_response_parts})

        # Caso atinja o limite de rounds de ferramentas, solicita a síntese final sem novas chamadas de tool
        final_data = self._call_gemini_api(
            system_instruction=system_instruction,
            contents=conversation,
            tools_declarations=None,
        )
        candidates = final_data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return "\n".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought")).strip()
        return "Não foi possível gerar a análise final."

    def _call_gemini_api(
        self,
        system_instruction: str,
        contents: List[Dict[str, Any]],
        tools_declarations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Realiza a requisição HTTP para a API REST v1beta do Google Gemini usando Streaming SSE
        (`streamGenerateContent?alt=sse`) quando não há tools, eliminando completamente o ReadTimeout
        em relatórios longos e mantendo 100% dos JSONs completos no prompt.
        """
        import time

        has_model_turns = any(
            c.get("role") == "model" and any("functionCall" in p for p in c.get("parts", []))
            for c in contents
        )
        if has_model_turns and self.last_model_used:
            models_to_try = [self.last_model_used]
        else:
            models_to_try = []
            for candidate in [self.model, self.fallback_model]:
                if candidate and "3.1-pro" not in candidate and candidate not in models_to_try:
                    models_to_try.append(candidate)
            if not models_to_try:
                models_to_try = ["gemini-3.8-flash", "gemini-3.6-flash"]

        payload: Dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0.3,
                "thinkingConfig": {
                    "thinkingBudget": 1024,
                    "includeThoughts": True,
                },
            },
        }
        if tools_declarations:
            payload["tools"] = [{"functionDeclarations": tools_declarations}]

        # Se não há tools_declarations (ex: geração do relatório completo com JSONs injetados),
        # usamos Streaming SSE (`streamGenerateContent?alt=sse`) para que os chunks cheguem continuamente
        # sem deixar o socket parado esperando o relatório inteiro terminar!
        use_sse_stream = tools_declarations is None
        t_start = time.monotonic()

        errors_log: List[str] = []
        attempts_log: List[str] = []
        for idx, target_model in enumerate(models_to_try):
            is_fallback = idx > 0
            if use_sse_stream:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:streamGenerateContent"
                params = {"key": self.api_key, "alt": "sse"}
            else:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"
                params = {"key": self.api_key}

            # Faz até 3 tentativas no mesmo modelo com backoff exponencial real (6s, 12s) para 429 / 503
            for attempt in range(3):
                attempt_label = f"{target_model} (tentativa {attempt + 1}/3)"
                self._log(
                    f"🚀 Chamando modelo {'FALLBACK ' if is_fallback else 'PRINCIPAL '}[{target_model}] "
                    f"(tentativa {attempt + 1})..."
                )
                req_t0 = time.monotonic()
                try:
                    resp = self._session.post(
                        url,
                        params=params,
                        json=payload,
                        stream=use_sse_stream,
                        timeout=(8.0, 95.0),
                    )
                except requests.exceptions.Timeout as exc:
                    elapsed_req = round(time.monotonic() - req_t0, 2)
                    msg = f"{attempt_label} -> Timeout após {elapsed_req}s: {exc}"
                    errors_log.append(f"[{msg}]")
                    attempts_log.append(msg)
                    self._log(f"⚠️ {msg}")
                    if attempt < 2:
                        time.sleep(5 * (attempt + 1))
                        continue
                    resp = None
                    break
                except requests.exceptions.RequestException as exc:
                    msg = f"{attempt_label} -> Erro de rede: {exc}"
                    errors_log.append(f"[{msg}]")
                    attempts_log.append(msg)
                    self._log(f"❌ {msg}")
                    resp = None
                    break

                http_elapsed = round(time.monotonic() - req_t0, 2)

                if resp.status_code == 200:
                    self.last_model_used = target_model
                    attempts_log.append(f"{attempt_label} -> HTTP 200 OK em {http_elapsed}s")
                    if use_sse_stream:
                        result_obj = self._consume_sse_stream(resp)
                    else:
                        result_obj = resp.json()
                    total_elapsed = round(time.monotonic() - t_start, 2)
                    self.last_call_metadata = {
                        "model_used": target_model,
                        "primary_model": self.model,
                        "fallback_model": self.fallback_model,
                        "used_fallback": is_fallback,
                        "from_cache": False,
                        "elapsed_sec": total_elapsed,
                        "ttft_sec": http_elapsed,
                        "tools_called": self.last_tools_called,
                        "attempts_log": attempts_log,
                    }
                    self._log(
                        f"✅ Resposta concluída por [{target_model}] "
                        f"({'FALLBACK' if is_fallback else 'PRINCIPAL'}) em {total_elapsed}s."
                    )
                    return result_obj

                try:
                    err_short = resp.json().get("error", {}).get("message", resp.text)[:160]
                except Exception:
                    err_short = resp.text[:160]
                attempts_log.append(f"{attempt_label} -> HTTP {resp.status_code} em {http_elapsed}s ({err_short})")
                self._log(f"⚠️ {attempt_label} retornou HTTP {resp.status_code}: {err_short}")

                # Se for HTTP 429 porque a cota DIÁRIA daquele modelo acabou ("per day"),
                # não adianta esperar 6s tentando o mesmo modelo — pula imediatamente para o fallback!
                if resp.status_code == 429 and "per day" in resp.text.lower():
                    self._log(
                        f"🔄 Cota diária de [{target_model}] atingida! Pulando imediatamente para o fallback..."
                    )
                    break

                if resp.status_code in (429, 503) and attempt < 2:
                    wait_sec = 6 * (attempt + 1)
                    self._log(f"⏳ Aguardando {wait_sec}s antes de nova tentativa em [{target_model}]...")
                    time.sleep(wait_sec)
                    continue
                break

            if resp is not None:
                try:
                    err_msg = resp.json().get("error", {}).get("message", resp.text)
                except Exception:
                    err_msg = resp.text
                errors_log.append(f"[{target_model} -> HTTP {resp.status_code}: {err_msg}]")
                if resp.status_code in (429, 500, 503, 404) and idx + 1 < len(models_to_try):
                    self._log(f"🔄 Alternando para fallback [{models_to_try[idx + 1]}]...")
                    continue
            elif idx + 1 < len(models_to_try):
                continue
            break

        raise RuntimeError("Erro na chamada da API do Gemini: " + " | ".join(errors_log))

    @staticmethod
    def _consume_sse_stream(resp: requests.Response) -> Dict[str, Any]:
        """Consome a stream SSE (`data: {...}`) do Gemini forçando UTF-8 (para nunca corromper acentos e emojis)
        e reconstrói o objeto padrão `candidates`.
        """
        resp.encoding = "utf-8"
        accumulated_parts: List[Dict[str, Any]] = []
        text_chunks: List[str] = []

        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                chunk_obj = json.loads(data_str)
            except Exception:
                continue

            for cand in chunk_obj.get("candidates", []):
                parts = cand.get("content", {}).get("parts", [])
                for p in parts:
                    if p.get("thought"):
                        continue
                    if "text" in p:
                        text_chunks.append(p["text"])
                    else:
                        accumulated_parts.append(p)

        if text_chunks:
            accumulated_parts.insert(0, {"text": "".join(text_chunks)})

        return {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": accumulated_parts,
                    }
                }
            ]
        }
