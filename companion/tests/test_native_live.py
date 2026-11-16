"""Opt-in tests. Only documents bearing this run's fixture marker are closed."""

import base64
from pathlib import Path
import threading
import time
import uuid

import pytest

from companion.contracts import DocumentConflict
from companion.model import EditProposal, ModelConfig, ToolCallingModel
from companion.session import EditingSession
from companion.windows import HOSTS, WindowsDocuments, diagnose


class NativeFixture(WindowsDocuments):
    def __init__(self, directory):
        self._fixture_directory = directory
        self._fixture_marker = uuid.uuid4().hex
        self._fixture_document = None
        self._fixture_other = None

        def factory(host):
            if self._fixture_document is not None:
                self._fixture_document.Activate()
                return self._fixture_application
            import win32com.client

            application = win32com.client.DispatchEx(HOSTS[host][1])
            self._fixture_application = application
            self._had_documents = application.Documents.Count > 0
            document = application.Documents.Add()
            self._fixture_document = document
            document.Variables.Add("KotoCompanionFixture", self._fixture_marker)
            picture = directory / "fixture.png"
            picture.write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aLp8AAAAASUVORK5CYII="
                )
            )
            application.Visible = True
            self._test_reset()
            return application

        super().__init__(factory, timeout=30)

    def _test_reset(self):
        if self._fixture_other is not None:
            assert (
                self._fixture_other.Variables.Item("KotoCompanionFixture").Value
                == self._fixture_marker
            )
            self._fixture_other.Close(0)
            self._fixture_other = None
        self._ranges.clear()
        document = self._fixture_document
        document.Content.Text = "First fixture paragraph.\rSecond fixture paragraph.\rThird fixture paragraph.\rManual text outside selection.\r"
        table = document.Tables.Add(
            document.Range(document.Content.End - 1, document.Content.End - 1), 2, 2
        )
        for row, values in enumerate((("项目", "金额"), ("研发", "120")), 1):
            for column, value in enumerate(values, 1):
                table.Cell(row, column).Range.Text = value
        document.InlineShapes.AddPicture(
            str(self._fixture_directory / "fixture.png"),
            False,
            True,
            document.Range(document.Content.End - 1, document.Content.End - 1),
        )
        document.Activate()
        document.Range(0, document.Paragraphs.Item(3).Range.End).Select()

    def _test_manual(self, index, text):
        part = self._fixture_document.Paragraphs.Item(index).Range.Duplicate
        part.End -= 1
        part.Text = text

    def _test_fonts(self):
        part = self._fixture_document.Paragraphs.Item(1).Range.Duplicate
        part.End -= 1

        def describe(font):
            result = {}
            for name in ("Name", "NameAscii", "NameFarEast", "NameOther", "NameBi"):
                try:
                    result[name] = getattr(font, name)
                except Exception:
                    result[name] = "unsupported"
            return result

        return describe(part.Font)

    def _test_mix_font(self):
        self._fixture_document.Paragraphs.Item(1).Range.Characters.Item(
            1
        ).Font.NameAscii = "Arial"

    def _test_state(self):
        document = self._fixture_document
        return {
            "paragraphs": [
                document.Paragraphs.Item(i).Range.Text.rstrip("\r") for i in range(1, 5)
            ],
            "tables": document.Tables.Count,
            "images": document.InlineShapes.Count,
            "cells": [
                document.Tables.Item(1).Range.Cells.Item(i).Range.Text.rstrip("\r\x07")
                for i in range(1, 5)
            ],
        }

    def _test_select_table(self):
        self._fixture_document.Tables.Item(1).Range.Select()

    def _test_select_cell(self, row, column):
        part = self._fixture_document.Tables.Item(1).Cell(row, column).Range.Duplicate
        part.End -= 1
        part.Select()

    def _test_select_paragraph(self, index):
        self._fixture_document.Paragraphs.Item(index).Range.Select()

    def _test_capture_latency(self):
        from statistics import median
        from companion.observation import capture_document, capture_selection

        document = self._fixture_document
        end = document.Content.End - 1
        document.Tables.Add(document.Range(end, end), 50, 6)
        document.Paragraphs.Item(1).Range.Select()
        selected = self._fixture_application.Selection.Range.Duplicate
        before = time.perf_counter()
        full = capture_document(self._target_host, document, selected)
        full_time = time.perf_counter() - before
        quick = []
        for _ in range(3):
            before = time.perf_counter()
            result = capture_selection(self._target_host, document, selected)
            quick.append(time.perf_counter() - before)
        assert result["tables_pending"] and not result["tables"]
        assert full["tables"] and result["current_text"] == "First fixture paragraph."
        return {"full_ms": full_time * 1000, "quick_ms": median(quick) * 1000}

    def _test_merge_cells(self):
        table = self._fixture_document.Tables.Item(1)
        table.Cell(1, 1).Merge(table.Cell(2, 1))

    def _test_switch(self):
        document = self._fixture_application.Documents.Add()
        self._fixture_other = document
        document.Variables.Add("KotoCompanionFixture", self._fixture_marker)
        document.Content.Text = "Other document must remain unchanged.\r"
        document.Activate()
        return document.Content.Text

    def _test_other_text(self):
        return self._fixture_other.Content.Text

    def _test_reference(self, path):
        document = self._fixture_application.Documents.Add()
        self._fixture_other = document
        document.Variables.Add("KotoCompanionFixture", self._fixture_marker)
        document.Content.Text = "研发预算：120万元。\r"
        document.SaveAs(path, 12)
        document.Content.Text = "研发预算：9876万元（刚更新，尚未保存）。\r"
        self._fixture_document.Activate()
        return document.Content.Text

    def _test_save(self):
        path = self._fixture_directory / "native-result.docx"
        self._fixture_document.SaveAs(str(path), 12)
        return str(path)

    def _test_reload(self, path):
        assert (
            self._fixture_document.Variables.Item("KotoCompanionFixture").Value
            == self._fixture_marker
        )
        self._ranges.clear()
        self._document = None
        self._fixture_document.Close(0)
        self._fixture_document = self._fixture_application.Documents.Open(path)
        assert (
            self._fixture_document.Variables.Item("KotoCompanionFixture").Value
            == self._fixture_marker
        )
        return self._test_state()

    def _test_cleanup(self):
        self._ranges.clear()
        self._document = None
        for document in (self._fixture_other, self._fixture_document):
            if document is not None:
                assert (
                    document.Variables.Item("KotoCompanionFixture").Value
                    == self._fixture_marker
                )
                document.Close(0)
        # Leave the host running; WPS may share its server with user windows.
        # Only close our marked fixtures, never quit a potentially shared app.
        self._fixture_document = self._fixture_other = self._fixture_application = None


@pytest.fixture(scope="module", params=["word", "wps"])
def native_environment(request, tmp_path_factory):
    if not request.config.getoption("--native-office"):
        pytest.skip("explicit --native-office required")
    environment = diagnose()
    if not any(
        host["id"] == request.param and host["installed"]
        for host in environment["hosts"]
    ):
        pytest.skip("requested native host is not installed")
    port = NativeFixture(tmp_path_factory.mktemp("companion-" + request.param))
    try:
        port.connect(request.param)
        yield port, request.param
    finally:
        try:
            port._call("test_cleanup")
        finally:
            port.close()
            port._thread.join(timeout=30)
            assert not port._thread.is_alive(), "native apartment did not shut down"


@pytest.fixture
def native(native_environment):
    port, host = native_environment
    port._call("test_reset")
    yield port, port.connect(host), host


def wait_for(session):
    deadline = time.monotonic() + 90
    while session.snapshot()["busy"] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not session.snapshot()["busy"], "agent did not settle"
    return session.snapshot()


def live_config(request):
    from companion.config import config_from_key_file

    key_file = request.config.getoption("--api-key-file")
    if key_file:
        return config_from_key_file(key_file)
    from dotenv import dotenv_values

    values = dotenv_values(
        Path(__file__).resolve().parents[2] / "config" / "deepseek_config.env"
    )
    key = values.get("DEEPSEEK_API_KEY")
    if not key:
        pytest.skip("an explicit DeepSeek key is required")
    return ModelConfig("https://api.deepseek.com", "deepseek-chat", key)


class FixedModel:
    def propose(self, **kwargs):
        return EditProposal(kwargs["current"] + " [edited]", "Test edit")


@pytest.mark.integration
def test_native_live_ranges_follow_earlier_edits_and_preserve_other_content(native):
    port, target, _ = native
    port._call("test_manual", 4, "New unsaved manual input")
    first, second = target.fragments[:2]
    assert port.replace(
        target.id,
        first.id,
        first.text,
        first.text + " Longer first paragraph.",
        lambda: True,
    )
    assert port.read(target.id, second.id) == second.text
    port.replace(
        target.id, second.id, second.text, "New second paragraph.", lambda: True
    )
    actual = port._call("test_state")
    assert actual["paragraphs"][1] == "New second paragraph."
    assert actual["paragraphs"][2] == "Third fixture paragraph."
    assert actual["paragraphs"][3] == "New unsaved manual input"
    assert actual["tables"] == actual["images"] == 1
    result = Path(port._call("test_save"))
    assert result.is_file() and result.stat().st_size > 0
    assert port._call("test_reload", str(result)) == actual


@pytest.mark.integration
def test_native_target_stays_pinned_after_switching_documents(native):
    port, target, _ = native
    original = port._call("test_switch")
    fragment = target.fragments[0]
    port.replace(
        target.id, fragment.id, fragment.text, "Pinned target only.", lambda: True
    )
    assert port._call("test_state")["paragraphs"][0] == "Pinned target only."
    assert port._call("test_other_text") == original


@pytest.mark.integration
def test_native_manual_conflict_rejects_old_text(native):
    port, target, _ = native
    first = target.fragments[0]
    port._call("test_manual", 1, "Manual change during model request")
    with pytest.raises(DocumentConflict):
        port.replace(target.id, first.id, first.text, "Must not write", lambda: True)
    assert (
        port._call("test_state")["paragraphs"][0]
        == "Manual change during model request"
    )


@pytest.mark.integration
def test_native_session_waits_after_each_visible_paragraph(native):
    port, _, host = native
    session = EditingSession(port, FixedModel)
    session.connect(host)
    session.start("逐段修改")
    assert wait_for(session)["phase"] == "review"
    state = port._call("test_state")
    assert state["paragraphs"][0].endswith("[edited]")
    assert state["paragraphs"][1] == "Second fixture paragraph."
    session.advance("继续")
    assert wait_for(session)["phase"] == "review"
    session.stop()
    assert port._call("test_state")["paragraphs"][2] == "Third fixture paragraph."


@pytest.mark.integration
@pytest.mark.live_api
def test_real_model_writes_first_paragraph_in_native_host(native, request):
    if not request.config.getoption("--live-model"):
        pytest.skip("explicit --live-model required")
    config = live_config(request)
    port, _, host = native
    started = threading.Event()
    real = ToolCallingModel(config)

    class LiveModel:
        def propose(self, **kwargs):
            started.set()
            return real.propose(**kwargs)

    session = EditingSession(port, LiveModel)
    session.connect(host)
    session.start("请在当前段落的末尾追加 [AI核验]，其他字不要修改。")
    assert started.wait(5)
    port._call("test_manual", 4, "User can type while the API is pending")
    state = wait_for(session)
    assert state["phase"] == "review", state["message"]
    actual = port._call("test_state")
    assert "[AI核验]" in actual["paragraphs"][0]
    assert actual["paragraphs"][1] == "Second fixture paragraph."
    assert actual["paragraphs"][3] == "User can type while the API is pending"
    assert actual["tables"] == actual["images"] == 1


@pytest.mark.integration
def test_native_reads_table_relationships_and_edits_each_cell_without_flattening(
    native,
):
    port, _, host = native
    port._call("test_select_table")
    context = port.read_current(host)
    assert context["tables"][0]["cells"] == [
        {"row": 1, "column": 1, "text": "项目"},
        {"row": 1, "column": 2, "text": "金额"},
        {"row": 2, "column": 1, "text": "研发"},
        {"row": 2, "column": 2, "text": "120"},
    ]
    target = port.connect(host)
    assert [f.text for f in target.fragments] == ["项目", "金额", "研发", "120"]
    cell = target.fragments[-1]
    assert cell.label == "第 2 行，第 2 列"
    port.replace(target.id, cell.id, "120", "150", lambda: True)
    state = port._call("test_state")
    assert state["cells"] == ["项目", "金额", "研发", "150"]
    assert state["tables"] == state["images"] == 1
    assert state["paragraphs"][0] == "First fixture paragraph."


@pytest.mark.integration
def test_native_reads_merged_table_cells(native):
    port, _, host = native
    port._call("test_merge_cells")
    port._call("test_select_table")
    context = port.read_current(host)
    cells = context["tables"][0]["cells"]
    assert len(cells) == 3
    assert "项目" in cells[0]["text"] and "研发" in cells[0]["text"]
    assert any(cell["text"] == "120" and cell["column"] == 2 for cell in cells)


@pytest.mark.integration
def test_native_background_follows_edits_selection_save_and_document_switch(native):
    port, _, host = native
    port.watch(host)

    def observed(predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            value = port.observation()
            if predicate(value):
                return value
            time.sleep(0.05)
        raise AssertionError("native observation did not update")

    original = observed(lambda x: x.get("connected") and x.get("host") == host)
    port._call("test_manual", 4, "Live manual progress")
    updated = observed(
        lambda x: x.get("content_fingerprint") != original.get("content_fingerprint")
        and "Live manual progress" in x.get("document_text", "")
    )
    assert updated["revision"] > original["revision"]
    assert not updated["saved"]
    port._call("test_select_cell", 2, 2)
    cell = observed(lambda x: x.get("current_text") == "120")
    assert "第 2 行" in cell["location"]
    port._call("test_save")
    assert observed(lambda x: x.get("saved"))["path"].endswith("native-result.docx")
    port._call("test_switch")
    switched = observed(lambda x: "Other document" in x.get("current_text", ""))
    assert switched["name"] != cell["name"]
    port.watch(host, False)
    assert port.observation()["watching"] is False
    port.watch(host, True)


@pytest.mark.integration
@pytest.mark.live_api
def test_real_model_understands_native_table_and_edits_one_cell(native, request):
    if not request.config.getoption("--live-model"):
        pytest.skip("explicit --live-model required")
    port, _, host = native
    real = ToolCallingModel(live_config(request))
    context = port.read_current(host)
    before = port._call("test_state")
    answer = real.answer(
        instruction="只根据表格回答：研发对应的金额是多少？请写出项目名称和金额。",
        context=context,
        history=[],
        cancelled=threading.Event(),
    )
    assert "120" in answer and "研发" in answer
    assert port._call("test_state") == before
    port._call("test_select_cell", 2, 2)
    session = EditingSession(port, lambda: real)
    session.connect(host)
    session.start("请将当前金额改为150，只返回数字，不添加解释。")
    state = wait_for(session)
    assert state["phase"] == "review", state["message"]
    after = port._call("test_state")
    assert after["cells"] == ["项目", "金额", "研发", "150"]
    assert after["paragraphs"] == before["paragraphs"]
    assert after["tables"] == after["images"] == 1


@pytest.mark.integration
def test_native_full_text_has_tail_outside_monitor_excerpt(native):
    port, target, _ = native
    port._call("test_manual", 4, "长文内容" * 6000 + "原生全文尾部标记")
    snapshot = port.text_snapshot(target.id)
    result = snapshot.search("原生全文尾部标记")
    assert result["matches"][0]["offset"] > 18000
    assert "正文（含表格）" in snapshot.coverage
    assert "研发" in snapshot.text and "120" in snapshot.text
    assert port.read(target.id, target.fragments[0].id) == target.fragments[0].text


@pytest.mark.integration
def test_native_selection_feedback_does_not_wait_for_tables(native, tmp_path):
    import json

    port, _, host = native
    timings = port._call("test_capture_latency")
    assert timings["quick_ms"] < timings["full_ms"] * 0.5, timings
    port.watch(host)
    latencies = []
    for index, text in [
        (2, "Second fixture paragraph."),
        (4, "Manual text outside selection."),
        (1, "First fixture paragraph."),
    ]:
        port._call("test_select_paragraph", index)
        started = time.perf_counter()
        while port.observation().get("current_text") != text:
            assert time.perf_counter() - started < 1.5, port.observation().get(
                "message"
            )
            time.sleep(0.005)
        latencies.append((time.perf_counter() - started) * 1000)
    timings["selection_ms"] = latencies
    (tmp_path / f"selection-latency-{host}.json").write_text(
        json.dumps(timings), encoding="utf-8"
    )


@pytest.mark.integration
@pytest.mark.live_api
def test_real_agent_reads_full_document_on_demand_without_initial_body_excerpt(
    native, request
):
    if not request.config.getoption("--live-model"):
        pytest.skip("explicit --live-model required")
    from companion.agent import WorkspaceAgent

    port, _, host = native
    port._call("test_manual", 4, "其他长文内容。" * 4000 + "全文核验代号：QZ8627")
    session = EditingSession(port, lambda: WorkspaceAgent(live_config(request)))
    session.connect(host, readable=True)
    context = port.agent_context(session.snapshot()["target"]["id"])
    assert "document_text" not in context and "QZ8627" not in context["current_text"]
    before = port._call("test_state")
    session.start("查找这份文档全文末尾的“全文核验代号”，只回答该代号。", agent=True)
    state = wait_for(session)
    assert state["phase"] == "answered" and "QZ8627" in state["answer"], state[
        "message"
    ]
    assert port._call("test_state") == before


@pytest.mark.integration
def test_native_chinese_latin_text_can_be_revised_without_accepting_mixed_format(
    native,
):
    from companion.contracts import CompanionError

    port, target, host = native
    fragment = target.fragments[0]
    port.replace(
        target.id,
        fragment.id,
        fragment.text,
        fragment.text + " [中文反馈]",
        lambda: True,
    )
    fonts = port._call("test_fonts")
    target = port.connect(host)
    fragment = target.fragments[0]
    port.replace(
        target.id, fragment.id, fragment.text, fragment.text + " 再改一次", lambda: True
    )
    revised = port._call("test_fonts")
    assert {k: v for k, v in fonts.items() if k != "Name"} == {
        k: v for k, v in revised.items() if k != "Name"
    }
    port._call("test_mix_font")
    with pytest.raises(CompanionError, match="混合字体"):
        port.connect(host)


@pytest.mark.integration
@pytest.mark.live_api
def test_real_agent_reads_unsaved_reference_and_writes_visible_native_steps(
    native, request, tmp_path
):
    if not request.config.getoption("--live-model"):
        pytest.skip("explicit --live-model required")
    from companion.agent import WorkspaceAgent
    from companion.workspace import LocalWorkspace

    port, _, host = native
    source = tmp_path / "研发预算.docx"
    reference_text = port._call("test_reference", str(source))
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    session = EditingSession(
        port,
        lambda: WorkspaceAgent(live_config(request)),
        lambda: workspace.session(port.read_open_file),
    )
    session.connect(host, readable=True)
    session.start(
        '从 @"研发预算.docx" 读取研发预算金额，以宿主中最新未保存的值为准。'
        "保留当前片段原文，在末尾补充“研发预算为金额万元。”，金额必须来自该文件。逐段处理。",
        agent=True,
    )
    first = wait_for(session)
    assert first["phase"] == "review", first["message"]
    actual = port._call("test_state")
    assert "9876" in actual["paragraphs"][0], actual["paragraphs"][0]
    assert actual["paragraphs"][1] == "Second fixture paragraph."
    assert port._call("test_other_text") == reference_text
    assert first["sources"][0]["file_id"] == source.name
    session.advance("后面段落仍采用最新预算，但这次请在段末追加 [反馈生效]。")
    second = wait_for(session)
    assert second["phase"] == "review", second["message"]
    after = port._call("test_state")
    assert after["paragraphs"][0] == actual["paragraphs"][0]
    assert "9876" in after["paragraphs"][1] and "[反馈生效]" in after["paragraphs"][1]
    assert after["paragraphs"][2] == "Third fixture paragraph."
    assert after["tables"] == after["images"] == 1
    assert port._call("test_other_text") == reference_text
    session.stop()
