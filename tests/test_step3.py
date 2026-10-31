"""Testes automatizados para o Passo 3: GeminiCoach, suporte a .env e ciclo de Function Calling."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ai_coach import GeminiCoach, build_coach_system_prompt
from src.database import MetricsDatabase

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "fit-archive-example"


class TestStep3AICoach(unittest.TestCase):
    """Valida a construção do System Prompt, carregamento de configuração e o loop de Tools."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_runs.db"
        self.db = MetricsDatabase(self.db_path)

        # Popula o banco com os 3 treinos reais
        self.w5 = self.db.import_fit_file(EXAMPLES_DIR / "5km.fit")
        self.w10 = self.db.import_fit_file(EXAMPLES_DIR / "10km.fit")
        self.wint = self.db.import_fit_file(EXAMPLES_DIR / "Intervalado.fit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_system_prompt_generation(self) -> None:
        profile = self.db.get_runner_profile()
        prompt = build_coach_system_prompt(profile)
        self.assertIn("Amazfit Active 2", prompt)
        self.assertIn("195 bpm", prompt)
        self.assertIn("traffic_lights_under_60s", prompt)

    def test_gemini_tool_calling_loop_and_db_caching(self) -> None:
        coach = GeminiCoach(db=self.db, api_key="TEST_KEY_123", model="gemini-2.5-flash")
        self.assertTrue(coach.is_configured())

        # Simula 2 turnos da API do Gemini:
        # Turno 1: Gemini pede para chamar `consultar_ultimos_treinos(limite=2)` e `consultar_evolucao_e_recordes()`
        # Turno 2: Gemini recebe os JSONs do banco e devolve o relatório Markdown final
        mock_responses = [
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "consultar_ultimos_treinos",
                                        "args": {"limite": 2},
                                    }
                                },
                                {
                                    "functionCall": {
                                        "name": "consultar_evolucao_e_recordes",
                                        "args": {},
                                    }
                                },
                            ]
                        }
                    }
                ]
            },
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "## 🎯 Veredito Geral do Treino\nExcelente treino intervalado com 4 tiros!"
                                }
                            ]
                        }
                    }
                ]
            },
        ]

        # Verifica o fluxo de `analyze_workout` (1 única chamada rápida com os JSONs do SQLite já pré-consultados)
        single_turn_resp = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": "## 🎯 Veredito Geral do Treino\nExcelente treino intervalado com 4 tiros!"
                            }
                        ]
                    }
                }
            ]
        }

        call_log = []

        def fake_call_single(system_instruction, contents, tools_declarations=None):
            call_log.append(list(contents))
            return single_turn_resp

        with patch.object(coach, "_call_gemini_api", side_effect=fake_call_single):
            report = coach.analyze_workout(self.wint, save_to_db=True)

        self.assertIn("Veredito Geral do Treino", report)
        self.assertEqual(len(call_log), 1)

        # Verifica se o relatório ficou salvo em cache no SQLite (não deve chamar a API de novo)
        with patch.object(coach, "_call_gemini_api", side_effect=AssertionError("Não deveria chamar API!")):
            cached_report = coach.analyze_workout(self.wint, force_regenerate=False)
            self.assertEqual(cached_report, report)

        # E verifica se o `chat_about_workouts` continua suportando multi-turn Function Calling normalmente
        call_log_chat = []

        def fake_call_chat(system_instruction, contents, tools_declarations=None):
            call_log_chat.append(list(contents))
            return mock_responses[len(call_log_chat) - 1]

        with patch.object(coach, "_call_gemini_api", side_effect=fake_call_chat):
            chat_reply = coach.chat_about_workouts("Compare meus treinos", current_workout_json=self.wint)
            self.assertIn("Veredito Geral", chat_reply)
            self.assertEqual(len(call_log_chat), 2)

    def test_network_diagnose_to_google(self) -> None:
        from src.ai_coach import diagnose_network_to_google
        diag = diagnose_network_to_google(host="127.0.0.1", port=80)
        self.assertIn("dns_ms", diag)
        self.assertIn("ok", diag)


if __name__ == "__main__":
    unittest.main()
