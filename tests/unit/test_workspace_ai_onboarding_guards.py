from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_ai_onboarding_copy_tracks_goal_first_task_flow():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")

    for html in (embedded_html, standalone_html):
        assert "Koto AI" in html
        assert "能总结分析、改写润色、生成文档、整理文件。输入任务或附加文件，过程和结果都会显示在这里。" in html
        assert "wa-welcome-lede" not in html
        assert "wa-welcome-tip" not in html
        assert "读取并直接处理" not in html
        assert "支持多步骤工作流" not in html
        assert 'id="wa-actions-bar"' not in html
        assert "润色表达" not in html
        assert "翻译内容" not in html
        assert "提炼要点" not in html
        assert "检查问题" not in html
        # card grid removed
        assert "wa-welcome-grid" not in html
        assert "wa-welcome-card" not in html
        # removed in Apple-style redesign
        assert "wa-scenario-card" not in html
        assert "从这里开始" not in html
        assert "wa-welcome-capability-row" not in html
        assert "wa-welcome-starter" not in html


def test_workspace_ai_onboarding_placeholder_and_dropzone_match_new_context_rules():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")

    for html in (embedded_html, standalone_html):
        assert "拖放文件作为任务上下文" in html
        assert "添加任务上下文" in html
        assert "输入问题，或让 Koto 处理当前文件" in html
