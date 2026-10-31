"""Testes automatizados para o Passo 4: Servidor Web e API REST do Dashboard (`app.py`)."""

import base64
import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import DashboardRequestHandler

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "fit-archive-example"


class TestStep4WebDashboard(unittest.TestCase):
    """Valida as rotas HTTP GET/POST do servidor web local (`app.py`)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardRequestHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def _get_json(self, path: str):
        with urllib.request.urlopen(f"{self.base_url}{path}") as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    def test_static_index_and_status(self) -> None:
        with urllib.request.urlopen(f"{self.base_url}/") as resp:
            html = resp.read().decode("utf-8")
            self.assertIn("Amazfit Active 2", html)

        status = self._get_json("/api/status")
        self.assertTrue(status["ok"])

    def test_workouts_and_evolution_endpoints(self) -> None:
        workouts = self._get_json("/api/workouts")["workouts"]
        self.assertGreaterEqual(len(workouts), 3)

        wid = workouts[0]["workout_id"]
        detail = self._get_json(f"/api/workout?id={wid}")
        self.assertEqual(detail["workout_id"], wid)
        self.assertIn("workout_json", detail)
        self.assertIn("timeseries", detail)

        evol = self._get_json("/api/evolution")
        self.assertGreaterEqual(evol["total_workouts"], 3)

    def test_preview_and_upload_fit(self) -> None:
        fit_bytes = (EXAMPLES_DIR / "5km.fit").read_bytes()
        b64_str = base64.b64encode(fit_bytes).decode("ascii")

        preview = self._post_json("/api/preview_fit", {"file_base64": b64_str, "file_name": "5km.fit"})
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["preview"]["summary"]["total_distance_km"], 5.01)

    def test_analyze_ai_stream_cached(self) -> None:
        workouts = self._get_json("/api/workouts")["workouts"]
        wid = workouts[0]["workout_id"]
        original = DashboardRequestHandler.db.get_workout(wid, include_timeseries=False)
        orig_report = original.get("ai_report_md") if original else None

        try:
            DashboardRequestHandler.db.save_ai_report(wid, "## Relatório de Teste em Cache")
            data = json.dumps({"workout_id": wid, "force": False}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/analyze_ai_stream",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                raw_sse = resp.read().decode("utf-8")
                self.assertIn('"type": "model_selected"', raw_sse)
                self.assertIn('"type": "chunk"', raw_sse)
                self.assertIn('"type": "done"', raw_sse)
                self.assertIn("Relatório de Teste em Cache", raw_sse)
        finally:
            DashboardRequestHandler.db.save_ai_report(wid, orig_report or "")


if __name__ == "__main__":
    unittest.main()
