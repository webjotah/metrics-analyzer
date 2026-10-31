"""Servidor Web Local e API REST do Running Metrics Analyzer (`app.py`).

Roda com zero dependências externas de servidor (usando `http.server` / `ThreadingHTTPServer`
nativo do Python), servindo o Dashboard Web Moderno em `http://localhost:8501` e expondo
os endpoints JSON que conectam o Frontend ao FitParser, WorkoutAnalyzer, SQLite e GeminiCoach.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import sys
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from src.ai_coach import GeminiCoach
from src.analyzer import process_fit_to_workout_json
from src.database import MetricsDatabase

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_DIR = PROJECT_ROOT / "web"
EXAMPLES_DIR = PROJECT_ROOT / "fit-archive-example"


def ensure_initial_seed(db: MetricsDatabase) -> None:
    """Garante que os 3 arquivos .FIT de exemplo estejam no banco caso o banco esteja vazio."""
    existing = db.list_workouts_summary(limit=5)
    if not existing and EXAMPLES_DIR.exists():
        for fname in ["5km.fit", "10km.fit", "Intervalado.fit"]:
            fpath = EXAMPLES_DIR / fname
            if fpath.exists():
                db.import_fit_file(fpath)


class DashboardRequestHandler(BaseHTTPRequestHandler):
    """Handler HTTP para servir arquivos estáticos do Dashboard (`web/`) e rotas `/api/*`."""

    db = MetricsDatabase()
    coach = GeminiCoach(db=db)

    def log_message(self, format: str, *args: Any) -> None:
        # Log mais limpo no terminal
        sys.stderr.write(f"[Dashboard] {self.address_string()} - {format % args}\n")

    def _send_json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        try:
            if path == "/api/status":
                self._send_json(
                    {
                        "ok": True,
                        "ai_configured": self.coach.is_configured(),
                        "model": self.coach.model,
                        "fallback_model": self.coach.fallback_model,
                    }
                )
                return

            if path == "/api/profile":
                self._send_json(self.db.get_runner_profile())
                return

            if path == "/api/workouts":
                workouts = self.db.list_workouts_summary(limit=100)
                self._send_json({"workouts": workouts})
                return

            if path == "/api/workout":
                wid = query.get("id", [None])[0]
                if not wid:
                    self._send_json({"error": "Parâmetro 'id' é obrigatório."}, HTTPStatus.BAD_REQUEST)
                    return
                w = self.db.get_workout(wid, include_timeseries=True)
                if not w:
                    self._send_json({"error": f"Treino '{wid}' não encontrado."}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json(w)
                return

            if path == "/api/evolution":
                self._send_json(self.db.buscar_evolucao_e_recordes())
                return

            # Arquivos estáticos em web/
            self._serve_static(path)
        except Exception as exc:
            traceback.print_exc()
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        try:
            payload = self._read_json_body()

            if path == "/api/profile":
                updated = self.db.update_runner_profile(
                    name=payload.get("name"),
                    age=int(payload["age"]) if payload.get("age") is not None else None,
                    weight_kg=float(payload["weight_kg"]) if payload.get("weight_kg") is not None else None,
                    max_hr_bpm=int(payload["max_hr_bpm"]) if payload.get("max_hr_bpm") is not None else None,
                    resting_hr_bpm=int(payload["resting_hr_bpm"]) if payload.get("resting_hr_bpm") is not None else None,
                    running_experience_months=(
                        int(payload["running_experience_months"])
                        if payload.get("running_experience_months") is not None
                        else None
                    ),
                    weekly_routine_description=payload.get("weekly_routine_description"),
                    current_goals=payload.get("current_goals"),
                )
                self._send_json({"ok": True, "profile": updated})
                return

            if path == "/api/preview_fit":
                # Recebe base64 do arquivo .FIT para detectar automaticamente o tipo de treino antes de salvar
                b64_data = payload.get("file_base64", "")
                if not b64_data:
                    self._send_json({"error": "Arquivo .FIT vazio."}, HTTPStatus.BAD_REQUEST)
                    return
                raw_bytes = base64.b64decode(b64_data)
                wjson = process_fit_to_workout_json(raw_bytes)
                wjson["metadata"]["source_file"] = payload.get("file_name", "uploaded.fit")
                self._send_json({"ok": True, "preview": wjson})
                return

            if path == "/api/upload_fit":
                b64_data = payload.get("file_base64", "")
                if not b64_data:
                    self._send_json({"error": "Arquivo .FIT não enviado."}, HTTPStatus.BAD_REQUEST)
                    return
                raw_bytes = base64.b64decode(b64_data)
                workout_type = payload.get("workout_type_confirmed")
                rpe = int(payload["rpe_effort"]) if payload.get("rpe_effort") else None
                notes = payload.get("weather_or_notes", "")

                wjson = self.db.import_fit_file(
                    raw_bytes,
                    workout_type_confirmed=workout_type,
                    rpe_effort=rpe,
                    weather_or_notes=notes,
                )
                self._send_json({"ok": True, "workout_id": wjson["workout_id"], "workout_json": wjson})
                return

            if path == "/api/update_workout_context":
                wid = payload.get("workout_id")
                existing = self.db.get_workout(wid, include_timeseries=False) if wid else None
                if not existing:
                    self._send_json({"error": "Treino não encontrado."}, HTTPStatus.NOT_FOUND)
                    return
                wjson = existing["workout_json"]
                if payload.get("workout_type_confirmed"):
                    wjson["metadata"]["workout_type_confirmed"] = payload["workout_type_confirmed"]
                if "rpe_effort" in payload:
                    wjson["metadata"]["user_context"]["rpe_effort_1_to_10"] = (
                        int(payload["rpe_effort"]) if payload["rpe_effort"] else None
                    )
                if "weather_or_notes" in payload:
                    wjson["metadata"]["user_context"]["weather_or_notes"] = payload["weather_or_notes"]

                new_id = self.db.save_workout(wjson)
                self._send_json({"ok": True, "workout_id": new_id, "workout_json": wjson})
                return

            if path == "/api/analyze_ai":
                wid = payload.get("workout_id")
                force = bool(payload.get("force", False))
                existing = self.db.get_workout(wid, include_timeseries=False) if wid else None
                if not existing:
                    self._send_json({"error": "Treino não encontrado no banco."}, HTTPStatus.NOT_FOUND)
                    return

                report_md = self.coach.analyze_workout(
                    existing["workout_json"],
                    save_to_db=True,
                    force_regenerate=force,
                )
                self._send_json(
                    {
                        "ok": True,
                        "workout_id": wid,
                        "ai_report_md": report_md,
                        "model_used": self.coach.last_model_used,
                        "tools_called": self.coach.last_tools_called,
                        "call_metadata": self.coach.last_call_metadata,
                    }
                )
                return

            if path == "/api/analyze_ai_stream":
                wid = payload.get("workout_id")
                force = bool(payload.get("force", False))
                existing = self.db.get_workout(wid, include_timeseries=False) if wid else None
                if not existing:
                    self._send_json({"error": "Treino não encontrado no banco."}, HTTPStatus.NOT_FOUND)
                    return

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Connection", "close")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                self.close_connection = True

                try:
                    for event in self.coach.analyze_workout_stream(
                        existing["workout_json"],
                        save_to_db=True,
                        force_regenerate=force,
                    ):
                        sse_line = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
                        self.wfile.write(sse_line)
                        self.wfile.flush()
                except Exception as stream_exc:
                    traceback.print_exc()
                    err_event = {"type": "error", "error": str(stream_exc)}
                    self.wfile.write(f"data: {json.dumps(err_event, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                return

            if path == "/api/chat_ai":
                question = payload.get("question", "").strip()
                wid = payload.get("workout_id")
                history = payload.get("chat_history", [])
                if not question:
                    self._send_json({"error": "Pergunta vazia."}, HTTPStatus.BAD_REQUEST)
                    return

                current_wjson: Optional[Dict[str, Any]] = None
                if wid:
                    existing = self.db.get_workout(wid, include_timeseries=False)
                    if existing:
                        current_wjson = existing["workout_json"]

                answer_md = self.coach.chat_about_workouts(
                    user_question=question,
                    current_workout_json=current_wjson,
                    chat_history=history,
                )
                self._send_json(
                    {
                        "ok": True,
                        "answer_md": answer_md,
                        "model_used": self.coach.last_model_used,
                        "tools_called": self.coach.last_tools_called,
                        "call_metadata": self.coach.last_call_metadata,
                    }
                )
                return

            self._send_json({"error": f"Rota POST desconhecida: {path}"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            traceback.print_exc()
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _serve_static(self, url_path: str) -> None:
        if url_path in ("/", ""):
            file_path = WEB_DIR / "index.html"
        else:
            clean_rel = url_path.lstrip("/")
            file_path = (WEB_DIR / clean_rel).resolve()
            if not str(file_path).startswith(str(WEB_DIR.resolve())):
                self._send_json({"error": "Acesso negado."}, HTTPStatus.FORBIDDEN)
                return

        if not file_path.exists() or not file_path.is_file():
            self._send_json({"error": f"Arquivo não encontrado: {url_path}"}, HTTPStatus.NOT_FOUND)
            return

        mime_type, _ = mimetypes.guess_type(str(file_path))
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime_type or 'text/plain'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def run_server(host: str = "127.0.0.1", port: int = 8501) -> None:
    db = MetricsDatabase()
    ensure_initial_seed(db)
    server = ThreadingHTTPServer((host, port), DashboardRequestHandler)
    print("=" * 72)
    print("🏃 Running Metrics Analyzer — Amazfit Active 2 Dashboard")
    print(f"🌐 Acesse no navegador: http://{host}:{port}")
    print("=" * 72)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor...")
        server.server_close()


if __name__ == "__main__":
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 8501
    run_server(port=port_arg)
