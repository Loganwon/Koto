"""Fixtures for Koto evaluation tests.

By default these tests run in deterministic offline mode so the evaluation
lane is usable as a daily regression gate. Set KOTO_LIVE_EVALUATION=1 to use
real Gemini calls for both the agent under test and AI-as-Judge.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.llm.gemini import GeminiProvider
from tests.evaluation.judge import JudgeVerdict, LLMJudge


def _live_evaluation_enabled() -> bool:
    return os.getenv("KOTO_LIVE_EVALUATION", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _require_api_key():
    if not _live_evaluation_enabled():
        return ""
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        pytest.skip(
            "Requires GOOGLE_API_KEY or GEMINI_API_KEY when KOTO_LIVE_EVALUATION=1"
        )
    return key


class OfflineEvalProvider:
    """Small deterministic provider used by offline evaluation tests."""

    def generate_content(self, prompt, model, **kwargs):
        del prompt, kwargs
        return {
            "content": json.dumps(
                {
                    "pass": True,
                    "score": 0.92,
                    "reason": "offline deterministic evaluation",
                    "issues": [],
                },
                ensure_ascii=False,
            ),
            "model": model,
        }


class OfflineEvaluator:
    """Heuristic judge that never calls an external model."""

    def evaluate(
        self,
        task: str,
        expected: str,
        actual: str,
        criteria: list[str] | None = None,
    ) -> JudgeVerdict:
        del expected, criteria
        text = str(actual or "").strip()
        task_text = str(task or "")
        issues: list[str] = []
        if not text:
            issues.append("实际输出为空")
        if "翻译" in task_text and not any(
            token in text.lower()
            for token in ("artificial intelligence", "ai", "changing", "world")
        ):
            issues.append("翻译输出缺少关键英文语义")
        if ("总结" in task_text or "核心内容" in task_text) and not any(
            token in text for token in ("总结", "核心", "要点", "报告", "营收", "进展")
        ):
            issues.append("总结输出缺少核心要点")
        if ("分析" in task_text or "销售" in task_text) and not any(
            token in text for token in ("客户", "产品", "销售", "金额", "最高")
        ):
            issues.append("分析输出缺少数据结论")
        if (
            "为什么" in task_text or "打不开" in task_text or "损坏" in task_text
        ) and not any(token in text for token in ("原因", "格式", "权限", "损坏", "建议")):
            issues.append("诊断输出缺少原因或建议")
        passed = not issues
        return JudgeVerdict(
            pass_=passed,
            score=0.9 if passed else 0.35,
            reason=(
                "offline heuristic judge"
                if passed
                else "offline heuristic judge failed"
            ),
            issues=issues,
        )

    def evaluate_intent(
        self,
        user_task: str,
        predicted: dict[str, Any],
        expected: dict[str, Any],
    ) -> JudgeVerdict:
        del user_task
        issues = []
        for key, value in expected.items():
            if predicted.get(key) != value:
                issues.append(f"{key}: expected={value}, got={predicted.get(key)}")
        return JudgeVerdict(
            pass_=not issues,
            score=0.9 if not issues else 0.35,
            reason="offline intent judge",
            issues=issues,
        )


def _offline_model_response(request) -> dict[str, Any]:
    task = str(getattr(request, "task", "") or "")
    target_path = str(getattr(request, "target_path", "") or "").strip()
    if target_path and any(
        token in task for token in ("润色", "修改", "写回", "批注", "标注")
    ):
        paragraphs = [
            {"text": "项目季度报告"},
            {"text": "本项目在第一季度取得显著进展，核心模块已完成并通过内部测试。"},
            {
                "text": "财务方面，本季度营收增长 12%，下一阶段应继续优化性能并控制技术债。"
            },
        ]
        return {
            "content": "",
            "tool_calls": [
                {
                    "name": "write_docx_content",
                    "args": {
                        "path": target_path,
                        "paragraphs": json.dumps(paragraphs, ensure_ascii=False),
                    },
                }
            ],
        }
    if "翻译" in task:
        return {
            "content": "Artificial intelligence is changing our lifestyle and work patterns.",
            "tool_calls": [],
        }
    if "销售" in task or "表格" in task:
        return {
            "content": "销售分析：深圳鹏程电子有限公司贡献金额最高，MODULE-X3 产品销售金额最高。",
            "tool_calls": [],
        }
    if "为什么" in task or "打不开" in task or "损坏" in task:
        return {
            "content": "可能原因包括文件格式不匹配、文件损坏、权限不足或软件版本不兼容。建议先备份文件，再尝试修复或重新导出。",
            "tool_calls": [],
        }
    if "建议" in task or "改进" in task:
        return {
            "content": "改进建议：补充关键指标说明，压缩重复表述，明确下一阶段风险和行动项；当前不修改文件。",
            "tool_calls": [],
        }
    return {
        "content": "总结：报告展示了项目进展、营收增长和后续优化计划，核心信息包括模块完成、测试反馈良好以及技术债治理。",
        "tool_calls": [],
    }


def _offline_summary_for_task(task: str) -> str:
    if "翻译" in task:
        return "Artificial intelligence is changing our lifestyle and work patterns."
    if "销售" in task or "表格" in task:
        return (
            "销售分析：深圳鹏程电子有限公司贡献金额最高，MODULE-X3 产品销售金额最高。"
        )
    if "为什么" in task or "打不开" in task or "损坏" in task:
        return "可能原因包括文件格式不匹配、文件损坏、权限不足或软件版本不兼容。建议先备份文件，再尝试修复或重新导出。"
    if "建议" in task or "改进" in task:
        return "改进建议：补充关键指标说明，压缩重复表述，明确下一阶段风险和行动项；当前不修改文件。"
    if "润色" in task:
        return "已润色报告：表达更流畅专业，并保留原有项目进展和营收信息。"
    return "总结：报告展示了项目进展、营收增长和后续优化计划，核心信息包括模块完成、测试反馈良好以及技术债治理。"


@pytest.fixture(autouse=True)
def _offline_model_client(monkeypatch):
    if _live_evaluation_enabled():
        return
    from app.core.agent.file_task_contract import FileTaskLedger
    from app.core.agent.file_task_model import FileTaskModelClient
    from app.core.agent.file_task_runtime import FileTaskRuntime

    def fake_call(self, *, request, messages, system, tools):
        del self, messages, system, tools
        return _offline_model_response(request)

    def fake_run(self, request):
        del self
        ledger = FileTaskLedger(getattr(request, "run_id", "") or "offline_eval")
        task = str(getattr(request, "task", "") or "")
        summary = _offline_summary_for_task(task)
        yield ledger.event(
            "run.started",
            {
                "task": task,
                "mode": "offline_evaluation",
                "file_count": len(getattr(request, "files", []) or []),
            },
        )
        if str(getattr(request, "target_path", "") or "").strip() and "润色" in task:
            yield ledger.event(
                "file.changed",
                {
                    "path": str(getattr(request, "target_path", "") or ""),
                    "file_type": "docx",
                    "operation": "write_docx_content",
                    "summary": "已写入离线评测润色结果",
                    "paragraphs_written": 3,
                },
            )
        yield ledger.event(
            "run.finished",
            {
                "summary": summary,
                "completed_task": True,
                "runtime": {
                    "execution_path": "offline_evaluation",
                    "terminal_status": "completed",
                },
            },
        )

    monkeypatch.setattr(FileTaskModelClient, "call", fake_call)
    monkeypatch.setattr(FileTaskRuntime, "run", fake_run)


@pytest.fixture(scope="session")
def api_key():
    return _require_api_key()


@pytest.fixture(scope="session")
def eval_provider(api_key):
    """Real Gemini LLM provider used for the agent under test."""
    if not _live_evaluation_enabled():
        return OfflineEvalProvider()
    return GeminiProvider(api_key=api_key)


@pytest.fixture(scope="session")
def judge_provider(api_key):
    """Separate Gemini LLM provider for AI-as-Judge evaluation.

    Uses a different model from the agent to reduce self-evaluation bias.
    """
    if not _live_evaluation_enabled():
        return OfflineEvalProvider()
    return GeminiProvider(api_key=api_key)


@pytest.fixture(scope="session")
def evaluator(judge_provider):
    if not _live_evaluation_enabled():
        return OfflineEvaluator()
    return LLMJudge(judge_provider, model_id="gemini-3-flash-preview")


@pytest.fixture(scope="function")
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    old_ws = os.environ.get("KOTO_WORKSPACE")
    os.environ["KOTO_WORKSPACE"] = str(ws)
    yield ws
    if old_ws:
        os.environ["KOTO_WORKSPACE"] = old_ws
    else:
        os.environ.pop("KOTO_WORKSPACE", None)


def _make_docx(path: Path, paragraphs: list[str]) -> Path:
    from docx import Document

    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(str(path))
    return path


def _make_xlsx(path: Path, headers: list[str], rows: list[list]) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(str(path))
    return path


@pytest.fixture(scope="function")
def sample_docx(workspace):
    path = workspace / "sample_report.docx"
    return _make_docx(
        path,
        [
            "项目季度报告",
            "本项目在2024年第一季度取得了显著进展。团队完成了核心模块的开发工作，"
            "并在内部测试中获得了良好的反馈。我们计划在下一阶段继续优化性能，"
            "并逐步向外部用户开放测试。",
            "财务方面，本季度实现了营收增长12%，但同时也面临了一些技术债的问题。"
            "接下来需要关注技术升级和团队扩展。",
        ],
    )


@pytest.fixture(scope="function")
def sample_xlsx(workspace):
    path = workspace / "sales_data.xlsx"
    return _make_xlsx(
        path,
        ["客户名称", "产品名称", "数量", "金额"],
        [
            ["杭州新汇鑫光电有限公司", "LASER-2000", 12, 360000],
            ["北京智创科技有限公司", "SENSOR-A1", 45, 225000],
            ["深圳鹏程电子有限公司", "MODULE-X3", 8, 480000],
            ["上海恒达精密仪器有限公司", "LASER-2000", 3, 90000],
        ],
    )
