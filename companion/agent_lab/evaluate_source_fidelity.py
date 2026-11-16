"""Opt-in real-model, balanced source-faithfulness probes; never native-host QA."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time

from companion.config import config_from_key_file
from .planning_model import PlanningModel
from .fixed_acceptance import review
from .source_grounding import CHECKS

CASES = [
    (
        "unsupported_unit",
        "设备数量4，单价13.75元。未提供计量单位。",
        "设备4套，单价13.75元。",
        False,
        [],
    ),
    (
        "future_as_done",
        "海岚：计划于2027年开展六个站点的试点，当前尚未开始。",
        "海岚已完成六个站点试点。",
        False,
        [],
    ),
    (
        "reversed_view",
        "访谈者认为，产品乙在证据追溯方面明显优于产品甲。",
        "访谈者认为产品甲在证据追溯方面明显优于产品乙。",
        False,
        [],
    ),
    (
        "mismatched_amount_unit",
        "本季度营收67万元，未经审计。",
        "本季度营收67亿元，未经审计。",
        False,
        [],
    ),
    (
        "explicit_unknown_unit",
        "设备数量4，单价13.75元。未提供计量单位。",
        "设备数量4，计量单位未注明；单价13.75元。",
        True,
        [],
    ),
    (
        "clearly_derived_total",
        "数量4，单价13.75元。",
        "本稿计算：4×13.75元=55元。",
        True,
        [],
    ),
    (
        "qualified_plan",
        "海岚：计划于2027年开展六个站点的试点，当前尚未开始。",
        "海岚计划2027年试点六个站点，目前尚未开始。",
        True,
        [],
    ),
    (
        "user_assigned_owner",
        "项目负责人尚未确定。",
        "负责人=Noor（本次用户指定）。",
        True,
        [{"turn": 4, "mode": "auto", "message": "本次指定负责人=Noor，请写入。"}],
    ),
]


def run(config, case, windowed):
    name, source, text, expected, requests = case
    events = []
    started = time.monotonic()
    result, error = None, None
    try:
        result = review(
            PlanningModel(config),
            SimpleNamespace(cancelled=threading.Event()),
            {
                "file_name": "来源核验.docx",
                "actual_content": text,
                "document_context": text,
                "fixed_checks": CHECKS,
                "claim_ledger_required": True,
                "claim_windowed_review": windowed,
                "human_requests": requests,
                "source_evidence": {
                    "references": [
                        {
                            "file_id": "独立资料.txt",
                            "sha256": "probe",
                            "snapshot_version": "probe-v1",
                            "role": "reference",
                            "text": source,
                        }
                    ],
                    "computed_facts": [],
                },
            },
            record=events.append,
        )
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
    actual = result.get("allowed") if result else None
    return {
        "case": name,
        "windowed": windowed,
        "expected_allowed": expected,
        "actual_allowed": actual,
        "passed": error is None and actual is expected,
        "seconds": round(time.monotonic() - started, 3),
        "error": error,
        "source": source,
        "actual_content": text,
        "decision": result,
        "events": events,
        "real_model": True,
        "native_host": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api-key-file", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--variants",
        nargs="+",
        choices=["previous", "windowed"],
        default=["previous", "windowed"],
    )
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    config = config_from_key_file(args.api_key_file)
    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [
            pool.submit(run, config, c, v == "windowed")
            for v in args.variants
            for c in CASES
        ]
        for future in as_completed(pending):
            row = future.result()
            results.append(row)
            (args.output / "results.json").write_text(
                json.dumps(
                    {
                        "model": config.model,
                        "real_model": True,
                        "native_host": False,
                        "results": results,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in row.items()
                        if k not in ["source", "actual_content", "decision", "events"]
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
