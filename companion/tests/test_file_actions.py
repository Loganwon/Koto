"""Real output packages; fake native save/export are explicitly not acceptance."""

from pathlib import Path

import pytest

from companion.contracts import CompanionError, OperationCancelled, ResultUncertain
from companion.file_actions import FileActions, FileActionProposal
from companion.file_readers import parse_file
from companion.journal import EventJournal, document_scope
from companion.session import EditingSession
from companion.workspace import LocalWorkspace
from companion.tests.test_session import settled
from companion.tests.test_journal import FileDocument
from companion.tests.test_workspace_agent import agent_for
from companion.tests.test_task_goal import declare


def test_publish_new_preserves_a_concurrently_created_destination(tmp_path):
    temporary, destination = tmp_path / "temporary.txt", tmp_path / "result.txt"
    temporary.write_text("new output", encoding="utf-8")
    FileActions.publish_new(temporary, destination)
    assert destination.read_text(encoding="utf-8") == "new output"
    temporary.unlink(missing_ok=True)
    temporary.write_text("another output", encoding="utf-8")
    with pytest.raises(FileExistsError):
        FileActions.publish_new(temporary, destination)
    assert destination.read_text(encoding="utf-8") == "new output"


def setup_actions(tmp_path, documents=None):
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    docs = documents or FileDocument()
    return FileActions(workspace, docs), docs, workspace


@pytest.mark.parametrize("suffix", ["docx", "pptx", "xlsx"])
def test_new_office_package_is_real_readable_and_does_not_edit_current_doc(
    tmp_path, suffix
):
    actions, docs, _ = setup_actions(tmp_path)
    args = {"file_name": "项目汇报." + suffix, "title": "青岚项目"}
    args.update(
        {"rows": [["项目", "预算"], ["研发", 120.1], ["运营", 79.9]]}
        if suffix == "xlsx"
        else {
            "sections": [
                {"heading": "进展", "text": "青岚预算200万元。"},
                {"heading": "后续", "text": "核对6个团队。"},
            ]
        }
    )
    result = actions.execute(
        FileActionProposal("create_office_file", args),
        docs.connect("word"),
        lambda: True,
        lambda *args: None,
    )
    path = Path(result["path"])
    assert result["verified"] and result["bytes"] > 1000 and len(result["sha256"]) == 64
    text = parse_file(path).text
    assert "研发" in text if suffix == "xlsx" else "200" in text and "6" in text
    assert docs.writes == []
    assert not list(tmp_path.glob(".koto-*"))


@pytest.mark.parametrize(
    "name", ["../outside.docx", "C:/bad.docx", ".hidden.docx", "CON.docx", "x.exe"]
)
def test_generation_rejects_paths_and_unavailable_file_types(tmp_path, name):
    actions, docs, _ = setup_actions(tmp_path)
    with pytest.raises(CompanionError):
        actions.execute(
            FileActionProposal(
                "create_office_file", {"file_name": name, "title": "test"}
            ),
            docs.connect("word"),
            lambda: True,
            lambda *args: None,
        )
    assert not list(tmp_path.iterdir())


def test_no_overwrite_stop_or_implicit_spreadsheet_formula(tmp_path):
    actions, docs, _ = setup_actions(tmp_path)
    target = docs.connect("word")
    args = {
        "file_name": "已存在.docx",
        "title": "test",
        "sections": [{"heading": "", "text": "内容"}],
    }
    path = tmp_path / args["file_name"]
    path.write_bytes(b"original")
    with pytest.raises(CompanionError, match="同名文件"):
        actions.execute(
            FileActionProposal("create_office_file", args),
            target,
            lambda: True,
            lambda *args: None,
        )
    assert path.read_bytes() == b"original"
    with pytest.raises(OperationCancelled):
        actions.execute(
            FileActionProposal("create_office_file", args),
            target,
            lambda: False,
            lambda *args: None,
        )
    with pytest.raises(CompanionError, match="公式"):
        actions.execute(
            FileActionProposal(
                "create_office_file",
                {
                    "file_name": "不可执行.xlsx",
                    "title": "test",
                    "rows": [["=WEBSERVICE(1)"]],
                },
            ),
            target,
            lambda: True,
            lambda *args: None,
        )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["已存在.docx"]


def test_agent_generates_ppt_receipt_instead_of_word_placeholder_edit(tmp_path):
    actions, docs, workspace = setup_actions(tmp_path)
    model, _ = agent_for(
        [
            [declare("new_file", "create")],
            [
                (
                    "create_office_file",
                    {
                        "file_name": "汇报.pptx",
                        "title": "青岚",
                        "sections": [{"heading": "结论", "text": "项目覆盖6个团队。"}],
                    },
                )
            ],
        ],
        goal=None,
    )
    journal = EventJournal()
    session = EditingSession(
        docs, lambda: model, workspace.session, journal=journal, file_actions=actions
    )
    session.submit("新建汇报PPT并保存，不要修改当前Word")
    state = settled(session)
    assert state["phase"] == "answered", state["message"]
    assert state["artifact"]["file_id"] == "汇报.pptx"
    assert (tmp_path / "汇报.pptx").is_file() and not docs.writes
    assert state["answer"].startswith("已生成")
    assert (
        journal.recovery(document_scope("word", "C:/synthetic/report.docx"))[
            "unverified"
        ]
        == []
    )


@pytest.mark.parametrize("fail", [False, True])
def test_native_pdf_receipt_requires_real_pdf_and_does_not_replay_unknown_result(
    tmp_path, fail
):
    class NativeFixture(FileDocument):
        calls = 0

        def file_capabilities(self):
            return {"export_pdf": True}

        def call(self, name, target, path, **kwargs):
            self.calls += 1
            if fail:
                raise ResultUncertain("synthetic lost native reply")
            from reportlab.pdfgen import canvas

            document = canvas.Canvas(path)
            document.drawString(50, 700, "Synthetic export, not native WPS")
            document.save()
            return {"path": path}

    docs = NativeFixture()
    actions, _, workspace = setup_actions(tmp_path, docs)
    model, _ = agent_for(
        [
            [declare("current_fragment", "export")],
            [("export_current_pdf", {"file_name": "导出.pdf"})],
        ],
        goal=None,
    )
    journal = EventJournal()
    session = EditingSession(
        docs, lambda: model, workspace.session, journal=journal, file_actions=actions
    )
    session.submit("导出PDF")
    state = settled(session)
    assert state["phase"] == ("uncertain" if fail else "answered"), state["message"]
    assert docs.calls == 1 and not docs.writes
    if fail:
        assert not state["can_retry"] and not (tmp_path / "导出.pdf").exists()
        assert journal.recovery(document_scope("word", "C:/synthetic/report.docx"))[
            "unverified"
        ]
    else:
        assert (
            state["artifact"]["verified"]
            and "Synthetic export" in parse_file(tmp_path / "导出.pdf").text
        )
