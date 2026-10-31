# Schema do Documento JSON de Treino (`workout_json`)

Este documento define a estrutura exata do JSON gerado pelo motor Python após processar um arquivo `.FIT` do **Amazfit Active 2** e combiná-lo com os inputs do usuário.

Cada corrida analisada é salva no banco de dados `SQLite` com este JSON completo. É exatamente esta estrutura que o **Google Gemini** recebe do treino atual e consulta dos treinos anteriores (via *Function Calling / Tools*) para tirar conclusões sobre o treino e a evolução histórica.

---

## 1. Exemplo Real Extraído do `Intervalado.fit`

Abaixo está o JSON real gerado a partir dos dados binários do arquivo [`fit-archive-example/Intervalado.fit`](file:///home/jvnasc/USP/projetos/metrics-analyzer/fit-archive-example/Intervalado.fit):

```json
{
  "workout_id": "2026-10-24_180920_intervalado",
  "metadata": {
    "date": "2026-10-24T18:09:20",
    "day_of_week": "Wednesday",
    "device": "Amazfit Active 2",
    "workout_type_detected": "Intervalado / Tiros",
    "workout_type_confirmed": "Intervalado / Tiros",
    "user_context": {
      "rpe_effort_1_to_10": 9,
      "weather_or_notes": "Quarta-feira de tiros com meu amigo. 4 tiros de ~1.2km com 3 min de pausa."
    }
  },
  "summary": {
    "total_distance_km": 4.88,
    "active_timer_time_sec": 1412,
    "active_timer_formatted": "23:32",
    "total_elapsed_time_sec": 1949,
    "total_elapsed_formatted": "32:29",
    "avg_pace_min_km": "4:49",
    "max_pace_min_km": "3:47",
    "calories_kcal": 327,
    "elevation_gain_m": 3,
    "elevation_loss_m": 0
  },
  "physiology": {
    "avg_hr_bpm": 180,
    "max_hr_bpm": 195,
    "training_effect_aerobic": 3.9,
    "training_effect_anaerobic": 3.1,
    "training_load_score": 204,
    "cardiac_drift_pct": 4.8,
    "hr_zones_time_sec": {
      "z1_warmup": 13,
      "z2_fat_burn": 19,
      "z3_aerobic": 70,
      "z4_threshold": 494,
      "z5_anaerobic_max": 812
    }
  },
  "biomechanics_running_dynamics": {
    "avg_cadence_spm": 170,
    "max_cadence_spm": 180,
    "avg_step_length_m": 1.24,
    "avg_vertical_oscillation_cm": 7.45,
    "avg_vertical_ratio_pct": 6.1,
    "avg_ground_contact_time_ms": 263,
    "avg_power_watts": 252,
    "max_power_watts": 315
  },
  "pauses_analysis": {
    "traffic_lights_under_60s": {
      "count": 1,
      "total_time_sec": 1,
      "durations_sec": [1]
    },
    "rest_stops_over_60s": {
      "count": 3,
      "total_time_sec": 535,
      "stops": [
        {
          "after_km": 1.23,
          "duration_sec": 179,
          "hr_at_stop": 182,
          "hr_at_resume": 118,
          "hr_recovery_drop": 64
        },
        {
          "after_km": 2.45,
          "duration_sec": 178,
          "hr_at_stop": 191,
          "hr_at_resume": 124,
          "hr_recovery_drop": 67
        },
        {
          "after_km": 3.67,
          "duration_sec": 178,
          "hr_at_stop": 193,
          "hr_at_resume": 129,
          "hr_recovery_drop": 64
        }
      ]
    }
  },
  "active_blocks_or_intervals": [
    {
      "block_number": 1,
      "distance_m": 1233,
      "duration_sec": 365,
      "duration_formatted": "6:05",
      "pace_min_km": "4:56",
      "avg_hr_bpm": 170,
      "max_hr_bpm": 183,
      "avg_power_w": 248,
      "avg_cadence_spm": 166,
      "avg_step_length_m": 1.27,
      "avg_vertical_oscillation_cm": 7.18,
      "avg_ground_contact_ms": 267
    },
    {
      "block_number": 2,
      "distance_m": 1225,
      "duration_sec": 342,
      "duration_formatted": "5:42",
      "pace_min_km": "4:39",
      "avg_hr_bpm": 181,
      "max_hr_bpm": 193,
      "avg_power_w": 255,
      "avg_cadence_spm": 165,
      "avg_step_length_m": 1.26,
      "avg_vertical_oscillation_cm": 7.45,
      "avg_ground_contact_ms": 270
    },
    {
      "block_number": 3,
      "distance_m": 1212,
      "duration_sec": 351,
      "duration_formatted": "5:51",
      "pace_min_km": "4:49",
      "avg_hr_bpm": 184,
      "max_hr_bpm": 195,
      "avg_power_w": 256,
      "avg_cadence_spm": 168,
      "avg_step_length_m": 1.22,
      "avg_vertical_oscillation_cm": 7.53,
      "avg_ground_contact_ms": 260
    },
    {
      "block_number": 4,
      "distance_m": 1212,
      "duration_sec": 353,
      "duration_formatted": "5:53",
      "pace_min_km": "4:51",
      "avg_hr_bpm": 186,
      "max_hr_bpm": 195,
      "avg_power_w": 252,
      "avg_cadence_spm": 169,
      "avg_step_length_m": 1.20,
      "avg_vertical_oscillation_cm": 7.63,
      "avg_ground_contact_ms": 256
    }
  ],
  "splits_per_km": [
    { "km": 1, "pace_min_km": "4:49", "avg_hr_bpm": 167, "avg_cadence_spm": 160, "elev_gain_m": 0, "elev_loss_m": 0 },
    { "km": 2, "pace_min_km": "4:49", "avg_hr_bpm": 177, "avg_cadence_spm": 172, "elev_gain_m": 1, "elev_loss_m": 0 },
    { "km": 3, "pace_min_km": "4:44", "avg_hr_bpm": 182, "avg_cadence_spm": 175, "elev_gain_m": 1, "elev_loss_m": 0 },
    { "km": 4, "pace_min_km": "4:56", "avg_hr_bpm": 185, "avg_cadence_spm": 174, "elev_gain_m": 1, "elev_loss_m": 0 },
    { "km": 5, "distance_m": 882, "pace_min_km": "4:48", "avg_hr_bpm": 186, "avg_cadence_spm": 172, "elev_gain_m": 0, "elev_loss_m": 0 }
  ]
}
```

---

## 2. Explicação dos Blocos do JSON

1. **`metadata`**: Identifica a data, dia da semana, qual era a proposta do treino (ex: *Intervalado / Tiros*, *Rodagem Leve*, *Longo*) e o contexto que você informou na interface (esforço percebido de 1 a 10 e observações como clima ou dores).
2. **`summary`**: Dados gerais da sessão descontando o tempo parado (`active_timer_time_sec` vs `total_elapsed_time_sec`).
3. **`physiology`**: Todo o comportamento cardiovascular do treino, incluindo tempo nas 5 zonas de FC, Training Effect (Aeróbico e Anaeróbico) e Deriva Cardíaca (*Cardiac Drift*).
4. **`biomechanics_running_dynamics`**: As métricas mecânicas do Amazfit Active 2 já convertidas para unidades humanas (SPM, metros, centímetros, milissegundos e Watts).
5. **`pauses_analysis`**: Separação clara entre paradas rápidas de trânsito/semáforo ($\le 60\text{s}$) e paradas reais de descanso ($> 60\text{s}$), incluindo quantos batimentos seu coração recuperou em cada pausa (`hr_recovery_drop`).
6. **`active_blocks_or_intervals`**: Os blocos reais de corrida contínua separados por pausas $> 60\text{s}$. Em um treino intervalado feito pausando o relógio, cada item aqui é **exatamente um tiro**.
7. **`splits_per_km`**: As voltas tradicionais de 1 km em 1 km gravadas pelo relógio, essenciais para treinos contínuos de 5 km e 10–15 km.
