"""Parser binário nativo de arquivos .FIT (otimizado para Amazfit Active 2 / Zepp).

Lê diretamente a estrutura binária do protocolo FIT (Flexible and Interoperable Data Transfer),
descartando valores sentinela inválidos (ex: 0xFFFFFFFF, 0xFFFF, 0xFF) e normalizando
as escalas e unidades para métricas humanas (km, m/s, min/km, bpm, spm, W, cm, ms).
"""

from __future__ import annotations

import datetime
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Epoch oficial do protocolo Garmin FIT: 31 de Dezembro de 1989 00:00:00 UTC
FIT_EPOCH_OFFSET = 631065600

# Fator de conversão de semicírculos de GPS para graus decimais: 180 / 2^31
SEMICIRCLES_TO_DEGREES = 180.0 / (2**31)

# Mapeamento dos tipos primitivos do protocolo FIT:
# base_type_id -> (struct_format_char, size_in_bytes, invalid_sentinel_value)
FIT_BASE_TYPES: Dict[int, Tuple[str, int, Optional[int]]] = {
    0x00: ("B", 1, 0xFF),          # enum
    0x01: ("b", 1, 0x7F),          # sint8
    0x02: ("B", 1, 0xFF),          # uint8
    0x83: ("h", 2, 0x7FFF),        # sint16
    0x84: ("H", 2, 0xFFFF),        # uint16
    0x85: ("i", 4, 0x7FFFFFFF),    # sint32
    0x86: ("I", 4, 0xFFFFFFFF),    # uint32
    0x07: ("s", 1, None),          # string (null-terminated)
    0x88: ("f", 4, None),          # float32
    0x89: ("d", 8, None),          # float64
    0x0A: ("B", 1, 0x00),          # uint8z
    0x8B: ("H", 2, 0x0000),        # uint16z
    0x8C: ("I", 4, 0x00000000),    # uint32z
    0x0D: ("B", 1, 0xFF),          # byte
    0x8E: ("q", 8, None),          # sint64
    0x8F: ("Q", 8, None),          # uint64
    0x90: ("Q", 8, None),          # uint64z
}


def fit_timestamp_to_datetime(fit_ts: int, tz_offset_hours: int = -3) -> datetime.datetime:
    """Converte um timestamp FIT (segundos desde 1989-12-31 UTC) para datetime local (BRT -03:00)."""
    utc_dt = datetime.datetime.fromtimestamp(fit_ts + FIT_EPOCH_OFFSET, tz=datetime.timezone.utc)
    local_tz = datetime.timezone(datetime.timedelta(hours=tz_offset_hours))
    return utc_dt.astimezone(local_tz)


def speed_to_pace_str(speed_mps: Optional[float]) -> Optional[str]:
    """Converte velocidade em m/s para string de Pace em 'M:SS' por km."""
    if speed_mps is None or speed_mps <= 0.1:
        return None
    sec_per_km = 1000.0 / speed_mps
    minutes = int(sec_per_km // 60)
    seconds = int(round(sec_per_km % 60))
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}"


def format_duration_sec(seconds: Optional[float]) -> str:
    """Formata segundos em string 'MM:SS' ou 'H:MM:SS'."""
    if seconds is None or seconds < 0:
        return "0:00"
    total_sec = int(round(seconds))
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class FitParser:
    """Leitor e decodificador de arquivos .FIT do Amazfit Active 2."""

    def __init__(self, file_path_or_bytes: Union[str, Path, bytes]) -> None:
        if isinstance(file_path_or_bytes, (str, Path)):
            self.source_name = Path(file_path_or_bytes).name
            with open(file_path_or_bytes, "rb") as f:
                self.raw_bytes = f.read()
        else:
            self.source_name = "uploaded_workout.fit"
            self.raw_bytes = file_path_or_bytes

    def parse(self) -> Dict[str, Any]:
        """Decodifica o arquivo .FIT e retorna estruturas normalizadas:
        - session: dict com resumo global da corrida
        - laps: lista de dicts com cada volta (km)
        - records: lista de dicts com a série temporal segundo a segundo
        - events: lista de dicts com eventos de cronômetro (start/stop)
        """
        data = self.raw_bytes
        if len(data) < 14:
            raise ValueError("Arquivo .FIT inválido ou truncado (menor que 14 bytes).")

        header_size = data[0]
        data_size = struct.unpack("<I", data[4:8])[0]
        magic = data[8:12]
        if magic != b".FIT":
            raise ValueError(f"Assinatura mágica inválida no cabeçalho: {magic!r} (esperado b'.FIT').")

        pos = header_size
        end = min(len(data), header_size + data_size)

        local_defs: Dict[int, Tuple[str, int, List[Tuple[int, int, int]], List[Tuple[int, int, int]]]] = {}
        raw_sessions: List[Dict[int, Any]] = []
        raw_laps: List[Dict[int, Any]] = []
        raw_records: List[Dict[int, Any]] = []
        raw_events: List[Dict[int, Any]] = []

        last_timestamp: Optional[int] = None

        while pos < end:
            rec_header = data[pos]
            pos += 1

            # Verifica cabeçalho de timestamp comprimido (bit 7 == 1)
            if rec_header & 0x80:
                is_definition = False
                has_developer_data = False
                local_mesg_num = (rec_header >> 5) & 0x03
                time_offset = rec_header & 0x1F
                if last_timestamp is not None:
                    last_timestamp = (last_timestamp & ~0x1F) + time_offset
                    if last_timestamp < time_offset:
                        last_timestamp += 0x20
            else:
                is_definition = bool(rec_header & 0x40)
                has_developer_data = bool(rec_header & 0x20)
                local_mesg_num = rec_header & 0x0F

            if is_definition:
                # Mensagem de Definição
                _reserved = data[pos]
                arch = data[pos + 1]
                endian = ">" if arch == 1 else "<"
                global_mesg_num = struct.unpack(endian + "H", data[pos + 2 : pos + 4])[0]
                num_fields = data[pos + 4]
                pos += 5

                fields: List[Tuple[int, int, int]] = []
                for _ in range(num_fields):
                    f_num, f_size, f_type = data[pos], data[pos + 1], data[pos + 2]
                    fields.append((f_num, f_size, f_type))
                    pos += 3

                dev_fields: List[Tuple[int, int, int]] = []
                if has_developer_data:
                    num_dev = data[pos]
                    pos += 1
                    for _ in range(num_dev):
                        df_num, df_size, df_idx = data[pos], data[pos + 1], data[pos + 2]
                        dev_fields.append((df_num, df_size, df_idx))
                        pos += 3

                local_defs[local_mesg_num] = (endian, global_mesg_num, fields, dev_fields)
            else:
                # Mensagem de Dados
                if local_mesg_num not in local_defs:
                    raise ValueError(f"Mensagem de dados local {local_mesg_num} sem definição prévia.")

                endian, global_mesg_num, fields, dev_fields = local_defs[local_mesg_num]
                row: Dict[int, Any] = {}
                if (rec_header & 0x80) and last_timestamp is not None:
                    row[253] = last_timestamp

                for f_num, f_size, f_type in fields:
                    raw_val = data[pos : pos + f_size]
                    pos += f_size
                    decoded = self._decode_field(raw_val, endian, f_size, f_type)
                    if decoded is not None:
                        row[f_num] = decoded
                        if f_num == 253 and isinstance(decoded, int):
                            last_timestamp = decoded

                # Pula ou lê developer fields se presentes
                for _df_num, df_size, _df_idx in dev_fields:
                    pos += df_size

                if global_mesg_num == 18:
                    raw_sessions.append(row)
                elif global_mesg_num == 19:
                    raw_laps.append(row)
                elif global_mesg_num == 20:
                    raw_records.append(row)
                elif global_mesg_num == 21:
                    raw_events.append(row)

        session_norm = self._normalize_session(raw_sessions[0]) if raw_sessions else {}
        laps_norm = [self._normalize_lap(lap, i + 1) for i, lap in enumerate(raw_laps)]
        records_norm = self._normalize_records(raw_records)
        events_norm = self._normalize_events(raw_events)

        return {
            "source_file": self.source_name,
            "session": session_norm,
            "laps": laps_norm,
            "records": records_norm,
            "events": events_norm,
        }

    @staticmethod
    def _decode_field(raw: bytes, endian: str, f_size: int, f_type: int) -> Any:
        """Decodifica bytes brutos de um campo FIT descartando sentinelas inválidas."""
        if f_type not in FIT_BASE_TYPES:
            return None

        fmt, base_size, invalid_sentinel = FIT_BASE_TYPES[f_type]
        if fmt == "s":
            text = raw.split(b"\x00")[0].decode("utf-8", errors="replace").strip()
            return text if text else None

        if f_size == base_size:
            val = struct.unpack(endian + fmt, raw)[0]
            if invalid_sentinel is not None and val == invalid_sentinel:
                return None
            return val

        if base_size > 0 and f_size % base_size == 0:
            count = f_size // base_size
            vals = struct.unpack(endian + f"{count}{fmt}", raw)
            valid_vals = [v for v in vals if invalid_sentinel is None or v != invalid_sentinel]
            return valid_vals if valid_vals else None

        return None

    def _normalize_session(self, s: Dict[int, Any]) -> Dict[int, Any]:
        """Normaliza os campos da mensagem Session (18) do Amazfit Active 2."""
        start_ts = s.get(2)
        end_ts = s.get(253)
        start_dt = fit_timestamp_to_datetime(start_ts) if start_ts else None
        end_dt = fit_timestamp_to_datetime(end_ts) if end_ts else None

        total_dist_m = (s[9] / 100.0) if 9 in s else 0.0
        active_time_sec = (s[8] / 1000.0) if 8 in s else 0.0
        elapsed_time_sec = (s[7] / 1000.0) if 7 in s else 0.0

        avg_speed_mps = (s[14] / 1000.0) if 14 in s else (total_dist_m / active_time_sec if active_time_sec > 0 else 0.0)
        max_speed_mps = (s[15] / 1000.0) if 15 in s else None

        # Na mensagem Session (18), o Amazfit grava a cadência em ciclos (RPM, 1 perna). Multiplicamos por 2 para SPM.
        avg_cad_raw = s.get(18)
        max_cad_raw = s.get(19)
        avg_cad_spm = (avg_cad_raw * 2) if (avg_cad_raw is not None and avg_cad_raw < 120) else avg_cad_raw
        max_cad_spm = (max_cad_raw * 2) if (max_cad_raw is not None and max_cad_raw < 120) else max_cad_raw

        # No Amazfit Active 2, field_65 na Session guarda um array de 6 posições (em ms) com o tempo nas zonas de FC
        zones_ms = s.get(65, [])
        hr_zones_sec = {}
        if isinstance(zones_ms, list) and len(zones_ms) >= 6:
            # Posição 0 = Abaixo de Z1 / Relaxado; Posições 1 a 5 = Z1 a Z5
            hr_zones_sec = {
                "z1_warmup": int(round((zones_ms[0] + zones_ms[1]) / 1000.0)),
                "z2_fat_burn": int(round(zones_ms[2] / 1000.0)),
                "z3_aerobic": int(round(zones_ms[3] / 1000.0)),
                "z4_threshold": int(round(zones_ms[4] / 1000.0)),
                "z5_anaerobic_max": int(round(zones_ms[5] / 1000.0)),
            }

        # Training load peak no Amazfit é gravado em escala 65536 (Q16.16) no field 168
        raw_load = s.get(168)
        training_load = int(round(raw_load / 65536.0)) if raw_load else None

        return {
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
            "start_time_iso": start_dt.strftime("%Y-%m-%dT%H:%M:%S") if start_dt else None,
            "end_time_iso": end_dt.strftime("%Y-%m-%dT%H:%M:%S") if end_dt else None,
            "day_of_week": start_dt.strftime("%A") if start_dt else None,
            "total_distance_m": round(total_dist_m, 1),
            "total_distance_km": round(total_dist_m / 1000.0, 2),
            "active_timer_time_sec": int(round(active_time_sec)),
            "active_timer_formatted": format_duration_sec(active_time_sec),
            "total_elapsed_time_sec": int(round(elapsed_time_sec)),
            "total_elapsed_formatted": format_duration_sec(elapsed_time_sec),
            "avg_speed_mps": round(avg_speed_mps, 3) if avg_speed_mps else None,
            "max_speed_mps": round(max_speed_mps, 3) if max_speed_mps else None,
            "avg_pace_min_km": speed_to_pace_str(avg_speed_mps),
            "max_pace_min_km": speed_to_pace_str(max_speed_mps),
            "calories_kcal": s.get(11),
            "avg_hr_bpm": s.get(16),
            "max_hr_bpm": s.get(17),
            "min_hr_bpm": s.get(64),
            "avg_cadence_spm": avg_cad_spm,
            "max_cadence_spm": max_cad_spm,
            "avg_power_watts": s.get(20),
            "max_power_watts": s.get(21),
            "elevation_gain_m": s.get(22, 0),
            "elevation_loss_m": s.get(23, 0),
            "training_effect_aerobic": round(s[24] / 10.0, 1) if 24 in s else None,
            "training_effect_anaerobic": round(s[137] / 10.0, 1) if 137 in s else None,
            "training_load_score": training_load,
            "hr_zones_time_sec": hr_zones_sec,
        }

    def _normalize_lap(self, lap: Dict[int, Any], lap_idx: int) -> Dict[str, Any]:
        """Normaliza uma volta (Lap - mensagem 19)."""
        dist_m = (lap[9] / 100.0) if 9 in lap else 0.0
        timer_sec = (lap[8] / 1000.0) if 8 in lap else 0.0
        elapsed_sec = (lap[7] / 1000.0) if 7 in lap else 0.0
        avg_speed_mps = (lap[13] / 1000.0) if 13 in lap else (dist_m / timer_sec if timer_sec > 0 else 0.0)

        # Na mensagem Lap (19), o Amazfit já grava avg_cadence (campo 17) em SPM (~160-175).
        # Mas aplicamos checagem se < 115 para garantir consistência.
        raw_cad = lap.get(17)
        cad_spm = (raw_cad * 2) if (raw_cad is not None and raw_cad < 115) else raw_cad

        return {
            "km": lap_idx,
            "start_timestamp": lap.get(2),
            "end_timestamp": lap.get(253),
            "distance_m": round(dist_m, 1),
            "active_time_sec": round(timer_sec, 1),
            "elapsed_time_sec": round(elapsed_sec, 1),
            "pace_min_km": speed_to_pace_str(avg_speed_mps),
            "avg_speed_mps": round(avg_speed_mps, 3) if avg_speed_mps else None,
            "avg_hr_bpm": lap.get(15),
            "avg_cadence_spm": cad_spm,
            "calories_kcal": lap.get(11),
            "elev_gain_m": lap.get(21, 0),
            "elev_loss_m": lap.get(22, 0),
            "lap_trigger": lap.get(24),
        }

    def _normalize_records(self, raw_records: List[Dict[int, Any]]) -> List[Dict[str, Any]]:
        """Normaliza os registros segundo a segundo (Record - mensagem 20),
        interpolando/mantendo a última distância válida quando o sensor omite o campo num segundo.
        """
        normalized: List[Dict[str, Any]] = []
        last_valid_distance_m = 0.0

        for r in raw_records:
            ts = r.get(253)
            if ts is None:
                continue

            # Distância acumulada (campo 5, escala 100 -> metros)
            if 5 in r and r[5] is not None:
                dist_m = r[5] / 100.0
                last_valid_distance_m = dist_m
            else:
                dist_m = last_valid_distance_m

            # Velocidade (campo 6, escala 1000 -> m/s)
            speed_mps = (r[6] / 1000.0) if (6 in r and r[6] is not None) else None

            # Altitude (campo 2, escala 5, offset 500 -> metros)
            altitude_m = ((r[2] / 5.0) - 500.0) if (2 in r and r[2] is not None) else None

            # Frequência Cardíaca (campo 3 -> bpm)
            hr_bpm = r.get(3)
            if hr_bpm is not None and (hr_bpm <= 30 or hr_bpm >= 240):
                hr_bpm = None

            # Cadência (campo 4 -> rpm * 2 = spm)
            cad_rpm = r.get(4)
            cad_spm = (cad_rpm * 2) if (cad_rpm is not None and cad_rpm > 0) else 0

            # Potência (campo 7 -> Watts)
            power_w = r.get(7)

            # Running Dynamics no pulso (Amazfit Active 2):
            # - Campo 39: Vertical Oscillation (escala 10 -> mm; dividimos por 100 para cm, ou 10 para mm)
            vo_mm = (r[39] / 10.0) if (39 in r and r[39] is not None and r[39] > 0) else None
            vo_cm = round(vo_mm / 10.0, 2) if vo_mm is not None else None

            # - Campo 41: Stance Time / Ground Contact Time (escala 10 -> ms)
            stance_ms = (r[41] / 10.0) if (41 in r and r[41] is not None and r[41] > 0) else None

            # - Campo 83: Vertical Ratio (escala 100 -> %)
            v_ratio_pct = (r[83] / 100.0) if (83 in r and r[83] is not None and r[83] > 0) else None

            # - Campo 85: Step Length (escala 10 -> mm; dividimos por 10000 para metros)
            step_mm = (r[85] / 10.0) if (85 in r and r[85] is not None and r[85] > 0) else None
            step_m = round(step_mm / 1000.0, 3) if step_mm is not None else None

            # Coordenadas GPS (semicircles -> graus)
            lat = (r[0] * SEMICIRCLES_TO_DEGREES) if (0 in r and r[0] is not None) else None
            lon = (r[1] * SEMICIRCLES_TO_DEGREES) if (1 in r and r[1] is not None) else None

            normalized.append(
                {
                    "timestamp": ts,
                    "distance_m": round(dist_m, 2),
                    "speed_mps": round(speed_mps, 3) if speed_mps is not None else None,
                    "pace_min_km": speed_to_pace_str(speed_mps),
                    "heart_rate_bpm": hr_bpm,
                    "cadence_spm": cad_spm,
                    "power_w": power_w,
                    "altitude_m": round(altitude_m, 1) if altitude_m is not None else None,
                    "vertical_oscillation_cm": vo_cm,
                    "ground_contact_time_ms": round(stance_ms, 1) if stance_ms is not None else None,
                    "vertical_ratio_pct": round(v_ratio_pct, 2) if v_ratio_pct is not None else None,
                    "step_length_m": step_m,
                    "lat": round(lat, 6) if lat is not None else None,
                    "lon": round(lon, 6) if lon is not None else None,
                }
            )

        return normalized

    @staticmethod
    def _normalize_events(raw_events: List[Dict[int, Any]]) -> List[Dict[str, Any]]:
        """Normaliza os eventos de timer (start = 0, stop_all = 4)."""
        events: List[Dict[str, Any]] = []
        for ev in raw_events:
            ts = ev.get(253)
            ev_code = ev.get(0)       # 0 = timer
            ev_type = ev.get(1)       # 0 = start, 4 = stop_all / pause
            if ts is not None and ev_code == 0 and ev_type in (0, 4):
                events.append(
                    {
                        "timestamp": ts,
                        "type": "start" if ev_type == 0 else "stop",
                    }
                )
        return events
