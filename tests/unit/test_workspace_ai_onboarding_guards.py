from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_ai_onboarding_copy_tracks_goal_first_task_flow():
    embedded_html = _read("web/templates/index.html")

    assert "Koto AI" in embedded_html
    assert (
        "在输入框直接说出任务，或附加文件作为上下文。支持文档分析、PPT生成、代码编写、数据处理等。"
        in embedded_html
    )
    assert "wa-welcome-lede" not in embedded_html
    assert "wa-welcome-tip" not in embedded_html
    assert "读取并直接处理" not in embedded_html
    assert "支持多步骤工作流" not in embedded_html
    assert 'id="wa-actions-bar"' not in embedded_html
    assert "润色表达" not in embedded_html
    assert "翻译内容" not in embedded_html
    assert "提炼要点" not in embedded_html
    assert "检查问题" not in embedded_html
    assert "wa-welcome-grid" not in embedded_html
    assert "wa-welcome-card" not in embedded_html
    assert "wa-scenario-card" not in embedded_html
    assert "从这里开始" not in embedded_html
    assert "wa-welcome-capability-row" not in embedded_html
    assert "wa-welcome-starter" not in embedded_html


def test_workspace_ai_onboarding_placeholder_and_dropzone_match_new_context_rules():
    embedded_html = _read("web/templates/index.html")

    assert "拖放文件作为任务上下文" in embedded_html
    assert "添加任务上下文" in embedded_html
    assert "输入问题，或让 Koto 处理当前文件" in embedded_html
