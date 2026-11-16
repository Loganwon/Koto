"""Real bytes, no overwrite, stale source rejection and synchronized contracts."""

import hashlib
import threading
from companion.agent_lab.tools import Turn
from companion.tests.test_content_checks import setup_contract, draft


def test_copy_reference_and_rename_keep_original_and_move_contract(tmp_path):
    store, task, broker, source = setup_contract(tmp_path)
    raw = source.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    copied = broker.invoke(
        "copy_reference",
        {
            "action_id": "copy",
            "file_id": "销售.csv",
            "file_name": "资料副本.csv",
            "expected_sha256": sha,
        },
    )
    assert (
        copied["ok"]
        and (broker.outputs / "资料副本.csv").read_bytes() == raw == source.read_bytes()
    )
    receipt = draft(broker, "合计：2.00万元。销售.csv")["receipt"]
    args = {
        "action_id": "rename",
        "file_name": "结果.docx",
        "new_file_name": "正式结果.docx",
        "expected_sha256": receipt["sha256"],
    }
    renamed = broker.invoke("rename_artifact", args)
    assert renamed["ok"] and not (broker.outputs / "结果.docx").exists()
    state = store.get(task)
    assert state["expected_outputs"] == ["正式结果.docx"]
    assert (
        "正式结果.docx" in state["content_checks"]
        and "结果.docx" not in state["artifacts"]
    )
    assert broker.invoke("rename_artifact", args)["replayed_receipt"]
    assert broker.invoke("complete_task", {"summary": "完成"})["ok"]
    assert not draft(broker, "合计：2.00万元。销售.csv")[
        "ok"
    ]  # old receipt cannot falsely replay


def test_conflicts_paths_stale_versions_and_read_only_do_not_write(tmp_path):
    store, task, broker, source = setup_contract(tmp_path)
    raw = source.read_bytes()
    base = {
        "action_id": "c",
        "file_id": "销售.csv",
        "file_name": "副本.csv",
        "expected_sha256": "0" * 64,
    }
    assert not broker.invoke("copy_reference", base)["ok"]
    base["expected_sha256"] = hashlib.sha256(raw).hexdigest()
    for name in ("../外部.csv", "绝不转换.xlsx"):
        assert not broker.invoke("copy_reference", {**base, "file_name": name})["ok"]
    assert broker.invoke("copy_reference", base)["ok"]
    assert not broker.invoke("copy_reference", {**base, "action_id": "overwrite"})["ok"]
    n, e = store.begin_turn(task, "只解释", "read")
    broker.bind_turn(Turn(task, n, e, "只解释", "read", threading.Event()))
    assert not broker.invoke(
        "copy_reference", {**base, "action_id": "read", "file_name": "不能创建.csv"}
    )["ok"]
    assert source.read_bytes() == raw and not (broker.outputs / "不能创建.csv").exists()


def test_native_boundary_replays_same_copy_with_source_metadata(tmp_path):
    from docx import Document
    from companion.pane_task_tools import NativeBroker, NativeDocument, PaneTaskStore
    from companion.tests.test_pane_task_session import Host
    from companion.workspace import LocalWorkspace
    from companion.journal import EventJournal

    refs = tmp_path / "refs"
    refs.mkdir()
    doc = Document()
    doc.add_paragraph("原文必须保留")
    doc.save(refs / "来源.docx")
    workspace = LocalWorkspace()
    workspace.open(refs)
    store = PaneTaskStore(tmp_path / "native.sqlite3")
    task = store.create("复制来源", expected_outputs=["副本.docx"])
    host = Host()
    journal = EventJournal(tmp_path / "journal.sqlite3")
    native = NativeDocument(host, host.target, journal, "test", task)
    broker = NativeBroker(
        store,
        task,
        workspace,
        tmp_path / "outputs",
        native,
        lambda *args: {"allowed": True},
        False,
    )
    n, e = store.begin_turn(task, "复制来源", "auto")
    broker.bind_turn(Turn(task, n, e, "复制来源", "auto", threading.Event()))
    assert broker.invoke("read_reference", {"file_id": "来源.docx"})["ok"]
    args = {
        "action_id": "copy",
        "file_id": "来源.docx",
        "file_name": "副本.docx",
        "expected_sha256": hashlib.sha256(
            (refs / "来源.docx").read_bytes()
        ).hexdigest(),
        "source_ids": ["来源.docx"],
    }
    first = broker.invoke("copy_reference", args)
    assert first["ok"]
    assert broker.invoke("copy_reference", args)["replayed_receipt"]
    assert not host.writes
