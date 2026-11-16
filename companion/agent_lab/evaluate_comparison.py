"""Matched local Office-tool benchmark, explicitly separate from native host QA.

Each variant runs in a separate process. The upstream reference is an ablation
over the same capability tools, not a claim about all Deep Agents/OpenHands tasks.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time

from companion.config import config_from_key_file

VARIANTS = ("koto-deepagents", "koto-pi", "upstream-deepagents")
CASES = ("reconcile_1200", "multi_file_feedback")


def session(folder, variant, config, goal=None, outputs=(), task=None):
    from .cli import open_session

    if variant != "upstream-deepagents":
        return open_session(
            folder,
            variant.removeprefix("koto-"),
            config,
            goal=goal,
            expected_outputs=outputs,
            task=task,
        )
    from .store import TaskStore
    from .tools import ToolBroker, JsonDocument
    from .runtime import LabSession
    from companion.tests.reference_deepagents import ReferenceDeepAgents

    store = TaskStore(folder / "tasks.sqlite3")
    if task is None:
        task = store.create(goal, expected_outputs=outputs)
    document = JsonDocument(
        folder / "document.json", ["甲方将在全部验收完成之后再进行付款。"]
    )
    broker = ToolBroker(
        store,
        task,
        folder / "references",
        folder / "outputs",
        document,
        lambda turn, tool, args, state: {"allowed": True},
    )
    return LabSession(
        store, task, broker, ReferenceDeepAgents(config, folder / "checkpoints.sqlite3")
    )


def run(root, variant, case, key_file):
    import openpyxl
    from docx import Document
    from pptx import Presentation

    folder = root / variant / case
    refs = folder / "references"
    refs.mkdir(parents=True, exist_ok=False)
    config = config_from_key_file(key_file)
    checks = {}
    runs = []
    error = None
    s = None
    started = time.monotonic()

    def send(text, **kwargs):
        result = s.send(text, **kwargs)
        runs.append(result)
        return result

    def hashes():
        return {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in (folder / "outputs").iterdir()
            if p.is_file()
        }

    try:
        if case == "reconcile_1200":
            customers = [
                {"customer": "C01", "region": "华东"},
                {"customer": "C02", "region": "华南"},
                {"customer": "C03", "region": "华北"},
            ]
            (refs / "customers.json").write_text(
                json.dumps(customers, ensure_ascii=False), encoding="utf-8"
            )
            orders = [
                {
                    "id": f"R{i:05}",
                    "customer": f"C{(i%3)+1:02}",
                    "status": "cancelled" if i % 11 == 0 else "complete",
                    "amount_yuan": str(Decimal(i * 127 + 31) / 100),
                }
                for i in range(1, 1201)
            ]
            bad = [
                {
                    "id": "BAD1",
                    "customer": "C99",
                    "status": "complete",
                    "amount_yuan": "88.00",
                },
                {
                    "id": "BAD2",
                    "customer": "C01",
                    "status": "complete",
                    "amount_yuan": "待定",
                },
            ]
            with (refs / "orders.csv").open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["id", "customer", "status", "amount_yuan"]
                )
                writer.writeheader()
                writer.writerows(orders + orders[::17] + bad)
            (refs / "policy.txt").write_text(
                "amount_yuan是人民币元；相同id重复行为重复记录只计一次。只计complete状态，cancelled排除；金额不可解析或客户不在主表的记录单列异常，不纳入地区汇总。",
                encoding="utf-8",
            )
            goal = "联合orders.csv、customers.json和policy.txt做去重对账。生成对账.xlsx，仅两个工作表：汇总（地区、订单数、金额）和异常（id、原因）。完整处理所有输入，不是只用预览；金额保持数值、按人民币元保留两位小数。只纳入complete且客户存在、金额可解析的订单；id去重。不得修改当前正文。完成并回读核对。"
            s = session(folder, variant, config, goal, ("对账.xlsx",))
            send(goal)
            expected = {}
            for row in orders:
                if row["status"] == "complete":
                    region = customers[int(row["customer"][-1]) - 1]["region"]
                    v = expected.setdefault(region, [0, Decimal(0)])
                    v[0] += 1
                    v[1] += Decimal(row["amount_yuan"])
            path = folder / "outputs/对账.xlsx"
            checks["actual_workbook"] = path.exists()
            if path.exists():
                wb = openpyxl.load_workbook(path)
                checks["exact_sheets"] = wb.sheetnames == ["汇总", "异常"]
                if "汇总" in wb:
                    checks["exact_columns"] = list(next(wb["汇总"].values)) == [
                        "地区",
                        "订单数",
                        "金额",
                    ] and list(next(wb["异常"].values)) == ["id", "原因"]
                    actual = {
                        r[0]: r[1:3]
                        for r in wb["汇总"].values
                        if r and r[0] in expected
                    }
                    checks["all_1200_rows_join_dedup_sum"] = set(actual) == set(
                        expected
                    ) and all(
                        actual[k][0] == v[0]
                        and isinstance(actual[k][1], (int, float))
                        and abs(Decimal(str(actual[k][1])) - v[1]) < Decimal(".005")
                        for k, v in expected.items()
                    )
                    checks["numeric_two_decimal_display"] = all(
                        wb["汇总"].cell(i, 3).number_format in {"0.00", "#,##0.00"}
                        for i in range(2, wb["汇总"].max_row + 1)
                    )
                if "异常" in wb:
                    checks["both_anomalies"] = all(
                        x in str(list(wb["异常"].values)) for x in ["BAD1", "BAD2"]
                    )
                wb.close()
        else:
            facts = {
                "项目": "海岚",
                "营收万元": 387.26,
                "同比": "13.4%",
                "限定": "示例且未经审计",
                "节点": "2027-03-19",
                "数量": 7,
                "单价元": 14.35,
                "计量单位": None,
            }
            (refs / "facts.json").write_text(
                json.dumps(facts, ensure_ascii=False), encoding="utf-8"
            )
            goal = "依据facts.json连续生成摘要.docx（正文不超过220字）、核对.xlsx（一个叫核对的工作表）、简报.pptx（2页）。保留项目、营收同比、示例且未经审计限定及节点；采购数量乘单价按元核算，金额为数值。数量计量单位没有给出，不能猜成件、项或套；把缺失标为待确认。不要修改当前正文。全部完成后结束。"
            outputs = ("摘要.docx", "核对.xlsx", "简报.pptx")
            s = session(folder, variant, config, goal, outputs)
            send(goal)
            before = hashes()
            checks["three_real_deliveries"] = set(before) == set(outputs)
            send(
                "仅回答刚才的采购合计是多少，说明计量单位是否明确；本轮不修改任何文件。",
                mode="read",
            )
            checks["readonly_does_not_write"] = hashes() == before
            task = s.task
            s.close()
            s.store.close()
            s = None
            s = session(folder, variant, config, task=task)
            send(
                "继续同一任务：只把摘要.docx和简报.pptx加入准确文字负责人=Noor，保留其他事实及原有页数。核对.xlsx不动，不生成副本；回读核对后结束。",
                interaction="continue",
            )
            after = hashes()
            checks["same_outputs_no_duplicates"] = set(after) == set(outputs)
            checks["unchanged_workbook"] = after.get("核对.xlsx") == before.get(
                "核对.xlsx"
            )
            if (folder / "outputs/摘要.docx").exists():
                text = "\n".join(
                    p.text for p in Document(folder / "outputs/摘要.docx").paragraphs
                )
                checks["word_facts_literal"] = all(
                    v in text
                    for v in [
                        "海岚",
                        "387.26",
                        "13.4",
                        "示例",
                        "未经审计",
                        "2027-03-19",
                        "负责人=Noor",
                    ]
                )
                checks["word_under_limit"] = len(text.replace("\n", "")) <= 240
            if (folder / "outputs/简报.pptx").exists():
                deck = Presentation(folder / "outputs/简报.pptx")
                text = "\n".join(
                    shape.text
                    for slide in deck.slides
                    for shape in slide.shapes
                    if shape.has_text_frame
                )
                checks["slide_count_and_literal"] = (
                    len(deck.slides) == 2 and "负责人=Noor" in text
                )
            if (folder / "outputs/核对.xlsx").exists():
                wb = openpyxl.load_workbook(folder / "outputs/核对.xlsx")
                values = [c.value for sheet in wb for row in sheet for c in row]
                checks["exact_purchase_total"] = any(
                    type(v) in (int, float) and abs(v - 100.45) < 0.000001
                    for v in values
                )
                checks["unknown_unit_visible"] = (
                    "待确认" in str(values)
                    or "未提供" in str(values)
                    or "未注明" in str(values)
                )
                wb.close()
        checks["completion_recorded"] = s.store.get(s.task)["phase"] == "complete"
        checks["native_editor_not_modified"] = s.broker.document.contents() == {
            "0": "甲方将在全部验收完成之后再进行付款。"
        }
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
        checks["no_execution_error"] = False
    events = s.store.events(s.task) if s else []
    result = {
        "variant": variant,
        "case": case,
        "passed": bool(checks) and all(checks.values()),
        "checks": checks,
        "error": error,
        "seconds": round(time.monotonic() - started, 3),
        "real_model": True,
        "native_host": False,
        "runs": runs,
        "events": events,
    }
    if s:
        s.close()
        s.store.close()
    (folder / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("runs", "events")},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api-key-file", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--worker", action="store_true")
    p.add_argument("--variant", choices=VARIANTS)
    p.add_argument("--variants", nargs="+", choices=VARIANTS, default=VARIANTS)
    p.add_argument("--case", choices=CASES)
    args = p.parse_args()
    if args.worker:
        return run(args.output, args.variant, args.case, args.api_key_file)
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "model": "deepseek-chat",
        "temperature": 0,
        "max_model_dispatches_per_turn": 120,
        "max_tools_per_turn": 100,
        "cases": CASES,
        "variants": args.variants,
        "native_host": False,
        "claim": "single-agent Office-tool comparison; not a universal frontier-agent benchmark",
        "comparison_limits": [
            "Deep Agents variants use the same thinking-enabled model profile; Pi execution does not enable provider thinking and its latency is not directly comparable.",
            "Koto has an additional 60 execution-dispatch ceiling; the shared total ceiling includes its compiler and verifier calls.",
            "Resume reconstructs the session against a persistent store; it is not a process-crash test.",
            "The reference has the same bounded Office tools, not unrestricted shell, browser or multi-agent capabilities.",
        ],
    }
    from hashlib import sha256 as digest

    manifest["code_sha256"] = {
        str(f.relative_to(Path(__file__).parents[2])): digest(
            f.read_bytes()
        ).hexdigest()
        for f in [
            *Path(__file__).parent.glob("*.py"),
            Path(__file__).parents[1] / "tests/reference_deepagents.py",
        ]
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    def worker(variant, case):
        command = [
            sys.executable,
            "-m",
            "companion.agent_lab.evaluate_comparison",
            "--worker",
            "--api-key-file",
            args.api_key_file,
            "--output",
            str(args.output),
            "--variant",
            variant,
            "--case",
            case,
        ]
        try:
            child = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", timeout=1500
            )
        except subprocess.TimeoutExpired:
            return {
                "variant": variant,
                "case": case,
                "passed": False,
                "error": "1500s worker wall-clock limit; incomplete task is a failure",
                "seconds": 1500,
                "native_host": False,
            }
        path = args.output / variant / case / "result.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {
            "variant": variant,
            "case": case,
            "passed": False,
            "error": child.stderr[-1500:],
            "exit_code": child.returncode,
            "native_host": False,
        }

    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(worker, v, c) for v in args.variants for c in CASES]
        for job in as_completed(pending):
            row = job.result()
            results.append(row)
            (args.output / "results.json").write_text(
                json.dumps(
                    {"manifest": manifest, "results": results},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {k: v for k, v in row.items() if k not in ("runs", "events")},
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
