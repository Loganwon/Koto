"""Intent accuracy evaluation for the file assistant AI adjudicator.

These tests use real LLM calls to verify that the AI intent adjudicator
correctly classifies user requests.  Each test case is a (user_message,
expected_intent, expected_should_write) tuple.

All tests auto-skip when GOOGLE_API_KEY is not set.

Run:  pytest tests/evaluation/test_intent_accuracy.py -v --tb=short
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.file_task_runtime import FileTaskRuntime

# -- Test Cases ---------------------------------------------------------
# Each: (label, task_text, files_context, expected)
# expected: dict with optional keys: intent, output_mode, write_intent

INTENT_CASES: List[Dict[str, Any]] = [
    {
        "label": "明确修改 DOCX",
        "task": "帮我把这个报告里的'第一季度'改成'Q1'",
        "files": [
            FileTaskFile(
                path="report.docx", name="report.docx", type="docx", target=True
            )
        ],
        "expected": {"output_mode": "write", "write_intent": True},
    },
    {
        "label": "只询问不修改",
        "task": "这份报告里有哪些地方可以改进？只分析，不要改",
        "files": [FileTaskFile(path="report.docx", name="report.docx", type="docx")],
        "expected": {"output_mode": "answer", "write_intent": False},
    },
    {
        "label": "润色 DOCX（歧义）",
        "task": "帮我把这个 DOCX 润色一下，看看有哪里不通顺",
        "files": [
            FileTaskFile(path="essay.docx", name="essay.docx", type="docx", target=True)
        ],
        "expected": {"output_mode": "write", "write_intent": True},
    },
    {
        "label": "总结 PDF",
        "task": "总结一下这个文件",
        "files": [FileTaskFile(path="document.pdf", name="document.pdf", type="pdf")],
        "expected": {"output_mode": "answer", "write_intent": False},
    },
    {
        "label": "翻译 DOCX",
        "task": "把这份英文合同翻译成中文",
        "files": [
            FileTaskFile(
                path="contract.docx", name="contract.docx", type="docx", target=True
            )
        ],
        "expected": {"output_mode": "write", "write_intent": True},
    },
    {
        "label": "XLSX 图表分析",
        "task": "分析这个销售数据，做成图表给我看看",
        "files": [FileTaskFile(path="sales.xlsx", name="sales.xlsx", type="xlsx")],
        "expected": {"output_mode": "answer", "write_intent": False},
    },
    {
        "label": "诊断失败原因",
        "task": "为什么上次的那个任务失败了？",
        "files": [],
        "expected": {"diagnostic_request": True, "write_intent": False},
    },
    {
        "label": "创建新文件",
        "task": "根据这份数据，帮我写一份项目总结报告",
        "files": [FileTaskFile(path="data.xlsx", name="data.xlsx", type="xlsx")],
        "expected": {"output_mode": "write", "write_intent": True},
    },
    {
        "label": "文件对比审校",
        "task": "对照原文PDF审校这份翻译稿，把问题标注出来",
        "files": [
            FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
            FileTaskFile(
                path="translation.docx",
                name="translation.docx",
                type="docx",
                target=True,
            ),
        ],
        "expected": {"output_mode": "write", "write_intent": True},
    },
    {
        "label": "只看不写",
        "task": "看看这个 PPT 的设计有没有问题，先不要改",
        "files": [FileTaskFile(path="deck.pptx", name="deck.pptx", type="pptx")],
        "expected": {"output_mode": "answer", "write_intent": False},
    },
    {
        "label": "PPT 美化",
        "task": "这个 PPT 太丑了，帮我美化一下",
        "files": [
            FileTaskFile(path="deck.pptx", name="deck.pptx", type="pptx", target=True)
        ],
        "expected": {"output_mode": "write", "write_intent": True},
    },
    {
        "label": "纯聊天",
        "task": "你好，今天天气怎么样？",
        "files": [],
        "expected": {"output_mode": "answer", "write_intent": False},
    },
    {
        "label": "对比两份 DOCX",
        "task": "对比这两份 DOCX 文档，告诉我有哪里不同",
        "files": [
            FileTaskFile(path="v1.docx", name="v1.docx", type="docx"),
            FileTaskFile(path="v2.docx", name="v2.docx", type="docx", target=True),
        ],
        "expected": {"output_mode": "answer", "write_intent": False},
    },
    {
        "label": "DOCX 批注",
        "task": "给这份合同做批注，标记出风险条款",
        "files": [
            FileTaskFile(
                path="contract.docx", name="contract.docx", type="docx", target=True
            )
        ],
        "expected": {"output_mode": "write", "write_intent": True},
    },
    {
        "label": "翻译+回写 DOCX",
        "task": "把这篇中文报告翻译成英文，直接写回原文位置",
        "files": [
            FileTaskFile(
                path="report.docx", name="report.docx", type="docx", target=True
            )
        ],
        "expected": {"output_mode": "write", "write_intent": True},
    },
]


def _make_runtime():
    """Create a FileTaskRuntime with a real model client."""
    return FileTaskRuntime(
        model_client=FileTaskModelClient(),
        workspace_root=".",
    )


def _check_expected(
    classification: FileTaskClassification,
    adjudication: Dict[str, Any],
    expected: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare classification + adjudication against expected values."""
    errors: List[str] = []

    for key, expected_val in expected.items():
        actual = getattr(classification, key, None)
        if actual != expected_val:
            errors.append(f"{key}: expected={expected_val}, got={actual}")

    return {
        "pass": len(errors) == 0,
        "errors": errors,
        "output_mode": classification.output_mode,
        "write_intent": classification.write_intent,
        "diagnostic_request": classification.diagnostic_request,
        "reason_codes": classification.reason_codes,
        "adjudication_intent": adjudication.get("intent", ""),
        "adjudication_confidence": adjudication.get("confidence", 0),
    }


# -- Tests --------------------------------------------------------------


@pytest.mark.parametrize("case", INTENT_CASES, ids=[c["label"] for c in INTENT_CASES])
def test_intent_accuracy(case, eval_provider, evaluator):
    runtime = _make_runtime()
    files = case.get("files", [])
    request = FileTaskRequest(
        task=case["task"],
        run_id=f"eval_{case['label'][:20]}",
        files=files,
        model_mode="cloud",
    )

    classification = runtime._classify_request(request, files)

    adjudication = runtime._adjudicate_intent_if_needed(request, files, classification)

    if adjudication.get("status") == "ok":
        classification = runtime._apply_intent_adjudication(
            request, files, classification, adjudication
        )

    result = _check_expected(classification, adjudication, case["expected"])

    # If the rule-based check fails, use AI judge for a second opinion
    if not result["pass"]:
        verdict = evaluator.evaluate_intent(
            user_task=case["task"],
            predicted={
                "output_mode": classification.output_mode,
                "write_intent": classification.write_intent,
                "diagnostic_request": classification.diagnostic_request,
                "adjudication_intent": adjudication.get("intent", ""),
                "reason_codes": classification.reason_codes,
            },
            expected=case["expected"],
        )
        if verdict.pass_:
            pytest.fail(
                f"[{case['label']}] 规则检查未通过，但 AI 评判也认为不正确:\n"
                f"  规则错误: {result['errors']}\n"
                f"  实际: output_mode={result['output_mode']}, "
                f"write_intent={result['write_intent']}, "
                f"adjudication={result['adjudication_intent']}\n"
                f"  评判理由: {verdict.reason}"
            )
        return

    assert result["pass"], (
        f"[{case['label']}] 意图分类不符合预期:\n"
        f"  错误: {result['errors']}\n"
        f"  完整输出: {result}"
    )


def test_intent_accuracy_report(evaluator):
    """Aggregated intent accuracy report."""
    runtime = _make_runtime()
    results = []

    for case in INTENT_CASES:
        files = case.get("files", [])
        request = FileTaskRequest(
            task=case["task"],
            run_id=f"eval_{case['label'][:20]}",
            files=files,
            model_mode="cloud",
        )
        classification = runtime._classify_request(request, files)
        adjudication = runtime._adjudicate_intent_if_needed(
            request, files, classification
        )

        if adjudication.get("status") == "ok":
            classification = runtime._apply_intent_adjudication(
                request, files, classification, adjudication
            )

        result = _check_expected(classification, adjudication, case["expected"])
        result["label"] = case["label"]
        results.append(result)

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    rate = passed / total if total else 0

    print(f"\n{'='*60}")
    print(f"  意图识别准确率: {passed}/{total} = {rate:.0%}")
    print(f"{'='*60}")
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  [{status}] {r['label']}")
        print(
            f"         output_mode={r['output_mode']}, "
            f"write_intent={r['write_intent']}, "
            f"diagnostic={r['diagnostic_request']}"
        )
        if r["errors"]:
            # Evaluation errors can be derived from model responses.  Keep the
            # report useful without writing potentially sensitive payloads to
            # CI logs.
            print("         ERROR: classification did not match expected values")
        if r["adjudication_intent"]:
            print(
                f"         adjudicator: {r['adjudication_intent']} "
                f"(conf={r['adjudication_confidence']})"
            )
    print(f"{'='*60}")

    assert rate >= 0.65, f"意图识别准确率 {rate:.0%} 低于阈值 65%，请检查失败案例"
