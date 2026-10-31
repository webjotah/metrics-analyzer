"""Camada de Persistência Local SQLite (`runs.db`) e Ferramentas de Consulta (Tools) para a IA.

Responsabilidades:
1. Gerenciar a tabela `runner_profile` (perfil fisiológico e rotina Seg/Qua/Sex do corredor).
2. Gerenciar a tabela `workouts` armazenando:
   - Colunas indexadas para filtros rápidos (data, tipo de treino, distância, pace, FC).
   - `workout_json`: O documento JSON completo do treino (conforme `docs/JSON_SCHEMA.md`) que a IA consulta.
   - `timeseries_json`: A série temporal segundo a segundo (`records`) para renderização dos gráficos no Dashboard.
   - `ai_report_md`: Relatório em Markdown gerado pelo Gemini (cacheado para evitar gastos repetidos de API).
3. Prover métodos e *Function Calling Tools* (`buscar_ultimos_treinos`, `buscar_treinos_mesmo_tipo`,
   `buscar_evolucao_e_recordes`, `buscar_detalhes_treino_por_id`) prontos para o Google Gemini consultar.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from src.analyzer import WorkoutAnalyzer
from src.parser import FitParser

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "runs.db"


class MetricsDatabase:
    """Gerenciador do banco de dados SQLite para histórico de corridas e consultas da IA."""

    def __init__(self, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Cria as tabelas necessárias caso ainda não existam e garante o perfil padrão."""
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runner_profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    name TEXT DEFAULT 'Corredor',
                    age INTEGER DEFAULT 25,
                    weight_kg REAL DEFAULT 75.0,
                    max_hr_bpm INTEGER DEFAULT 195,
                    resting_hr_bpm INTEGER DEFAULT 60,
                    running_experience_months INTEGER DEFAULT 2,
                    weekly_routine_description TEXT DEFAULT '3x por semana (Seg/Qua/Sex): Segunda e Sexta alternam entre Rodagem Leve (5km) e Longo (10-15km); Quarta-feira é dia de treino forte (Intervalado/Tiros ou Fartlek).',
                    current_goals TEXT DEFAULT 'Entender melhor as métricas do Amazfit Active 2, melhorar condicionamento aeróbico e evoluir o pace com segurança.',
                    updated_at TEXT
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workouts (
                    workout_id TEXT PRIMARY KEY,
                    start_time_iso TEXT UNIQUE NOT NULL,
                    day_of_week TEXT,
                    workout_type TEXT NOT NULL,
                    total_distance_km REAL NOT NULL,
                    active_timer_time_sec INTEGER NOT NULL,
                    avg_pace_min_km TEXT,
                    avg_hr_bpm INTEGER,
                    max_hr_bpm INTEGER,
                    avg_cadence_spm INTEGER,
                    avg_power_watts INTEGER,
                    rpe_effort INTEGER,
                    weather_or_notes TEXT,
                    workout_json TEXT NOT NULL,
                    timeseries_json TEXT,
                    ai_report_md TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            # Garante que existe a linha única (id=1) de perfil do corredor
            cur = conn.execute("SELECT COUNT(*) as cnt FROM runner_profile WHERE id = 1")
            if cur.fetchone()["cnt"] == 0:
                now_iso = datetime.datetime.now().isoformat(timespec="seconds")
                conn.execute(
                    "INSERT INTO runner_profile (id, updated_at) VALUES (1, ?)",
                    (now_iso,),
                )
            conn.commit()

    # -------------------------------------------------------------------------
    # Perfil do Corredor
    # -------------------------------------------------------------------------
    def get_runner_profile(self) -> Dict[str, Any]:
        """Retorna o perfil atual do corredor."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM runner_profile WHERE id = 1").fetchone()
            return dict(row) if row else {}

    def update_runner_profile(
        self,
        name: Optional[str] = None,
        age: Optional[int] = None,
        weight_kg: Optional[float] = None,
        max_hr_bpm: Optional[int] = None,
        resting_hr_bpm: Optional[int] = None,
        running_experience_months: Optional[int] = None,
        weekly_routine_description: Optional[str] = None,
        current_goals: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atualiza os campos fornecidos do perfil do corredor."""
        current = self.get_runner_profile()
        updated = {
            "name": name if name is not None else current.get("name", "Corredor"),
            "age": age if age is not None else current.get("age", 25),
            "weight_kg": weight_kg if weight_kg is not None else current.get("weight_kg", 75.0),
            "max_hr_bpm": max_hr_bpm if max_hr_bpm is not None else current.get("max_hr_bpm", 195),
            "resting_hr_bpm": resting_hr_bpm if resting_hr_bpm is not None else current.get("resting_hr_bpm", 60),
            "running_experience_months": (
                running_experience_months
                if running_experience_months is not None
                else current.get("running_experience_months", 2)
            ),
            "weekly_routine_description": (
                weekly_routine_description
                if weekly_routine_description is not None
                else current.get("weekly_routine_description", "")
            ),
            "current_goals": (
                current_goals if current_goals is not None else current.get("current_goals", "")
            ),
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }

        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE runner_profile
                SET name = :name,
                    age = :age,
                    weight_kg = :weight_kg,
                    max_hr_bpm = :max_hr_bpm,
                    resting_hr_bpm = :resting_hr_bpm,
                    running_experience_months = :running_experience_months,
                    weekly_routine_description = :weekly_routine_description,
                    current_goals = :current_goals,
                    updated_at = :updated_at
                WHERE id = 1
                """,
                updated,
            )
            conn.commit()
        return self.get_runner_profile()

    # -------------------------------------------------------------------------
    # Persistência e Importação de Treinos (.FIT / workout_json)
    # -------------------------------------------------------------------------
    def save_workout(
        self,
        workout_json: Dict[str, Any],
        timeseries_records: Optional[List[Dict[str, Any]]] = None,
        ai_report_md: Optional[str] = None,
    ) -> str:
        """Salva ou atualiza (UPSERT por start_time_iso/workout_id) um treino no banco SQLite."""
        workout_id = workout_json["workout_id"]
        meta = workout_json.get("metadata", {})
        summary = workout_json.get("summary", {})
        phys = workout_json.get("physiology", {})
        bio = workout_json.get("biomechanics_running_dynamics", {})
        user_ctx = meta.get("user_context", {})

        start_time_iso = meta.get("date")
        if not start_time_iso:
            raise ValueError("workout_json não possui metadata.date válido.")

        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        workout_json_str = json.dumps(workout_json, ensure_ascii=False)
        timeseries_json_str = (
            json.dumps(timeseries_records, ensure_ascii=False)
            if timeseries_records is not None
            else None
        )

        with self._get_conn() as conn:
            # Verifica se já existe um treino com o mesmo start_time_iso (para evitar duplicatas ao re-subir arquivo)
            existing = conn.execute(
                "SELECT workout_id, timeseries_json, ai_report_md FROM workouts WHERE start_time_iso = ?",
                (start_time_iso,),
            ).fetchone()

            if existing:
                # Se já existia e o usuário mudou o tipo do treino, removemos o registro antigo para atualizar o workout_id
                if existing["workout_id"] != workout_id:
                    conn.execute("DELETE FROM workouts WHERE start_time_iso = ?", (start_time_iso,))
                if timeseries_json_str is None:
                    timeseries_json_str = existing["timeseries_json"]
                if ai_report_md is None:
                    ai_report_md = existing["ai_report_md"]

            conn.execute(
                """
                INSERT INTO workouts (
                    workout_id, start_time_iso, day_of_week, workout_type,
                    total_distance_km, active_timer_time_sec, avg_pace_min_km,
                    avg_hr_bpm, max_hr_bpm, avg_cadence_spm, avg_power_watts,
                    rpe_effort, weather_or_notes, workout_json, timeseries_json,
                    ai_report_md, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(workout_id) DO UPDATE SET
                    workout_type = excluded.workout_type,
                    rpe_effort = excluded.rpe_effort,
                    weather_or_notes = excluded.weather_or_notes,
                    workout_json = excluded.workout_json,
                    timeseries_json = COALESCE(excluded.timeseries_json, workouts.timeseries_json),
                    ai_report_md = COALESCE(excluded.ai_report_md, workouts.ai_report_md)
                """,
                (
                    workout_id,
                    start_time_iso,
                    meta.get("day_of_week"),
                    meta.get("workout_type_confirmed") or meta.get("workout_type_detected") or "Rodagem (5 km)",
                    summary.get("total_distance_km", 0.0),
                    summary.get("active_timer_time_sec", 0),
                    summary.get("avg_pace_min_km"),
                    phys.get("avg_hr_bpm"),
                    phys.get("max_hr_bpm"),
                    bio.get("avg_cadence_spm"),
                    bio.get("avg_power_watts"),
                    user_ctx.get("rpe_effort_1_to_10"),
                    user_ctx.get("weather_or_notes", ""),
                    workout_json_str,
                    timeseries_json_str,
                    ai_report_md,
                    now_iso,
                ),
            )
            conn.commit()

        # Se a FC máxima atingida no treino superar a FC máxima cadastrada no perfil, atualiza automaticamente!
        max_hr_workout = phys.get("max_hr_bpm")
        profile = self.get_runner_profile()
        if max_hr_workout and profile.get("max_hr_bpm") and max_hr_workout > profile["max_hr_bpm"]:
            self.update_runner_profile(max_hr_bpm=int(max_hr_workout))

        return workout_id

    def import_fit_file(
        self,
        file_path_or_bytes: Union[str, Path, bytes],
        workout_type_confirmed: Optional[str] = None,
        rpe_effort: Optional[int] = None,
        weather_or_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fluxo completo: lê o .FIT, gera o workout_json + timeseries, salva no SQLite e retorna o workout_json."""
        parser = FitParser(file_path_or_bytes)
        parsed = parser.parse()
        analyzer = WorkoutAnalyzer(parsed)
        wjson = analyzer.build_workout_json(
            workout_type_confirmed=workout_type_confirmed,
            rpe_effort=rpe_effort,
            weather_or_notes=weather_or_notes,
        )
        self.save_workout(wjson, timeseries_records=parsed.get("records", []))
        return wjson

    def save_ai_report(self, workout_id: str, ai_report_md: str) -> None:
        """Salva ou atualiza o relatório em Markdown gerado pela IA para um treino."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE workouts SET ai_report_md = ? WHERE workout_id = ?",
                (ai_report_md, workout_id),
            )
            conn.commit()

    def get_workout(self, workout_id: str, include_timeseries: bool = False) -> Optional[Dict[str, Any]]:
        """Recupera um treino pelo ID, incluindo o `workout_json` desserializado e o relatório da IA."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM workouts WHERE workout_id = ?", (workout_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["workout_json"] = json.loads(result["workout_json"])
            if include_timeseries and result.get("timeseries_json"):
                result["timeseries"] = json.loads(result["timeseries_json"])
            result.pop("timeseries_json", None)
            return result

    def list_workouts_summary(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Lista os resumos de todos os treinos do mais recente para o mais antigo (para tabelas/menus do Dashboard)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT workout_id, start_time_iso, day_of_week, workout_type,
                       total_distance_km, active_timer_time_sec, avg_pace_min_km,
                       avg_hr_bpm, max_hr_bpm, avg_cadence_spm, avg_power_watts,
                       rpe_effort, weather_or_notes,
                       CASE WHEN ai_report_md IS NOT NULL AND ai_report_md != '' THEN 1 ELSE 0 END AS has_ai_report
                FROM workouts
                ORDER BY start_time_iso DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Ferramentas de Consulta (Tools) para o Treinador IA (Google Gemini)
    # -------------------------------------------------------------------------
    def buscar_ultimos_treinos(
        self,
        limite: int = 5,
        excluir_workout_id: Optional[str] = None,
        antes_de_iso: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retorna os documentos JSON completos (`workout_json`) dos últimos N treinos realizados.
        Se `antes_de_iso` for informado (ex: data do treino que está sendo analisado), retorna apenas
        os treinos que ocorreram cronologicamente ANTES daquele treino!
        """
        limite = max(1, min(int(limite), 20))
        with self._get_conn() as conn:
            if antes_de_iso and excluir_workout_id:
                rows = conn.execute(
                    """
                    SELECT workout_json FROM workouts
                    WHERE workout_id != ? AND start_time_iso < ?
                    ORDER BY start_time_iso DESC
                    LIMIT ?
                    """,
                    (excluir_workout_id, antes_de_iso, limite),
                ).fetchall()
            elif excluir_workout_id:
                rows = conn.execute(
                    """
                    SELECT workout_json FROM workouts
                    WHERE workout_id != ?
                    ORDER BY start_time_iso DESC
                    LIMIT ?
                    """,
                    (excluir_workout_id, limite),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT workout_json FROM workouts
                    ORDER BY start_time_iso DESC
                    LIMIT ?
                    """,
                    (limite,),
                ).fetchall()
            return [json.loads(r["workout_json"]) for r in rows]

    def buscar_treinos_posteriores(
        self,
        depois_de_iso: str,
        limite: int = 5,
        excluir_workout_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retorna os documentos JSON completos (`workout_json`) dos treinos realizados DEPOIS de `depois_de_iso`."""
        limite = max(1, min(int(limite), 20))
        with self._get_conn() as conn:
            if excluir_workout_id:
                rows = conn.execute(
                    """
                    SELECT workout_json FROM workouts
                    WHERE workout_id != ? AND start_time_iso > ?
                    ORDER BY start_time_iso ASC
                    LIMIT ?
                    """,
                    (excluir_workout_id, depois_de_iso, limite),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT workout_json FROM workouts
                    WHERE start_time_iso > ?
                    ORDER BY start_time_iso ASC
                    LIMIT ?
                    """,
                    (depois_de_iso, limite),
                ).fetchall()
            return [json.loads(r["workout_json"]) for r in rows]

    def buscar_treinos_mesmo_tipo(
        self,
        tipo_treino: str,
        limite: int = 5,
        excluir_workout_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retorna os documentos JSON completos (`workout_json`) dos últimos treinos do mesmo tipo.
        Exemplos de `tipo_treino`: 'Rodagem (5 km)', 'Treino Longo (10–15 km)', 'Intervalado / Tiros', 'Fartlek'.
        Ideal para comparar tiro a tiro, parciais por km, FC e biomecânica em treinos de mesma proposta.
        """
        limite = max(1, min(int(limite), 15))
        search_term = f"%{tipo_treino.strip()}%"
        with self._get_conn() as conn:
            if excluir_workout_id:
                rows = conn.execute(
                    """
                    SELECT workout_json FROM workouts
                    WHERE workout_type LIKE ? AND workout_id != ?
                    ORDER BY start_time_iso DESC
                    LIMIT ?
                    """,
                    (search_term, excluir_workout_id, limite),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT workout_json FROM workouts
                    WHERE workout_type LIKE ?
                    ORDER BY start_time_iso DESC
                    LIMIT ?
                    """,
                    (search_term, limite),
                ).fetchall()
            return [json.loads(r["workout_json"]) for r in rows]

    def buscar_evolucao_e_recordes(self) -> Dict[str, Any]:
        """Retorna um panorama estatístico de todos os treinos no banco, recordes de ritmo/distância
        e a linha do tempo de evolução aeróbica (Pace vs FC vs Cadência) para a IA analisar progresso.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT workout_id, start_time_iso, workout_type, total_distance_km,
                       active_timer_time_sec, avg_pace_min_km, avg_hr_bpm, max_hr_bpm,
                       avg_cadence_spm, avg_power_watts, rpe_effort
                FROM workouts
                ORDER BY start_time_iso ASC
                """
            ).fetchall()

        if not rows:
            return {"total_workouts": 0, "timeline": [], "records": {}}

        timeline = [dict(r) for r in rows]
        longest_run = max(timeline, key=lambda x: x["total_distance_km"] or 0.0)
        highest_power = max(timeline, key=lambda x: x["avg_power_watts"] or 0)

        # Calcula Fator de Eficiência (metros por minuto / FC média) para medir evolução aeróbica
        for item in timeline:
            dist_m = (item["total_distance_km"] or 0.0) * 1000.0
            time_min = (item["active_timer_time_sec"] or 1) / 60.0
            hr = item["avg_hr_bpm"] or 0
            if dist_m > 0 and time_min > 0 and hr > 0:
                speed_m_per_min = dist_m / time_min
                item["aerobic_efficiency_factor"] = round(speed_m_per_min / hr, 3)
            else:
                item["aerobic_efficiency_factor"] = None

        return {
            "total_workouts": len(timeline),
            "total_distance_accumulated_km": round(sum(r["total_distance_km"] or 0.0 for r in timeline), 2),
            "longest_workout": {
                "workout_id": longest_run["workout_id"],
                "date": longest_run["start_time_iso"],
                "distance_km": longest_run["total_distance_km"],
                "avg_pace_min_km": longest_run["avg_pace_min_km"],
                "avg_hr_bpm": longest_run["avg_hr_bpm"],
            },
            "highest_power_workout": {
                "workout_id": highest_power["workout_id"],
                "date": highest_power["start_time_iso"],
                "avg_power_watts": highest_power["avg_power_watts"],
                "avg_pace_min_km": highest_power["avg_pace_min_km"],
            },
            "chronological_timeline": timeline,
        }

    def get_gemini_tools(self, current_workout_id: Optional[str] = None) -> List[Callable[..., Any]]:
        """Retorna a lista de funções Python tipadas e documentadas para serem passadas
        diretamente no parâmetro `tools=[...]` da API do Google Gemini (`google-genai`).
        """

        def consultar_ultimos_treinos(limite: int = 5) -> List[Dict[str, Any]]:
            """Consulta os JSONs completos dos últimos treinos realizados pelo corredor no banco SQLite.

            Args:
                limite: Quantidade de treinos recentes para retornar (padrão 5, máximo 15).
            """
            return self.buscar_ultimos_treinos(limite=limite, excluir_workout_id=current_workout_id)

        def consultar_treinos_mesmo_tipo(tipo_treino: str, limite: int = 5) -> List[Dict[str, Any]]:
            """Consulta os JSONs completos de treinos anteriores do mesmo tipo para comparação direta.

            Args:
                tipo_treino: Nome ou parte do tipo do treino. Exemplos: 'Intervalado', 'Longo', 'Rodagem', 'Fartlek'.
                limite: Quantidade máxima de treinos daquele tipo para retornar (padrão 5).
            """
            return self.buscar_treinos_mesmo_tipo(
                tipo_treino=tipo_treino,
                limite=limite,
                excluir_workout_id=current_workout_id,
            )

        def consultar_evolucao_e_recordes() -> Dict[str, Any]:
            """Consulta o histórico cronológico resumido, total de km acumulados, recordes e o Fator de Eficiência Aeróbica de todas as corridas."""
            return self.buscar_evolucao_e_recordes()

        return [
            consultar_ultimos_treinos,
            consultar_treinos_mesmo_tipo,
            consultar_evolucao_e_recordes,
        ]
