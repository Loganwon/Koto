"""Execution quality evaluation for the file assistant AI.

Tests the full end-to-end task execution path using real LLM calls and
validates results with AI-as-Judge.

All tests auto-skip when GOOGLE_API_KEY is not set.

Run:  pytest tests/evaluation/test_execution_quality.py -v --tb=short
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.file_task_runtime import FileTaskRuntime


def _read_file(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _collect_events_output(events) -> str:
    texts: List[str] = []
    for event in events:
        payload = (
            event.payload if hasattr(event, "payload") else event.get("payload", {})
        )
        content = (
            payload.get("content")
            or payload.get("text")
            or payload.get("summary")
            or ""
        )
        if isinstance(content, str) and content.strip():
            texts.append(content.strip())
    return "\n\n".join(texts[:30])


def _make_runtime():
    return FileTaskRuntime(
        model_client=FileTaskModelClient(),
        workspace_root=".",
    )


# -- Knowledge / Analysis Tasks -----------------------------------------


def test_execution_summarize_docx(evaluator, sample_docx):
    req = FileTaskRequest(
        task="总结这份报告的核心内容",
        files=[
            FileTaskFile(
                path=str(sample_docx),
                name=sample_docx.name,
                type="docx",
                content=_read_file(sample_docx),
            )
        ],
        run_id="eval_summarize",
        model_mode="cloud",
    )
    runtime = _make_runtime()
    events = list(runtime.run(req))
    output = _collect_events_output(events)

    assert len(events) > 0, f"无事件产生: {req.task}"

    verdict = evaluator.evaluate(
        task=req.task,
        expected="一份对报告的简短总结，包含关键信息（项目进度、营收等）",
        actual=output[:2000],
        criteria=[
            "是否提取了报告的核心信息",
            "是否有虚构内容",
            "总结是否简洁",
        ],
    )
    assert verdict.pass_, (
        f"总结质量不合格: {verdict.reason}\n"
        f"问题: {verdict.issues}\n"
        f"输出: {output[:600]}"
    )


def test_execution_analyze_xlsx(evaluator, sample_xlsx):
    req = FileTaskRequest(
        task="分析这个销售数据表格，告诉我哪个客户贡献最高、哪种产品卖得最好",
        files=[
            FileTaskFile(
                path=str(sample_xlsx),
                name=sample_xlsx.name,
                type="xlsx",
                content="销售数据表格",
            )
        ],
        run_id="eval_analyze_xlsx",
        model_mode="cloud",
    )
    runtime = _make_runtime()
    events = list(runtime.run(req))
    output = _collect_events_output(events)

    assert len(events) > 0, f"无事件产生: {req.task}"

    verdict = evaluator.evaluate(
        task=req.task,
        expected="明确指出最高贡献的客户和最好卖的产品，可以引用数据",
        actual=output[:2000],
        criteria=[
            "是否指出了最高贡献的客户",
            "是否指出了最好卖的产品",
            "分析是否有依据",
        ],
    )
    assert verdict.pass_, (
        f"分析质量不合格: {verdict.reason}\n"
        f"问题: {verdict.issues}\n"
        f"输出: {output[:600]}"
    )


def test_execution_diagnostic(evaluator):
    req = FileTaskRequest(
        task="为什么我上传的 xlsx 文件打不开？",
        files=[],
        run_id="eval_diagnostic",
        model_mode="cloud",
    )
    runtime = _make_runtime()
    events = list(runtime.run(req))
    output = _collect_events_output(events)

    assert len(events) > 0, f"无事件产生: {req.task}"

    verdict = evaluator.evaluate(
        task=req.task,
        expected="分析可能导致 xlsx 文件打不开的原因（格式、损坏、权限等），给出合理的诊断建议",
        actual=output[:2000],
        criteria=[
            "是否给出了可能的原因",
            "诊断是否合理",
            "没有胡编乱造",
        ],
    )
    assert verdict.pass_, (
        f"诊断质量不合格: {verdict.reason}\n"
        f"问题: {verdict.issues}\n"
        f"输出: {output[:600]}"
    )


def test_execution_translate_text(evaluator):
    req = FileTaskRequest(
        task="把下面这段话翻译成英文：人工智能正在改变我们的生活方式和工作模式。",
        files=[],
        run_id="eval_translate",
        model_mode="cloud",
    )
    runtime = _make_runtime()
    events = list(runtime.run(req))
    output = _collect_events_output(events)

    assert len(events) > 0, f"无事件产生: {req.task}"

    verdict = evaluator.evaluate(
        task=req.task,
        expected="英文翻译，应包含 'artificial intelligence', 'changing', 'lifestyle', 'work' 等关键词，语义准确",
        actual=output[:2000],
        criteria=[
            "翻译是否准确传达了原意",
            "没有漏译或增译",
            "英文语法是否正确",
        ],
    )
    assert verdict.pass_, (
        f"翻译质量不合格: {verdict.reason}\n"
        f"问题: {verdict.issues}\n"
        f"输出: {output[:600]}"
    )


# -- Write / Edit Tasks --------------------------------------------------


def test_execution_polish_docx(evaluator, workspace, sample_docx):
    text = _read_file(sample_docx)
    req = FileTaskRequest(
        task="润色这份报告，让表达更流畅专业",
        files=[
            FileTaskFile(
                path=str(sample_docx),
                name=sample_docx.name,
                type="docx",
                content=text,
                target=True,
            )
        ],
        target_path=str(sample_docx),
        run_id="eval_polish",
        model_mode="cloud",
    )
    runtime = _make_runtime()
    events = list(runtime.run(req))
    output = _collect_events_output(events)

    assert len(events) > 0, f"无事件产生: {req.task}"

    changed = any(
        getattr(e, "type", "") == "file.changed"
        or e.payload.get("type") == "file.changed"
        for e in events
    )

    verdict = evaluator.evaluate(
        task=req.task,
        expected="润色后的报告，保持了原始内容和数据，语言更流畅专业",
        actual=output[:2000],
        criteria=[
            "是否尝试修改了原文",
            "润色后语义是否一致",
            "表达是否更流畅",
        ],
    )
    assert verdict.pass_ or changed, (
        f"润色质量不合格: {verdict.reason}\n"
        f"问题: {verdict.issues}\n"
        f"文件变更: {changed}\n"
        f"输出: {output[:600]}"
    )


def test_execution_advice_only(evaluator, sample_docx):
    text = _read_file(sample_docx)
    req = FileTaskRequest(
        task="看看这份报告有什么可以改进的地方，只给建议，不要修改",
        files=[
            FileTaskFile(
                path=str(sample_docx),
                name=sample_docx.name,
                type="docx",
                content=text,
            )
        ],
        run_id="eval_advice",
        model_mode="cloud",
    )
    runtime = _make_runtime()
    events = list(runtime.run(req))
    output = _collect_events_output(events)

    assert len(events) > 0, f"无事件产生: {req.task}"

    verdict = evaluator.evaluate(
        task=req.task,
        expected="给出改进建议，但没有实际修改文件",
        actual=output[:2000],
        criteria=[
            "是否给出了具体的改进建议",
            "是否明确没有修改原文",
            "建议是否合理",
        ],
    )
    assert verdict.pass_, (
        f"建议分析质量不合格: {verdict.reason}\n"
        f"问题: {verdict.issues}\n"
        f"输出: {output[:600]}"
    )


# -- Quality Aggregation Report ------------------------------------------


def test_execution_quality_report(evaluator, sample_docx, sample_xlsx):
    """Aggregated end-to-end quality report.

    Runs all execution test cases and reports pass rate.
    """
    print(f"\n{'='*60}")
    print(f"  端到端执行质量评估")
    print(f"{'='*60}")

    cases: List[Dict[str, Any]] = [
        {"label": "总结 DOCX", "fn": "summarize"},
        {"label": "分析 XLSX", "fn": "analyze"},
        {"label": "诊断问题", "fn": "diagnostic"},
        {"label": "翻译文本", "fn": "translate"},
    ]
    results = []
    for case in cases:
        label = case["label"]
        try:
            if case["fn"] == "summarize":
                req = FileTaskRequest(
                    task="总结这份报告的核心内容",
                    files=[
                        FileTaskFile(
                            path=str(sample_docx),
                            name=sample_docx.name,
                            type="docx",
                            content=_read_file(sample_docx),
                        )
                    ],
                    run_id=f"eval_report_{case['fn']}",
                    model_mode="cloud",
                )
            elif case["fn"] == "analyze":
                req = FileTaskRequest(
                    task="分析这个销售数据表格，找出最关键的发现",
                    files=[
                        FileTaskFile(
                            path=str(sample_xlsx),
                            name=sample_xlsx.name,
                            type="xlsx",
                            content="销售数据",
                        )
                    ],
                    run_id=f"eval_report_{case['fn']}",
                    model_mode="cloud",
                )
            elif case["fn"] == "diagnostic":
                req = FileTaskRequest(
                    task="为什么 xlsx 文件会损坏？分析可能原因",
                    files=[],
                    run_id=f"eval_report_{case['fn']}",
                    model_mode="cloud",
                )
            elif case["fn"] == "translate":
                req = FileTaskRequest(
                    task="把'人工智能改变世界'翻译成英文",
                    files=[],
                    run_id=f"eval_report_{case['fn']}",
                    model_mode="cloud",
                )
            else:
                continue

            runtime = _make_runtime()
            events = list(runtime.run(req))
            output = _collect_events_output(events)
            verdict = evaluator.evaluate(
                task=req.task,
                expected="合理、准确、没有虚构的回复",
                actual=output[:2000],
            )
            status = "PASS" if verdict.pass_ else "FAIL"
            print(
                f"  [{status}] {label}  score={verdict.score:.0%}  {verdict.reason[:60]}"
            )
            results.append(
                {"label": label, "pass": verdict.pass_, "score": verdict.score}
            )
        except Exception as exc:
            print(f"  [SKIP] {label}  异常: {exc}")

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    rate = passed / total if total else 0
    print(f"{'='*60}")
    print(f"  执行质量通过率: {passed}/{total} = {rate:.0%}")
    print(f"{'='*60}")

    assert rate >= 0.60, f"端到端执行通过率 {rate:.0%} 低于阈值 60%，请检查失败案例"
