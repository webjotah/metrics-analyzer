"""Script de linha de comando (CLI) para testar tudo o que foi feito até o Passo 3.

Como usar no terminal:
  python3 test_ai.py                                 # Analisa o Intervalado.fit por padrão
  python3 test_ai.py fit-archive-example/10km.fit    # Analisa os 10km
  python3 test_ai.py fit-archive-example/5km.fit     # Analisa os 5km
  python3 test_ai.py --ask "Qual foi minha evolução entre os treinos?"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.ai_coach import GeminiCoach
from src.database import MetricsDatabase


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Testa o extrator .FIT, o banco SQLite e o Treinador IA (Google Gemini)."
    )
    parser.add_argument(
        "fit_file",
        nargs="?",
        default="fit-archive-example/Intervalado.fit",
        help="Caminho para o arquivo .FIT a ser analisado (padrão: fit-archive-example/Intervalado.fit)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Força uma nova chamada à API do Gemini mesmo que o relatório já esteja salvo no banco SQLite.",
    )
    parser.add_argument(
        "--ask",
        type=str,
        default=None,
        help="Faz uma pergunta direta ao Treinador IA consultando o banco SQLite.",
    )
    args = parser.parse_args()

    db = MetricsDatabase()

    # Garante que os 3 arquivos de exemplo já estejam populados no banco para a IA ter histórico para consultar
    for sample in ["5km.fit", "10km.fit", "Intervalado.fit"]:
        sample_path = Path("fit-archive-example") / sample
        if sample_path.exists():
            db.import_fit_file(sample_path)

    coach = GeminiCoach(db=db)
    if not coach.is_configured():
        print("❌ ERRO: GEMINI_API_KEY não configurada no arquivo .env!")
        sys.exit(1)

    print(f"✅ Configuração carregada do .env | Modelo Principal: {coach.model} (Fallback: {coach.fallback_model})")
    print(f"📂 Total de treinos salvos no banco SQLite (data/runs.db): {len(db.list_workouts_summary())}")

    fit_path = Path(args.fit_file)
    if not fit_path.exists():
        print(f"❌ Arquivo não encontrado: {fit_path}")
        sys.exit(1)

    wjson = db.import_fit_file(fit_path)
    print(
        f"🏃 Treino carregado: {wjson['workout_id']} | "
        f"Tipo: {wjson['metadata']['workout_type_confirmed']} | "
        f"Distância: {wjson['summary']['total_distance_km']} km | "
        f"Pace: {wjson['summary']['avg_pace_min_km']}/km | "
        f"FC: {wjson['physiology']['avg_hr_bpm']} bpm"
    )

    if args.ask:
        print(f"\n💬 Enviando pergunta para o Gemini ({coach.model})...")
        answer = coach.chat_about_workouts(args.ask, current_workout_json=wjson)
        print(f"🛠️  Tools do SQLite chamadas pela IA: {coach.last_tools_called}")
        print(f"🤖 Modelo utilizado: {coach.last_model_used}\n")
        print("=" * 80)
        print(answer)
        print("=" * 80)
    else:
        print(f"\n🧠 Gerando análise completa do treino com o Gemini ({coach.model})...")
        print("   (O modelo Pro pode levar de 10 a 25 segundos consultando o banco e raciocinando...)")
        report = coach.analyze_workout(wjson, save_to_db=True, force_regenerate=args.force)
        if coach.last_tools_called:
            print(f"🛠️  Tools do SQLite chamadas pela IA: {coach.last_tools_called}")
        if coach.last_model_used:
            print(f"🤖 Modelo utilizado: {coach.last_model_used}")
        else:
            print("⚡ Relatório carregado instantaneamente do cache do SQLite (use --force para regerar na API)")
        print("\n" + "=" * 80)
        print(report)
        print("=" * 80)


if __name__ == "__main__":
    main()
