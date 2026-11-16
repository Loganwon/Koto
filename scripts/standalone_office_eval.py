"""Evaluate 24 office tasks against real tools and independently reopened files.

Fixture results measure engineering behavior under a scripted model; they are
explicitly not live model quality or browser end-to-end success rates.
"""

from __future__ import annotations

import argparse
import copy
import csv
from contextlib import ExitStack
import io
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.office_task_cases import fixed_cases
from scripts.office_task_scoring import artifact_snapshot, document_text, score_case
from scripts.standalone_acceptance import configure_isolation


class InterruptedAfterCommit(BaseException):
    pass


def create_office_fixtures(folder):
    """Only public synthetic materials; every run owns a new directory."""
    from docx import Document
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from pptx import Presentation

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "source.txt").write_text("季度营收240万元，同比增长20%。\n来源口径：截至2026-12-31。\n", encoding="utf-8")
    (folder / "sales.csv").write_bytes("部门,金额(万元)\n产品,120\n运营,80\n市场,40\n".encode("utf-8"))
    (folder / "edit.txt").write_bytes("标题保持不变\r\n我们希望通过这个项目，把团队的工作效率进行一个全面的提升。\r\n第二段保持不变。\r\n".encode("utf-8"))
    (folder / "duplicate.txt").write_text("第一项：待确认，120万元\n第二项：待确认，80万元\n", encoding="utf-8", newline="")
    doc = Document()
    doc.add_heading("季度办公简报", level=1)
    paragraph = doc.add_paragraph()
    paragraph.add_run("季度营收240万元，同比增长20%。").bold = True
    doc.add_paragraph("第二段保持不变。")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "合同编号", "KT-2026-12"
    doc.sections[0].header.paragraphs[0].text = "固定办公任务样例"
    doc.save(folder / "brief.docx")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    for row in [["部门", "金额(万元)"], ["产品", 120], ["运营", 80], ["市场", 40], ["合计", "=SUM(B2:B4)"]]:
        sheet.append(row)
    sheet["B2"].fill = PatternFill("solid", fgColor="DDEEFF")
    sheet["B2"].font = Font(bold=True)
    sheet["B2"].number_format = "0.00"
    workbook.save(folder / "budget.xlsx")
    workbook.close()
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "项目里程碑"
    slide.placeholders[1].text = "截止日：2026-12-31\n市场预算40万元"
    deck.save(folder / "milestones.pptx")


def unwrap(value):
    for _ in range(5):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                return value
            if isinstance(parsed, str) and parsed == value:
                return value
            value = parsed
        elif isinstance(value, dict) and "value" in value:
            value = value["value"]
        else:
            break
    return value


def tool_observations(messages):
    return [unwrap(message.get("content", "")) for message in messages if message.get("role") == "tool"]


class ScriptedModel:
    """A bounded ideal-model fixture; no oracle writes files outside tools."""

    def __init__(self, phase, folder):
        self.phase, self.folder = phase, Path(folder)
        self.index, self.calls, self.require_recovered_tool = 0, [], False

    def _resolve(self, value, observed):
        if isinstance(value, str):
            return value.replace("$ROOT", str(self.folder)).replace("$OBSERVED", observed)
        if isinstance(value, list):
            return [self._resolve(item, observed) for item in value]
        if isinstance(value, dict):
            return {key: self._resolve(item, observed) for key, item in value.items()}
        return value

    def __call__(self, **kwargs):
        messages = kwargs["messages"]
        observations = tool_observations(messages)
        if self.require_recovered_tool and not observations:
            raise RuntimeError("Restored run did not carry its actual tool receipt")
        observed = "\n".join(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
                             for item in observations)
        call = {"message_count": len(messages), "tools_available": len(kwargs.get("tools") or []), "usage": None}
        self.calls.append(call)
        if self.index < len(self.phase["steps"]):
            step = self.phase["steps"][self.index]
            self.index += 1
            call["tool"] = step["name"]
            return {"content": "执行显式办公任务步骤。", "tool_calls": [{
                "id": f"office-step-{self.index}", "name": step["name"],
                "args": self._resolve(step["args"], observed),
            }]}
        if self.phase["answer"] == "csv_sum":
            rows = list(csv.reader(io.StringIO(str(observations[-1] if observations else ""))))
            total = sum(float(row[-1]) for row in rows[1:] if row and row[-1].replace(".", "", 1).isdigit())
            answer = f"sales.csv预算合计{total:g}万元。"
        elif self.phase["answer"] == "xlsx_sum":
            data = observations[-1] if observations else {}
            total = sum(float(row[-1]) for row in data.get("rows", [])
                        if row and isinstance(row[-1], (int, float))) if isinstance(data, dict) else 0
            answer = f"budget.xlsx预算合计{total:g}万元。"
        elif self.phase["mode"] == "answer":
            answer = "已读取来源：" + "、".join(self.phase["inputs"]) + "\n" + observed
        else:
            answer = "已完成已验证的文件工具调用。" if observations else "未获得写入回执。"
        return {"content": answer, "tool_calls": []}

    def stream_call(self, **kwargs):
        """Exercise the real delta/final boundary without inventing token usage."""
        response = self(**kwargs)
        self.calls[-1]["stream"] = True
        text = str(response.get("content") or "")
        accumulated = ""
        for start in range(0, len(text), 32):
            cancel = kwargs.get("cancel_check")
            if callable(cancel) and cancel():
                raise RuntimeError("Fixture stream cancelled")
            piece = text[start:start + 32]
            accumulated += piece
            yield {"delta": piece, "content": accumulated, "tool_calls": []}
        yield {"delta": "", "content": accumulated, "tool_calls": response.get("tool_calls", []),
               "stream_final": True, "usage": None}


def event_record(event):
    return {"type": event.type, "payload": dict(event.payload),
            **{name: getattr(event, name) for name in ("task_id", "run_id", "step_id", "event_id", "seq")
               if getattr(event, name, None) is not None}}


def run_phase(case, phase, folder, ledger_dir, *, ordinal, capture=None):
    from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
    from app.core.agent.file_task_runtime import FileTaskRuntime
    from app.core.tasks.task_ledger import TaskLedger

    folder, ledger_dir = Path(folder), Path(ledger_dir)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = TaskLedger(db_path=str(ledger_dir / f"phase-{ordinal}.sqlite"))
    task = ledger.create(session_id=f"office-{case['id']}", user_input=phase["prompt"], source="file_task")
    model = ScriptedModel(phase, folder)
    if capture is not None:
        capture["calls"] = model.calls
    files = [FileTaskFile(path=str(folder / name), name=name, type=Path(name).suffix.lstrip("."),
                         target=name == phase["target"],
                         content=document_text(folder / name) if (folder / name).is_file() else "")
             for name in phase["inputs"]]
    options = {"output_mode": phase["mode"], "allow_local_fallback": False}
    saved = []

    def interrupt(state):
        if state["phase"] == "tool_complete" and not saved:
            saved.append(copy.deepcopy(state))
            raise InterruptedAfterCommit()

    if case["fault"] == "checkpoint_resume":
        options["_checkpoint_callback"] = interrupt
    request = FileTaskRequest(
        task=phase["prompt"], task_id=task.task_id, run_id=f"office-{case['id']}-{ordinal}",
        session_id=f"office-{case['id']}", target_path=str(folder / phase["target"]) if phase["target"] else "",
        files=files, options=options,
    )
    events, resumed = [], False
    if capture is not None:
        capture["events"] = events
    with ExitStack() as stack:
        stack.enter_context(patch("app.core.tasks.task_ledger.get_ledger", return_value=ledger))
        if case["fault"] == "save_failure":
            stack.enter_context(patch("app.core.agent.tools.docx_write._save_docx_via_temp_file",
                                      side_effect=PermissionError("Office evaluation fixture: persistence unavailable")))
        # Receipts use paths relative to the configured workspace, as in the
        # production transport. A case is a child folder, not a different root.
        runtime = FileTaskRuntime(workspace_root=str(folder.parent), model_client=model, max_rounds=3)
        try:
            for event in runtime.run(request):
                events.append(event_record(event))
        except InterruptedAfterCommit:
            checkpoint = ledger.get_kernel_checkpoint(task.task_id, request.run_id)
            if checkpoint is None:
                raise RuntimeError("Committed task did not leave a durable checkpoint") from None
            ledger.release_kernel_checkpoint(task.task_id, request.run_id, checkpoint["owner_id"])
            claimed = ledger.claim_kernel_checkpoint(task.task_id, "office-resume-worker", run_id=request.run_id)
            if claimed is None:
                raise RuntimeError("Durable checkpoint could not be claimed")
            state = claimed["state"]
            restored = FileTaskRequest.from_mapping(state["file_task_request"])
            restored.options.update(_kernel_resume_state=state, _checkpoint_owner="office-resume-worker")
            model.require_recovered_tool = True
            for event in runtime.run(restored):
                events.append(event_record(event))
            resumed = True
    return events, model.calls, resumed


def metrics_from_events(events):
    metrics = [event["payload"] for event in events if event["type"] == "model.metrics"]
    actual = []
    for item in metrics:
        usage = item.get("usage") or item.get("actual_usage")
        if isinstance(usage, dict) and usage.get("provider_reported") is True:
            counts = {name: value for name, value in usage.items()
                      if name in {"input_tokens", "output_tokens", "total_tokens", "cached_input_tokens"}
                      and isinstance(value, (int, float)) and not isinstance(value, bool)}
            if counts:
                actual.append({"provider_reported": True, **counts})
    first_text = [item["first_text_ms"] for item in metrics
                  if isinstance(item.get("first_text_ms"), (int, float))]
    return {"turn_metrics": metrics, "actual_usage": actual,
            "model_turns_recorded": len(metrics),
            "first_text_p50_ms": statistics.median(first_text) if first_text else None,
            "token_usage_available": bool(actual),
            "token_usage_complete": bool(metrics) and len(actual) == len(metrics)}


def run_case(case, folder, ledger_dir):
    artifact_dir = Path(ledger_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    create_office_fixtures(folder)
    before = artifact_snapshot(folder)
    (artifact_dir / "before.json").write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
    events, calls, resumed, exception = [], [], False, None
    start = time.monotonic()
    try:
        for ordinal, phase in enumerate(case["phases"], start=1):
            partial = {}
            try:
                phase_events, phase_calls, did_resume = run_phase(case, phase, folder, ledger_dir,
                                                                 ordinal=ordinal, capture=partial)
            except Exception:
                events.extend(partial.get("events", []))
                calls.extend(partial.get("calls", []))
                raise
            events.extend(phase_events)
            calls.extend(phase_calls)
            resumed = resumed or did_resume
    except Exception as exc:
        exception = type(exc).__name__
    elapsed = time.monotonic() - start
    score = score_case(case, folder, before, events, resumed=resumed)
    if exception:
        score["passed"] = False
        score["checks"].append({"kind": "runtime_exception", "passed": False, "reason": exception})
        score["score"] = sum(check["passed"] for check in score["checks"]) / len(score["checks"])
    details = {"case_id": case["id"], "group": case["group"], "title": case["title"],
               "provider_kind": "deterministic_fixture", "elapsed_seconds": round(elapsed, 6),
               "model_calls": len(calls), "tool_calls": sum(event["type"] == "tool.started" for event in events),
               "actual_provider_tokens": None, "resumed": resumed, **score, **metrics_from_events(events)}
    (artifact_dir / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "result.json").write_text(json.dumps(details, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return details


def summarize(records, repeats):
    groups = {}
    for group in sorted({row["group"] for row in records}):
        selected = [row for row in records if row["group"] == group]
        groups[group] = {"attempted": len(selected), "passed": sum(row["passed"] for row in selected),
                         "success_rate": sum(row["passed"] for row in selected) / len(selected)}
    elapsed = sorted(row["elapsed_seconds"] for row in records)
    first_text = [turn["first_text_ms"] for row in records for turn in row["turn_metrics"]
                  if isinstance(turn.get("first_text_ms"), (int, float))]
    return {"evaluation_kind": "scripted-model engineering office-task evaluation",
            "not_a_live_model_quality_score": True, "browser_verified": False,
            "fixed_case_count": len({row["case_id"] for row in records}), "repeats": repeats,
            "attempted": len(records), "passed": sum(row["passed"] for row in records),
            "success_rate": sum(row["passed"] for row in records) / max(1, len(records)),
            "elapsed_p50_seconds": statistics.median(elapsed) if elapsed else None,
            "elapsed_p95_seconds": elapsed[min(len(elapsed) - 1, int(len(elapsed) * .95))] if elapsed else None,
            "total_task_seconds": sum(elapsed), "model_calls": sum(row["model_calls"] for row in records),
            "tool_calls": sum(row["tool_calls"] for row in records), "actual_provider_tokens": None,
            "model_turns_recorded": sum(row["model_turns_recorded"] for row in records),
            "first_text_p50_ms": statistics.median(first_text) if first_text else None,
            "token_usage_note": "Fixture has no provider-billed tokens; missing usage stays null.",
            "groups": groups, "records": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cases", default="")
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--live-probe-report", type=Path, help="Attach an existing sanitized report; never issues a live request")
    args = parser.parse_args()
    cases = fixed_cases()
    if args.cases:
        selected = set(args.cases.split(","))
        cases = [case for case in cases if case["id"] in selected]
        if {case["id"] for case in cases} != selected:
            parser.error("Unknown office-task case id")
    if args.list_cases:
        print(json.dumps(cases, ensure_ascii=False, indent=2))
        return
    if args.repeats < 1 or args.repeats > 10:
        parser.error("Repeats must be between 1 and 10")
    state = args.state_dir.resolve()
    if (state / "evaluation.json").exists():
        parser.error("Choose a fresh state directory; existing evaluation evidence is preserved")
    from build_config import cython_build_input_snapshot

    initial_sources = cython_build_input_snapshot(ROOT)
    harness_names = ("office_task_cases.py", "office_task_scoring.py", "standalone_office_eval.py")
    initial_harness = {name: hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
                       for name in harness_names}
    workspace = configure_isolation(state)
    (state / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    records = []
    for repeat in range(1, args.repeats + 1):
        for case in cases:
            name = f"r{repeat:02}-{case['id']}"
            result = run_case(case, workspace / name, state / "results" / name)
            result["repeat"] = repeat
            records.append(result)
            print(json.dumps({key: result[key] for key in ("case_id", "repeat", "passed", "elapsed_seconds", "model_calls", "tool_calls")}), flush=True)
    summary = summarize(records, args.repeats)
    final_sources = cython_build_input_snapshot(ROOT)
    summary["source_changed_during_run"] = initial_sources != final_sources
    summary["production_source_snapshot_sha256"] = hashlib.sha256(json.dumps(
        initial_sources, sort_keys=True,
    ).encode("utf-8")).hexdigest()
    summary["task_prompts_sha256"] = hashlib.sha256(json.dumps(
        [(case["id"], [phase["prompt"] for phase in case["phases"]]) for case in cases],
        ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")).hexdigest()
    final_harness = {
        name: hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
        for name in harness_names
    }
    summary["harness_source_sha256"] = initial_harness
    summary["harness_changed_during_run"] = initial_harness != final_harness
    summary["valid_source_snapshot"] = not (summary["source_changed_during_run"] or summary["harness_changed_during_run"])
    if args.live_probe_report:
        probe = json.loads(args.live_probe_report.read_text(encoding="utf-8"))
        allowed = {"status", "provider_type", "model", "host", "requests_attempted", "output_token_cap",
                   "request_timeout_seconds", "elapsed_seconds", "actual_usage", "provider_charge_usd",
                   "error_types", "os_error_numbers", "live_task_attempts", "live_group_action"}
        summary["live_probe"] = {key: value for key, value in probe.items() if key in allowed}
    (state / "evaluation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Koto 固定办公任务评估", "", "本报告使用脚本模型，评估生产工具与文件持久化的工程行为，不代表真实模型质量或浏览器成功率。", "",
             f"固定任务：{summary['fixed_case_count']}；重复次数：{args.repeats}；通过：{summary['passed']}/{summary['attempted']}（{summary['success_rate']:.1%}）。",
             f"任务耗时 p50={summary['elapsed_p50_seconds']:.3f}s，p95={summary['elapsed_p95_seconds']:.3f}s；模型调用{summary['model_calls']}，工具调用{summary['tool_calls']}。", "",
             "provider实际token：不可得（fixture，无计费用量）；未估算真实模型花费。", "", "| 类别 | 通过 | 尝试 | 通过率 |", "|---|---:|---:|---:|"]
    if not summary["valid_source_snapshot"]:
        lines[4:4] = ["**运行期间生产或验收源码发生变化；本次记录不可作为最终冻结版本的验收。**", ""]
    for group, values in summary["groups"].items():
        lines.append(f"| {group} | {values['passed']} | {values['attempted']} | {values['success_rate']:.1%} |")
    lines += ["", "| 任务 | 通过/重复 | 中位耗时 | 模型调用 | 工具调用 |", "|---|---:|---:|---:|---:|"]
    for case in cases:
        selected = [record for record in records if record["case_id"] == case["id"]]
        lines.append(f"| {case['id']} {case['title']} | {sum(record['passed'] for record in selected)}/{len(selected)} | "
                     f"{statistics.median(record['elapsed_seconds'] for record in selected):.3f}s | "
                     f"{sum(record['model_calls'] for record in selected)} | {sum(record['tool_calls'] for record in selected)} |")
    lines += ["", "完整逐项规则、最终文件、原始结构快照、事件和失败明细见 cases.json、evaluation.json、workspace/与results/。", ""]
    if summary.get("live_probe"):
        probe = summary["live_probe"]
        lines += ["真实模型组：" + str(probe.get("status")) + "；探针请求" + str(probe.get("requests_attempted", 0))
                  + "次；实际办公任务" + str(probe.get("live_task_attempts", 0)) + "次。", "",
                  "真实API用量与费用以provider回执为准；连接阻塞或无回执时保持null，不用fixture数字替代。", ""]
    (state / "evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}), flush=True)
    raise SystemExit(0 if summary["passed"] == summary["attempted"] and summary["valid_source_snapshot"] else 1)


if __name__ == "__main__":
    main()
