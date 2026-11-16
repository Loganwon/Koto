from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_ai_onboarding_copy_tracks_goal_first_task_flow():
    embedded_html = _read("web/templates/index.html")

    assert "Koto (言) - AI Assistant" in embedded_html
    assert "提出问题、添加材料，或打开文档直接修改。" in embedded_html
    assert "执行过程与成果会保留在同一会话。" in embedded_html
    assert (
        'data-koto-suggestion="比较我附加的材料，列出主要差异与来源"' in embedded_html
    )
    assert 'data-koto-suggestion="根据材料生成一份有清晰结论的报告"' in embedded_html
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
    assert "描述任务，或添加文件一起处理…" in embedded_html
