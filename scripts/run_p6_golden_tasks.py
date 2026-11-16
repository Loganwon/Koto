"""Run the executable P6 golden task corpus by surface or priority."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "tests" / "golden" / "p6_real_tasks.json"


def load_cases() -> list[dict]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))["cases"]


def select_cases(*, surface: str = "", priority: str = "") -> list[dict]:
    cases = load_cases()
    if surface:
        cases = [case for case in cases if case["surface"] == surface]
    if priority:
        cases = [case for case in cases if case["priority"] == priority]
    return cases


def node_ids(cases: list[dict]) -> list[str]:
    return list(dict.fromkeys(node for case in cases for node in case["node_ids"]))


def build_command(cases: list[dict], pytest_args: list[str]) -> list[str]:
    return [sys.executable, "-m", "pytest", *node_ids(cases), *pytest_args]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", choices=["startup", "docx", "pdf", "xlsx", "pptx", "addon", "workspace"])
    parser.add_argument("--priority", choices=["P0", "P1"])
    parser.add_argument("--list", action="store_true", help="List selected cases without running pytest")
    args, pytest_args = parser.parse_known_args()
    cases = select_cases(surface=args.surface or "", priority=args.priority or "")
    if not cases:
        parser.error("no golden cases matched the requested filters")
    if args.list:
        for case in cases:
            print(f"{case['id']}\t{case['priority']}\t{case['surface']}\t{case['real_task']}")
        return 0
    return subprocess.call(build_command(cases, pytest_args), cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
