"""Motor Fisiológico e Biomecânico para Corridas do Amazfit Active 2.

Recebe os dados normalizados do FitParser e gera o documento JSON rico (`workout_json`)
seguindo a especificação em `docs/JSON_SCHEMA.md`.

Principais responsabilidades:
1. Filtragem inteligente de pausas:
   - Micro-pausas <= 60s: classificadas como semáforo/trânsito (`traffic_lights_under_60s`).
   - Pausas > 60s: classificadas como descanso/recuperação (`rest_stops_over_60s`),
     calculando a queda de Frequência Cardíaca (HRR - Heart Rate Recovery) em cada parada.
2. Segmentação em blocos ativos / tiros (`active_blocks_or_intervals`) divididos por pausas > 60s,
   descartando ruído de GPS pós-semáforo nos cálculos de consistência.
3. Cálculo de métricas biomecânicas agregadas (Running Dynamics no pulso).
4. Cálculo de Deriva Cardíaca (`cardiac_drift_pct` - Desacoplamento Aeróbico Pa:Hr).
5. Classificação inteligente do tipo de treino da rotina (Seg / Qua / Sex).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.parser import FitParser, format_duration_sec, speed_to_pace_str


class WorkoutAnalyzer:
    """Processa os dados extraídos do .FIT e constrói o JSON estruturado do treino."""

    def __init__(
        self,
        parsed_fit: Dict[str, Any],
        traffic_light_threshold_sec: int = 60,
        post_pause_gps_grace_sec: int = 6,
    ) -> None:
        self.parsed = parsed_fit
        self.traffic_threshold = traffic_light_threshold_sec
        self.gps_grace_sec = post_pause_gps_grace_sec

        self.session: Dict[str, Any] = parsed_fit.get("session", {})
        self.laps: List[Dict[str, Any]] = parsed_fit.get("laps", [])
        self.records: List[Dict[str, Any]] = parsed_fit.get("records", [])
        self.events: List[Dict[str, Any]] = parsed_fit.get("events", [])
        self.source_file: str = parsed_fit.get("source_file", "workout.fit")

    def build_workout_json(
        self,
        workout_type_confirmed: Optional[str] = None,
        rpe_effort: Optional[int] = None,
        weather_or_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gera o dicionário JSON completo do treino pronto para o banco SQLite e IA."""
        pauses_info = self._analyze_pauses()
        active_blocks = self._extract_active_blocks()
        biomechanics = self._compute_biomechanics()
        cardiac_drift = self._compute_cardiac_drift(active_blocks)
        splits = self._format_splits()
        detected_type = self._detect_workout_type(active_blocks, pauses_info)

        final_type = workout_type_confirmed if workout_type_confirmed else detected_type
        workout_id = self._generate_workout_id(final_type)

        return {
            "workout_id": workout_id,
            "metadata": {
                "source_file": self.source_file,
                "date": self.session.get("start_time_iso"),
                "day_of_week": self.session.get("day_of_week"),
                "device": "Amazfit Active 2",
                "workout_type_detected": detected_type,
                "workout_type_confirmed": final_type,
                "user_context": {
                    "rpe_effort_1_to_10": rpe_effort,
                    "weather_or_notes": weather_or_notes or "",
                },
            },
            "summary": {
                "total_distance_km": self.session.get("total_distance_km"),
                "active_timer_time_sec": self.session.get("active_timer_time_sec"),
                "active_timer_formatted": self.session.get("active_timer_formatted"),
                "total_elapsed_time_sec": self.session.get("total_elapsed_time_sec"),
                "total_elapsed_formatted": self.session.get("total_elapsed_formatted"),
                "avg_pace_min_km": self.session.get("avg_pace_min_km"),
                "max_pace_min_km": self.session.get("max_pace_min_km"),
                "calories_kcal": self.session.get("calories_kcal"),
                "elevation_gain_m": self.session.get("elevation_gain_m", 0),
                "elevation_loss_m": self.session.get("elevation_loss_m", 0),
            },
            "physiology": {
                "avg_hr_bpm": self.session.get("avg_hr_bpm"),
                "max_hr_bpm": self.session.get("max_hr_bpm"),
                "min_hr_bpm": self.session.get("min_hr_bpm"),
                "training_effect_aerobic": self.session.get("training_effect_aerobic"),
                "training_effect_anaerobic": self.session.get("training_effect_anaerobic"),
                "training_load_score": self.session.get("training_load_score"),
                "cardiac_drift_pct": cardiac_drift,
                "hr_zones_time_sec": self.session.get("hr_zones_time_sec", {}),
            },
            "biomechanics_running_dynamics": biomechanics,
            "pauses_analysis": pauses_info,
            "active_blocks_or_intervals": active_blocks,
            "splits_per_km": splits,
        }

    def _analyze_pauses(self) -> Dict[str, Any]:
        """Analisa os eventos de timer stop/start e separa semáforos (<= 60s) de descansos (> 60s)."""
        traffic_lights: List[int] = []
        rest_stops: List[Dict[str, Any]] = []

        # Mapeia os timestamps dos records para busca rápida de distância e FC antes/depois da pausa
        records_by_ts = {r["timestamp"]: r for r in self.records}
        sorted_ts = sorted(records_by_ts.keys())

        def find_hr_before_stop(target_ts: int) -> Tuple[float, Optional[int]]:
            candidates = [ts for ts in sorted_ts if ts <= target_ts]
            if not candidates:
                return 0.0, None
            dist_km = round(records_by_ts[candidates[-1]]["distance_m"] / 1000.0, 2)
            for ts in reversed(candidates[-5:]):
                hr = records_by_ts[ts].get("heart_rate_bpm")
                if hr is not None:
                    return dist_km, hr
            return dist_km, None

        def find_hr_after_resume(target_ts: int) -> Optional[int]:
            # No Amazfit Active 2, o 1º segundo após dar resume frequentemente repete o último HR antes da pausa
            # ou vem None enquanto o sensor óptico reativa (1 a 3 segundos). Pegamos a menor leitura válida nos primeiros 5s pós-pausa.
            candidates = [ts for ts in sorted_ts if target_ts <= ts <= target_ts + 6]
            valid_hrs = [
                records_by_ts[ts]["heart_rate_bpm"]
                for ts in candidates[1:]  # pula o segundo 0 (cache do stop)
                if records_by_ts[ts].get("heart_rate_bpm") is not None
            ]
            if valid_hrs:
                return int(min(valid_hrs))
            # Fallback se só houver no segundo 0
            if candidates and records_by_ts[candidates[0]].get("heart_rate_bpm") is not None:
                return int(records_by_ts[candidates[0]]["heart_rate_bpm"])
            return None

        for i in range(len(self.events) - 1):
            ev_curr = self.events[i]
            ev_next = self.events[i + 1]
            if ev_curr["type"] == "stop" and ev_next["type"] == "start":
                stop_ts = ev_curr["timestamp"]
                start_ts = ev_next["timestamp"]
                duration = start_ts - stop_ts
                if duration <= 0:
                    continue

                if duration <= self.traffic_threshold:
                    traffic_lights.append(duration)
                else:
                    dist_km, hr_stop = find_hr_before_stop(stop_ts)
                    hr_resume = find_hr_after_resume(start_ts)
                    hr_drop = (hr_stop - hr_resume) if (hr_stop is not None and hr_resume is not None) else None

                    rest_stops.append(
                        {
                            "after_km": dist_km,
                            "duration_sec": duration,
                            "duration_formatted": format_duration_sec(duration),
                            "hr_at_stop": hr_stop,
                            "hr_at_resume": hr_resume,
                            "hr_recovery_drop": hr_drop,
                        }
                    )

        return {
            "traffic_lights_under_60s": {
                "count": len(traffic_lights),
                "total_time_sec": sum(traffic_lights),
                "durations_sec": traffic_lights,
            },
            "rest_stops_over_60s": {
                "count": len(rest_stops),
                "total_time_sec": sum(s["duration_sec"] for s in rest_stops),
                "stops": rest_stops,
            },
        }

    def _extract_active_blocks(self) -> List[Dict[str, Any]]:
        """Divide a corrida em blocos contínuos separados por pausas de descanso (> 60s).
        Micro-pausas (<= 60s, como semáforos) NÃO quebram o bloco, e seu tempo parado é descontado.
        """
        if not self.records:
            return []

        raw_blocks: List[List[Dict[str, Any]]] = []
        current_block: List[Dict[str, Any]] = []

        for r in self.records:
            if current_block:
                gap = r["timestamp"] - current_block[-1]["timestamp"]
                if gap > self.traffic_threshold:
                    raw_blocks.append(current_block)
                    current_block = [r]
                else:
                    current_block.append(r)
            else:
                current_block.append(r)

        if current_block:
            raw_blocks.append(current_block)

        blocks_summary: List[Dict[str, Any]] = []
        for idx, block in enumerate(raw_blocks):
            if len(block) < 5:
                continue

            # Calcula o tempo ativo dentro do bloco (descontando gaps de semáforo > 2s e <= 60s)
            active_duration_sec = 0
            post_semaphore_timestamps = set()
            for j in range(1, len(block)):
                dt = block[j]["timestamp"] - block[j - 1]["timestamp"]
                if dt <= 2:
                    active_duration_sec += dt
                else:
                    # Ocorreu uma micro-pausa de semáforo (entre 3s e 60s)
                    # Marcamos os próximos `gps_grace_sec` segundos como retomada pós-semáforo
                    resume_ts = block[j]["timestamp"]
                    for k in range(j, min(len(block), j + self.gps_grace_sec)):
                        if block[k]["timestamp"] - resume_ts <= self.gps_grace_sec:
                            post_semaphore_timestamps.add(block[k]["timestamp"])

            dist_m = max(0.0, block[-1]["distance_m"] - block[0]["distance_m"])
            if active_duration_sec <= 0 or dist_m < 10.0:
                continue

            avg_speed_mps = dist_m / active_duration_sec

            # Filtra os records limpos (sem os segundos de lag do GPS logo após abrir o semáforo)
            clean_records = [r for r in block if r["timestamp"] not in post_semaphore_timestamps]
            if not clean_records:
                clean_records = block

            hrs = [r["heart_rate_bpm"] for r in block if r.get("heart_rate_bpm") is not None]
            pows = [r["power_w"] for r in clean_records if r.get("power_w") is not None and r["power_w"] > 0]
            cads = [r["cadence_spm"] for r in clean_records if r.get("cadence_spm") is not None and r["cadence_spm"] > 100]
            steps = [r["step_length_m"] for r in clean_records if r.get("step_length_m") is not None and r["step_length_m"] > 0.3]
            vos = [r["vertical_oscillation_cm"] for r in clean_records if r.get("vertical_oscillation_cm") is not None]
            gcts = [r["ground_contact_time_ms"] for r in clean_records if r.get("ground_contact_time_ms") is not None]

            blocks_summary.append(
                {
                    "block_number": len(blocks_summary) + 1,
                    "distance_m": int(round(dist_m)),
                    "duration_sec": int(round(active_duration_sec)),
                    "duration_formatted": format_duration_sec(active_duration_sec),
                    "pace_min_km": speed_to_pace_str(avg_speed_mps),
                    "avg_hr_bpm": int(round(sum(hrs) / len(hrs))) if hrs else None,
                    "max_hr_bpm": int(max(hrs)) if hrs else None,
                    "avg_power_w": int(round(sum(pows) / len(pows))) if pows else None,
                    "avg_cadence_spm": int(round(sum(cads) / len(cads))) if cads else None,
                    "avg_step_length_m": round(sum(steps) / len(steps), 2) if steps else None,
                    "avg_vertical_oscillation_cm": round(sum(vos) / len(vos), 2) if vos else None,
                    "avg_ground_contact_ms": int(round(sum(gcts) / len(gcts))) if gcts else None,
                }
            )

        return blocks_summary

    def _compute_biomechanics(self) -> Dict[str, Any]:
        """Calcula as médias e máximas biomecânicas (Running Dynamics) em movimento."""
        moving = [
            r for r in self.records
            if r.get("speed_mps") is not None and r["speed_mps"] > 1.2
        ]
        if not moving:
            moving = self.records

        cads = [r["cadence_spm"] for r in moving if r.get("cadence_spm") and r["cadence_spm"] > 100]
        steps = [r["step_length_m"] for r in moving if r.get("step_length_m") and r["step_length_m"] > 0.3]
        vos = [r["vertical_oscillation_cm"] for r in moving if r.get("vertical_oscillation_cm")]
        vratios = [r["vertical_ratio_pct"] for r in moving if r.get("vertical_ratio_pct")]
        gcts = [r["ground_contact_time_ms"] for r in moving if r.get("ground_contact_time_ms")]
        pows = [r["power_w"] for r in moving if r.get("power_w")]

        return {
            "avg_cadence_spm": self.session.get("avg_cadence_spm") or (int(round(sum(cads) / len(cads))) if cads else None),
            "max_cadence_spm": self.session.get("max_cadence_spm") or (int(max(cads)) if cads else None),
            "avg_step_length_m": round(sum(steps) / len(steps), 2) if steps else None,
            "avg_vertical_oscillation_cm": round(sum(vos) / len(vos), 2) if vos else None,
            "avg_vertical_ratio_pct": round(sum(vratios) / len(vratios), 1) if vratios else None,
            "avg_ground_contact_time_ms": int(round(sum(gcts) / len(gcts))) if gcts else None,
            "avg_power_watts": self.session.get("avg_power_watts") or (int(round(sum(pows) / len(pows))) if pows else None),
            "max_power_watts": self.session.get("max_power_watts") or (int(max(pows)) if pows else None),
        }

    def _compute_cardiac_drift(self, active_blocks: List[Dict[str, Any]]) -> Optional[float]:
        """Calcula a Deriva Cardíaca (Desacoplamento Aeróbico Pa:Hr) em %.
        Compara o Fator de Eficiência (Velocidade / FC) da 1ª metade com a 2ª metade da corrida
        (descartando os primeiros 3 minutos de aquecimento inicial onde a FC ainda está subindo).
        Valor positivo indica quanto o custo cardíaco para manter a velocidade subiu na 2ª metade.
        """
        if len(self.records) < 300:
            return None

        start_ts = self.records[0]["timestamp"]
        # Ignora os primeiros 180s (aquecimento cardiovascular inicial)
        steady_records = [
            r for r in self.records
            if (r["timestamp"] - start_ts) >= 180
            and r.get("speed_mps") is not None and r["speed_mps"] > 1.5
            and r.get("heart_rate_bpm") is not None and r["heart_rate_bpm"] > 100
        ]
        if len(steady_records) < 120:
            return None

        mid = len(steady_records) // 2
        first_half = steady_records[:mid]
        second_half = steady_records[mid:]

        ef_1 = (
            sum(r["speed_mps"] for r in first_half) / len(first_half)
        ) / (
            sum(r["heart_rate_bpm"] for r in first_half) / len(first_half)
        )
        ef_2 = (
            sum(r["speed_mps"] for r in second_half) / len(second_half)
        ) / (
            sum(r["heart_rate_bpm"] for r in second_half) / len(second_half)
        )

        if ef_1 <= 0:
            return None

        # Desacoplamento (%) = ((EF_1 - EF_2) / EF_1) * 100
        # Se EF_2 < EF_1, significa que na 2ª metade precisou de mais batimentos para a mesma velocidade (drift positivo)
        drift_pct = ((ef_1 - ef_2) / ef_1) * 100.0
        return round(drift_pct, 1)

    def _format_splits(self) -> List[Dict[str, Any]]:
        """Formata a lista de parciais por quilômetro (`splits_per_km`).
        Caso a última volta parcial (ex: 882m finais) não traga FC ou cadência agregada na mensagem Lap,
        calcula a partir dos records daquele intervalo de tempo.
        """
        formatted: List[Dict[str, Any]] = []
        for lap in self.laps:
            dist_m = lap.get("distance_m", 1000.0)
            # Ignora última volta residual se tiver menos de 50 metros
            if dist_m < 50.0:
                continue

            start_ts = lap.get("start_timestamp")
            end_ts = lap.get("end_timestamp")
            lap_records = [
                r for r in self.records
                if start_ts is not None and end_ts is not None and start_ts <= r["timestamp"] <= end_ts
            ]

            avg_hr = lap.get("avg_hr_bpm")
            if avg_hr is None and lap_records:
                hrs = [r["heart_rate_bpm"] for r in lap_records if r.get("heart_rate_bpm") is not None]
                if hrs:
                    avg_hr = int(round(sum(hrs) / len(hrs)))

            avg_cad = lap.get("avg_cadence_spm")
            if avg_cad is None and lap_records:
                cads = [r["cadence_spm"] for r in lap_records if r.get("cadence_spm") and r["cadence_spm"] > 100]
                if cads:
                    avg_cad = int(round(sum(cads) / len(cads)))

            pace = lap.get("pace_min_km")
            if pace is None and lap.get("active_time_sec", 0) > 0:
                pace = speed_to_pace_str(dist_m / lap["active_time_sec"])

            item: Dict[str, Any] = {
                "km": lap["km"],
                "distance_m": int(round(dist_m)),
                "pace_min_km": pace,
                "avg_hr_bpm": avg_hr,
                "avg_cadence_spm": avg_cad,
                "elev_gain_m": lap.get("elev_gain_m", 0),
                "elev_loss_m": lap.get("elev_loss_m", 0),
            }
            formatted.append(item)
        return formatted

    def _detect_workout_type(
        self,
        active_blocks: List[Dict[str, Any]],
        pauses_info: Dict[str, Any],
    ) -> str:
        """Detecta automaticamente o tipo de treino com base na rotina do usuário:
        - Intervalado / Tiros (3+ blocos similares separados por descansos > 60s e alta intensidade)
        - Treino Longo (10–15 km) (distância >= 8.0 km)
        - Fartlek (variação alta de velocidade sem pausas estruturadas)
        - Rodagem / 5km (distância < 8.0 km)
        """
        dist_km = self.session.get("total_distance_km") or 0.0
        rest_count = pauses_info["rest_stops_over_60s"]["count"]
        anaerobic_te = self.session.get("training_effect_anaerobic") or 0.0

        # Verifica padrão de tiros/intervalado (ex: 3 ou mais tiros com distâncias parecidas e pausas > 60s)
        if len(active_blocks) >= 3 and rest_count >= 2:
            block_dists = [b["distance_m"] for b in active_blocks]
            avg_b_dist = sum(block_dists) / len(block_dists)
            # Se os blocos têm tamanho consistente (ex: tiros de 400m a 2000m) ou alto efeito anaeróbico
            if avg_b_dist > 200 and max(block_dists) - min(block_dists) < 350 and anaerobic_te >= 2.0:
                return "Intervalado / Tiros"

        if dist_km >= 8.0:
            return "Treino Longo (10–15 km)"

        if anaerobic_te >= 2.5 and rest_count <= 1:
            return "Fartlek"

        return "Rodagem (5 km)"

    def _generate_workout_id(self, workout_type: str) -> str:
        """Gera um ID único e legível baseado na data/hora de início e no tipo de treino."""
        iso = self.session.get("start_time_iso") or "unknown_date"
        clean_ts = iso.replace("-", "").replace(":", "").replace("T", "_")
        slug = re.sub(r"[^a-z0-9]+", "_", workout_type.lower()).strip("_")
        return f"{clean_ts}_{slug}"


def process_fit_to_workout_json(
    file_path_or_bytes: Union[str, Path, bytes],
    workout_type_confirmed: Optional[str] = None,
    rpe_effort: Optional[int] = None,
    weather_or_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Função utilitária de alto nível: recebe o caminho ou bytes de um arquivo .FIT
    e retorna o `workout_json` completo e analisado.
    """
    parser = FitParser(file_path_or_bytes)
    parsed_data = parser.parse()
    analyzer = WorkoutAnalyzer(parsed_data)
    return analyzer.build_workout_json(
        workout_type_confirmed=workout_type_confirmed,
        rpe_effort=rpe_effort,
        weather_or_notes=weather_or_notes,
    )
