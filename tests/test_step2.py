"""Testes automatizados para o Passo 2: Banco de Dados SQLite e Tools para a IA."""

import tempfile
import unittest
from pathlib import Path

from src.database import MetricsDatabase

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "fit-archive-example"


class TestStep2Database(unittest.TestCase):
    """Valida persistência SQLite, deduplicação, perfil do corredor e tools da IA."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_runs.db"
        self.db = MetricsDatabase(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_runner_profile_crud(self) -> None:
        profile = self.db.get_runner_profile()
        self.assertEqual(profile["running_experience_months"], 2)
        self.assertEqual(profile["max_hr_bpm"], 195)

        updated = self.db.update_runner_profile(name="João", age=22, weight_kg=72.5)
        self.assertEqual(updated["name"], "João")
        self.assertEqual(updated["age"], 22)
        self.assertEqual(updated["weight_kg"], 72.5)

    def test_import_fit_files_and_deduplication(self) -> None:
        w5 = self.db.import_fit_file(EXAMPLES_DIR / "5km.fit", rpe_effort=7, weather_or_notes="Manhã fresca")
        w10 = self.db.import_fit_file(EXAMPLES_DIR / "10km.fit", rpe_effort=8, weather_or_notes="Vários semáforos")
        wint = self.db.import_fit_file(
            EXAMPLES_DIR / "Intervalado.fit", rpe_effort=9, weather_or_notes="4 tiros de 1.2km"
        )

        summaries = self.db.list_workouts_summary()
        self.assertEqual(len(summaries), 3)

        # Testa re-importação do mesmo arquivo (não deve duplicar, deve atualizar notas/RPE)
        self.db.import_fit_file(
            EXAMPLES_DIR / "5km.fit",
            workout_type_confirmed="Rodagem Leve (5 km)",
            rpe_effort=6,
            weather_or_notes="Nota atualizada",
        )
        summaries_after = self.db.list_workouts_summary()
        self.assertEqual(len(summaries_after), 3)

        # Verifica recuperação de workout com timeseries e salvamento de relatório IA
        wid = wint["workout_id"]
        self.db.save_ai_report(wid, "# Relatório IA de Teste\nExcelente treino!")
        loaded = self.db.get_workout(wid, include_timeseries=True)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["ai_report_md"], "# Relatório IA de Teste\nExcelente treino!")
        self.assertGreater(len(loaded["timeseries"]), 1400)

    def test_ai_tools_queries(self) -> None:
        self.db.import_fit_file(EXAMPLES_DIR / "5km.fit")
        self.db.import_fit_file(EXAMPLES_DIR / "10km.fit")
        wint = self.db.import_fit_file(EXAMPLES_DIR / "Intervalado.fit")

        tools = self.db.get_gemini_tools(current_workout_id=wint["workout_id"])
        consultar_ultimos, consultar_tipo, consultar_evolucao = tools

        # Excluindo o treino atual (Intervalado), últimos treinos deve retornar os outros 2 (10km e 5km)
        ultimos = consultar_ultimos(limite=5)
        self.assertEqual(len(ultimos), 2)
        self.assertEqual(ultimos[0]["summary"]["total_distance_km"], 10.01)

        # Consulta por tipo 'Longo'
        longos = consultar_tipo(tipo_treino="Longo")
        self.assertEqual(len(longos), 1)
        self.assertEqual(longos[0]["summary"]["total_distance_km"], 10.01)

        # Consulta evolução e recordes
        evolucao = consultar_evolucao()
        self.assertEqual(evolucao["total_workouts"], 3)
        self.assertAlmostEqual(evolucao["total_distance_accumulated_km"], 19.9, places=1)
        self.assertIsNotNone(evolucao["chronological_timeline"][0]["aerobic_efficiency_factor"])


if __name__ == "__main__":
    unittest.main()
