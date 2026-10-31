"""Testes automatizados para o Passo 1: FitParser e WorkoutAnalyzer."""

import unittest
from pathlib import Path

from src.analyzer import process_fit_to_workout_json
from src.parser import FitParser

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "fit-archive-example"


class TestStep1ParserAndAnalyzer(unittest.TestCase):
    """Valida a extração binária .FIT e a geração do workout_json nos 3 arquivos reais."""

    def test_intervalado_fit(self) -> None:
        wjson = process_fit_to_workout_json(
            EXAMPLES_DIR / "Intervalado.fit",
            rpe_effort=9,
            weather_or_notes="Treino de tiros quarta-feira",
        )
        self.assertEqual(wjson["metadata"]["workout_type_detected"], "Intervalado / Tiros")
        self.assertEqual(wjson["summary"]["total_distance_km"], 4.88)
        self.assertEqual(wjson["summary"]["avg_pace_min_km"], "4:49")
        self.assertEqual(wjson["physiology"]["avg_hr_bpm"], 180)
        self.assertEqual(wjson["physiology"]["max_hr_bpm"], 195)

        # Pausas: 1 micro-pausa <= 60s (1s) e 3 descansos de ~3 min (> 60s)
        self.assertEqual(wjson["pauses_analysis"]["traffic_lights_under_60s"]["count"], 1)
        self.assertEqual(wjson["pauses_analysis"]["rest_stops_over_60s"]["count"], 3)

        # 4 tiros detectados com ~1.2km cada
        blocks = wjson["active_blocks_or_intervals"]
        self.assertEqual(len(blocks), 4)
        for b in blocks:
            self.assertGreater(b["distance_m"], 1150)
            self.assertLess(b["distance_m"], 1300)
            self.assertIsNotNone(b["avg_step_length_m"])

    def test_10km_fit_traffic_lights_filter(self) -> None:
        wjson = process_fit_to_workout_json(EXAMPLES_DIR / "10km.fit")
        self.assertEqual(wjson["metadata"]["workout_type_detected"], "Treino Longo (10–15 km)")
        self.assertEqual(wjson["summary"]["total_distance_km"], 10.01)
        self.assertEqual(wjson["summary"]["avg_pace_min_km"], "6:51")

        # 12 semáforos <= 60s e 8 paradas > 60s
        self.assertEqual(wjson["pauses_analysis"]["traffic_lights_under_60s"]["count"], 12)
        self.assertEqual(wjson["pauses_analysis"]["traffic_lights_under_60s"]["total_time_sec"], 274)
        self.assertEqual(wjson["pauses_analysis"]["rest_stops_over_60s"]["count"], 8)
        self.assertEqual(len(wjson["splits_per_km"]), 10)

    def test_5km_fit(self) -> None:
        wjson = process_fit_to_workout_json(EXAMPLES_DIR / "5km.fit")
        self.assertEqual(wjson["metadata"]["workout_type_detected"], "Rodagem (5 km)")
        self.assertEqual(wjson["summary"]["total_distance_km"], 5.01)
        self.assertEqual(wjson["summary"]["avg_pace_min_km"], "5:18")
        self.assertEqual(wjson["pauses_analysis"]["traffic_lights_under_60s"]["count"], 0)
        self.assertEqual(wjson["pauses_analysis"]["rest_stops_over_60s"]["count"], 2)
        self.assertEqual(len(wjson["splits_per_km"]), 5)


if __name__ == "__main__":
    unittest.main()
