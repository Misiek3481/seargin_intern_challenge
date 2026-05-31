from __future__ import annotations

import argparse
import json
from pathlib import Path

from sap_ff_reviewer.engine import ReviewEngine
from sap_ff_reviewer.serialization import review_result_to_dict


def main() -> None:
    parser = argparse.ArgumentParser(description="SAP Firefighter Log Compliance Reviewer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review_parser = subparsers.add_parser("review", help="Review a single session JSON file")
    review_parser.add_argument("session_file", type=Path)
    review_parser.add_argument("--use-r002-llm", action="store_true", help="Use Ollama as an R-002 fallback when heuristics pass")
    review_parser.add_argument("--ollama-model", help="Ollama model name for R-002 fallback")

    review_dir_parser = subparsers.add_parser("review-dir", help="Review all session JSON files in a directory")
    review_dir_parser.add_argument("sessions_dir", type=Path)
    review_dir_parser.add_argument("--output", "-o", type=Path, required=True)
    review_dir_parser.add_argument("--use-r002-llm", action="store_true", help="Use Ollama as an R-002 fallback when heuristics pass")
    review_dir_parser.add_argument("--ollama-model", help="Ollama model name for R-002 fallback")

    args = parser.parse_args()

    if args.command == "review":
        review_file(args.session_file, use_r002_llm=args.use_r002_llm, ollama_model=args.ollama_model)
    elif args.command == "review-dir":
        review_dir(args.sessions_dir, args.output, use_r002_llm=args.use_r002_llm, ollama_model=args.ollama_model)


def review_file(session_file: Path, use_r002_llm: bool = False, ollama_model: str | None = None) -> None:
    result = ReviewEngine(use_r002_llm=use_r002_llm, ollama_model=ollama_model).review_file(session_file)
    print(json.dumps(review_result_to_dict(result), indent=2))


def review_dir(sessions_dir: Path, output: Path, use_r002_llm: bool = False, ollama_model: str | None = None) -> None:
    engine = ReviewEngine(use_r002_llm=use_r002_llm, ollama_model=ollama_model)
    session_files = sorted(sessions_dir.glob("*.json"))

    with output.open("w", encoding="utf-8") as file:
        for session_file in session_files:
            result = engine.review_file(session_file)
            file.write(json.dumps(review_result_to_dict(result)) + "\n")

    print(f"Wrote {len(session_files)} predictions to {output}")

if __name__ == "__main__":
    main()
