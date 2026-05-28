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

    review_dir_parser = subparsers.add_parser("review-dir", help="Review all session JSON files in a directory")
    review_dir_parser.add_argument("sessions_dir", type=Path)
    review_dir_parser.add_argument("--output", "-o", type=Path, required=True)

    args = parser.parse_args()

    if args.command == "review":
        review_file(args.session_file)
    elif args.command == "review-dir":
        review_dir(args.sessions_dir, args.output)


def review_file(session_file: Path) -> None:
    result = ReviewEngine().review_file(session_file)
    print(json.dumps(review_result_to_dict(result), indent=2))


def review_dir(sessions_dir: Path, output: Path) -> None:
    engine = ReviewEngine()
    session_files = sorted(sessions_dir.glob("*.json"))

    with output.open("w", encoding="utf-8") as file:
        for session_file in session_files:
            result = engine.review_file(session_file)
            file.write(json.dumps(review_result_to_dict(result)) + "\n")

    print(f"Wrote {len(session_files)} predictions to {output}")

if __name__ == "__main__":
    main()
