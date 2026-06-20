"""Fixtures for Koto evaluation tests.

Requires GOOGLE_API_KEY environment variable.  All tests auto-skip without it.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.llm.gemini import GeminiProvider
from tests.evaluation.judge import LLMJudge


def _require_api_key():
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        pytest.skip("Requires GOOGLE_API_KEY or GEMINI_API_KEY environment variable")
    return key


@pytest.fixture(scope="session")
def api_key():
    return _require_api_key()


@pytest.fixture(scope="session")
def eval_provider(api_key):
    """Real Gemini LLM provider used for the agent under test."""
    return GeminiProvider(api_key=api_key)


@pytest.fixture(scope="session")
def judge_provider(api_key):
    """Separate Gemini LLM provider for AI-as-Judge evaluation.

    Uses a different model from the agent to reduce self-evaluation bias.
    """
    return GeminiProvider(api_key=api_key)


@pytest.fixture(scope="session")
def evaluator(judge_provider):
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
