import json

import pytest

from app.core.agent.file_task_followup import FileTaskFollowupStore


def _artifact(tool_name="read_cad_file"):
    return {
        "artifact_type": "koto_next_action_v1",
        "category": "missing_native_tool",
        "title": f"Koto 下一步：{tool_name}",
        "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
        "source_task": "修改 CAD 文件并导出总结",
        "target_path": "drawing.dwg",
        "missing_capability": tool_name,
        "why_missing": "allowlist 中没有可读取 dwg 的工具。",
        "suggested_next_step": "先实现只读 CAD 解析工具，再决定写入方案。",
        "implementation_scope": "smallest_next_capability",
        "acceptance_criteria": ["提供稳定入口"],
        "proposed_tool": {"name": tool_name, "description": "解析 CAD 文件。"},
    }


def test_file_task_followup_store_upserts_by_stable_artifact_identity(tmp_path):
    store = FileTaskFollowupStore(tmp_path / "followups.json")

    first = store.upsert(_artifact(), run_id="run_1", session_id="editor_demo")
    second = store.upsert(_artifact(), run_id="run_2", session_id="editor_demo")

    assert first["id"] == second["id"]
    assert second["occurrences"] == 2
    assert second["run_id"] == "run_2"
    assert (
        store.list(status="open")[0]["artifact"]["missing_capability"]
        == "read_cad_file"
    )

    raw = json.loads((tmp_path / "followups.json").read_text(encoding="utf-8"))
    assert len(raw) == 1
    assert raw[0]["id"] == first["id"]


def test_file_task_followup_store_updates_status(tmp_path):
    store = FileTaskFollowupStore(tmp_path / "followups.json")
    record = store.upsert(_artifact(), run_id="run_1")

    updated = store.update_status(record["id"], "accepted")

    assert updated["status"] == "accepted"
    assert store.list(status="open") == []
    assert store.list(status="accepted")[0]["id"] == record["id"]

    with pytest.raises(ValueError):
        store.update_status(record["id"], "unknown")
    with pytest.raises(KeyError):
        store.update_status("missing", "done")
