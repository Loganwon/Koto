"""Cross-file editing, complete source addressing, and stale-source guards."""

import json
from pathlib import Path
import threading

import httpx
import pytest

from companion.agent import WorkspaceAgent
from companion.contracts import CompanionError, DocumentConflict
from companion.file_readers import parse_file
from companion.model import ModelConfig
from companion.reading import TextSnapshot
from companion.session import EditingSession
from companion.workspace import LocalWorkspace
from companion.tests.test_session import Documents, settled


def response(*calls):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call{i}",
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(args, ensure_ascii=False),
                                },
                            }
                            for i, (name, args) in enumerate(calls)
                        ],
                    },
                }
            ]
        },
    )


def agent_for(actions, *, goal=("current_fragment", "edit")):
    requests = []

    def send(request):
        payload = json.loads(request.content)
        requests.append(payload)
        # Existing scripted task steps share an explicit edit-goal handshake.
        # Goal-boundary tests pass goal=None and script the entire protocol.
        offered = {item["function"]["name"] for item in payload["tools"]}
        if goal is not None and "declare_task_goal" in offered:
            return response(("declare_task_goal", {
                "target": goal[0], "operation": goal[1], "summary": "测试指定的任务目标",
            }))
        action = actions.pop(0)
        return action(payload) if callable(action) else response(*action)

    return (
        WorkspaceAgent(
            ModelConfig("https://example.test", "test", "secret"),
            httpx.MockTransport(send),
        ),
        requests,
    )


def test_cross_file_tools_write_one_fragment_then_apply_feedback_to_next(tmp_path):
    folder = tmp_path / "资料"
    folder.mkdir()
    source = folder / "预算.md"
    source.write_text("研发费用：9876万元。", encoding="utf-8")
    workspace = LocalWorkspace()
    workspace.open(tmp_path)

    def edit(payload):
        outputs = [
            json.loads(m["content"]) for m in payload["messages"] if m["role"] == "tool"
        ]
        assert any("9876" in o.get("text", "") for o in outputs)
        request = json.loads(
            next(
                m["content"]
                for m in reversed(payload["messages"])
                if m["role"] == "user"
            )
        )
        suffix = " 后续按最新方向。" if request["feedback"] else ""
        return response(
            (
                "replace_current_text",
                {
                    "text": request["current_text"]
                    + " 研发预算9876万元（预算.md）。"
                    + suffix,
                    "note": "已核对预算",
                },
            )
        )

    model, requests = agent_for(
        [
            [("list_reference_files", {})],
            [("read_reference_file", {"file_id": "资料/预算.md"})],
            edit,
            [("read_reference_file", {"file_id": "资料/预算.md"})],
            edit,
        ]
    )
    docs = Documents()
    session = EditingSession(docs, lambda: model, workspace.session)
    session.connect("word")
    session.start("把预算中的研发费用补进这些段落", agent=True)
    state = settled(session)
    assert state["phase"] == "review", state["message"]
    assert docs.writes == ["one"] and docs.text["two"] == "second original"
    assert state["sources"][0]["file_id"] == "资料/预算.md"
    assert state["events"][-1]["tool"] == "native_write_verified"
    session.advance("后面按最新方向")
    assert settled(session)["phase"] == "review"
    assert docs.writes == ["one", "two"] and "最新方向" in docs.text["two"]
    assert source.read_text(encoding="utf-8") == "研发费用：9876万元。"


@pytest.mark.parametrize("change", ["reference", "target", "stop", "workspace"])
def test_change_during_agent_request_rejects_stale_write(tmp_path, change):
    source = tmp_path / "参考.txt"
    source.write_text("旧事实", encoding="utf-8")
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    started, release = threading.Event(), threading.Event()

    def pending(payload):
        started.set()
        assert release.wait(4)
        return response(
            ("replace_current_text", {"text": "不可写入的旧结果", "note": "旧事实"})
        )

    model, _ = agent_for([[("read_reference_file", {"file_id": "参考.txt"})], pending])
    docs = Documents()
    session = EditingSession(docs, lambda: model, workspace.session)
    session.connect("word")
    session.start("引用参考", agent=True)
    assert started.wait(2)
    if change == "reference":
        source.write_text("新事实", encoding="utf-8")
    if change == "target":
        docs.text["one"] = "用户刚写下的文字"
    if change == "stop":
        session.stop()
    if change == "workspace":
        other = tmp_path / "other"
        other.mkdir()
        workspace.open(other)
    release.set()
    state = settled(session)
    assert state["phase"] == ("stopped" if change == "stop" else "conflict"), state[
        "message"
    ]
    assert docs.writes == []


def test_full_text_search_outside_initial_context_and_read_only_answer(tmp_path):
    workspace = LocalWorkspace()
    workspace.open(tmp_path)

    class FullDocument(Documents):
        def text_snapshot(self, target):
            return TextSnapshot("test.docx", "前文" * 20000 + "结尾暗号：山海123")

    def answer(payload):
        result = json.loads(payload["messages"][-1]["content"])
        assert "山海123" in result["matches"][0]["text"]
        return response(("answer_user", {"text": "结尾暗号是山海123。"}))

    model, _ = agent_for([[("search_current_document", {"query": "结尾暗号"})], answer])
    docs = FullDocument()
    session = EditingSession(docs, lambda: model, workspace.session)
    session.connect("word")
    session.start("文末暗号是什么？", agent=True)
    state = settled(session)
    assert state["phase"] == "answered" and "山海123" in state["answer"]
    assert not state["can_continue"] and not docs.writes


def test_combined_read_and_write_packet_is_rejected(tmp_path):
    model, _ = agent_for(
        [
            [
                ("list_reference_files", {}),
                ("replace_current_text", {"text": "bad", "note": "bad"}),
            ]
        ]
    )
    docs = Documents()
    session = EditingSession(docs, lambda: model)
    session.connect("word")
    session.start("修改", agent=True)
    assert settled(session)["phase"] == "error" and not docs.writes


def test_explicit_reference_cannot_be_skipped_before_write(tmp_path):
    (tmp_path / "事实.txt").write_text("真实数值9876", encoding="utf-8")
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    model, _ = agent_for(
        [[("replace_current_text", {"text": "编造的数字120", "note": "未核对"})]]
    )
    docs = Documents()
    session = EditingSession(docs, lambda: model, workspace.session)
    session.connect("word")
    session.start('把 @"事实.txt" 的数字写进来', agent=True)
    state = settled(session)
    assert state["phase"] == "error" and "尚未读取" in state["message"]
    assert not docs.writes


def test_new_reference_in_feedback_is_checked_before_the_next_write(tmp_path):
    (tmp_path / "新资料.txt").write_text("数字9876", encoding="utf-8")
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    model, _ = agent_for(
        [
            [("replace_current_text", {"text": "第一处已改", "note": "修改"})],
            [("replace_current_text", {"text": "未经核对的120", "note": "修改"})],
        ]
    )
    docs = Documents()
    session = EditingSession(docs, lambda: model, workspace.session)
    session.submit("逐处修改")
    assert settled(session)["phase"] == "review"
    first = list(docs.writes)
    session.advance('下一处请引用 @"新资料.txt" 的数字')
    state = settled(session)
    assert state["phase"] == "error" and "尚未读取" in state["message"]
    assert docs.writes == first


def test_workspace_bounds_and_explicit_unread_state(tmp_path):
    secret = tmp_path / "key.txt"
    secret.write_text("never read", encoding="utf-8")
    source = tmp_path / "可见.txt"
    source.write_text("可引用文字", encoding="utf-8")
    (tmp_path / "~$可见.docx").write_text("Word owner lock", encoding="utf-8")
    workspace = LocalWorkspace(excluded=[secret])
    tree = workspace.open(tmp_path)
    assert [f["id"] for f in tree["entries"]] == [source.name]
    assert tree["entries"][0]["status"] == "unread"
    for file_id in ("../outside.txt", "key.txt"):
        with pytest.raises(CompanionError):
            workspace.session().read(file_id)
    assert workspace.session().read(source.name)["text"] == "可引用文字"
    assert workspace.tree()["entries"][0]["status"] == "text_ready"


def test_docx_reads_all_body_table_header_and_tail_and_pages(tmp_path):
    from docx import Document

    document = Document()
    document.add_paragraph("文档内容。" * 5000)
    table = document.add_table(rows=2, cols=2)
    for cell, value in zip(
        [c for row in table.rows for c in row.cells], ["项目", "金额", "研发", "9876"]
    ):
        cell.text = value
    document.add_paragraph("全文尾部核验标记")
    document.sections[0].header.paragraphs[0].text = "页眉标记"
    path = tmp_path / "source.docx"
    document.save(path)
    snapshot = parse_file(path)
    assert "页眉标记" in snapshot.text and "9876" in snapshot.text
    result = snapshot.search("全文尾部")
    assert result["matches"][0]["offset"] > 18000
    parts, start = [], 0
    while start is not None:
        page = snapshot.read(start, 5000)
        parts.append(page["text"])
        start = page["next"]
    assert "".join(parts) == snapshot.text
    assert snapshot.limitations


def test_xlsx_all_sheets_hidden_sheets_and_formula_are_explicit(tmp_path):
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "东区"
    book.active["B2"] = 9876
    second = book.create_sheet("南区")
    second["A90"] = "文末数据"
    second["B90"] = "=2+2"
    second.sheet_state = "hidden"
    path = tmp_path / "费用.xlsx"
    book.save(path)
    book.close()
    snapshot = parse_file(path)
    assert snapshot.coverage == ("东区", "南区")
    assert "东区!B2\t9876" in snapshot.text
    assert (
        "南区!A90\t文末数据" in snapshot.text
        and "=2+2" in snapshot.text
        and "缓存结果: None" in snapshot.text
    )


def test_open_unsaved_source_takes_priority_and_is_version_checked(tmp_path):
    source = tmp_path / "source.docx"
    source.write_text("not opened from disk", encoding="utf-8")
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    text = ["原生应用里尚未保存的内容"]
    reads = workspace.session(lambda path: TextSnapshot(Path(path).name, text[0]))
    assert reads.read(source.name)["text"] == text[0]
    text[0] = "用户又改了参考文档"
    with pytest.raises(DocumentConflict):
        reads.verify()
