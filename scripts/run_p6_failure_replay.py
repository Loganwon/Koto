"""Replay anonymized P6 failures through an allowlisted pytest registry."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.diagnostics.failure_replay import validate_failure_replay_case

REPLAY_TESTS = {
    "startup.local_model_missing": "tests/unit/test_runtime_capabilities.py::test_selected_but_uninstalled_model_is_misconfigured",
    "startup.runtime_incompatible": "tests/unit/test_runtime_capabilities.py::test_runtime_model_version_mismatch_is_incompatible",
    "startup.legacy_upgrade": "tests/unit/test_runtime_capabilities.py::test_legacy_local_model_tag_remains_readable",
    "docx.large_review": "tests/e2e/test_docx_review_ui.py::test_docx_large_review_corpus_stays_within_render_budget",
    "pdf.text_position": "tests/e2e/test_p4_pdf_document_flows.py::test_pdf_annotation_position_survives_zoom_save_render_and_reload",
    "pdf.watermark_cleanup": "tests/e2e/test_p4_pdf_document_flows.py::test_pdf_watermark_cleanup_reports_effect_and_safe_noop",
    "health.ping_liveness": "tests/unit/test_health_endpoint.py::TestPing::test_ping_never_opens_an_ollama_socket",
    "office.corrupt_pptx": "tests/integration/test_pptx_absolute_path_fix.py::TestOpenFilePptx::test_corrupt_pptx_returns_500_not_package_not_found",
}


def load_cases(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("cases"), list):
        raise ValueError(f"{path}: invalid replay corpus")
    cases = payload["cases"]
    for case in cases:
        validate_failure_replay_case(case)
    return cases


def selectors_for_cases(cases: list[dict]) -> list[str]:
    selectors: list[str] = []
    for case in cases:
        selector = REPLAY_TESTS[case["replay_key"]]
        if selector not in selectors:
            selectors.append(selector)
    return selectors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus", type=Path, default=Path("tests/replay/p6_anonymized_failures.json")
    )
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cases = load_cases(args.corpus)
    if args.case:
        wanted = set(args.case)
        cases = [case for case in cases if case["case_id"] in wanted]
        missing = wanted - {case["case_id"] for case in cases}
        if missing:
            raise SystemExit(f"unknown replay case(s): {', '.join(sorted(missing))}")
    if args.list:
        for case in cases:
            print(f"{case['case_id']}\t{case['replay_key']}\t{case['symptom_code']}")
        return 0
    selectors = selectors_for_cases(cases)
    print(f"[p6-replay] {len(cases)} anonymized cases -> {len(selectors)} allowlisted tests")
    if args.dry_run:
        for selector in selectors:
            print(selector)
        return 0
    return subprocess.call(
        [sys.executable, "-m", "pytest", *selectors, "-q", "--tb=short"]
    )


if __name__ == "__main__":
    raise SystemExit(main())
