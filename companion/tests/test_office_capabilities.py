import pytest

from companion.cell_edits import cell_proposal, CellEditProposal
from companion.contracts import CompanionError, DocumentTarget, Fragment
from companion.file_readers import parse_file
from companion.session import EditingSession
from companion.editor_profiles import editor_profile
from companion.reading import TextSnapshot
from companion.workspace import LocalWorkspace
import json
import threading
from companion.tests.test_session import Documents, settled
from companion.tests.test_workspace_agent import agent_for


@pytest.mark.parametrize(
    "kind,value",
    [
        ("formula", '=WEBSERVICE("https://example.test")'),
        ("formula", "='[other.xlsx]Sheet1'!A1"),
        ("formula", "=SUM(A1:A2)|cmd"),
        ("text", "=SUM(A1:A2)"),
        ("number", "12万元"),
        ("number", "1234567890123456"),
        ("boolean", "yes"),
    ],
)
def test_typed_cell_contract_rejects_implicit_execution_or_precision_loss(kind, value):
    with pytest.raises(CompanionError):
        cell_proposal(kind, value, "检查")


@pytest.mark.parametrize(
    "kind,value",
    [
        ("formula", "=SUM(B2:B3)"),
        ("formula", "=IF(A1>0,ROUND(A1*1.1,2),0)"),
        ("number", "-120.1"),
        ("boolean", "false"),
        ("text", "研发预算"),
    ],
)
def test_typed_cell_contract_preserves_the_requested_type(kind, value):
    proposal = cell_proposal(kind, value, "检查")
    assert proposal.value_type == kind and proposal.value == value


def test_agent_repairs_invalid_cell_formula_before_proposing_a_write():
    def repaired(payload):
        error = json.loads(
            [m["content"] for m in payload["messages"] if m["role"] == "tool"][-1]
        )
        assert error["recoverable"] is True and "尚未执行" in error["instruction"]
        from companion.tests.test_workspace_agent import response

        return response(
            (
                "set_current_cell",
                {
                    "value_type": "formula",
                    "value": "=SUM(B2:B3)",
                    "note": "保留本地公式",
                },
            )
        )

    model, requests = agent_for(
        [
            [
                (
                    "set_current_cell",
                    {
                        "value_type": "formula",
                        "value": '=WEBSERVICE("https://example.test")',
                        "note": "公式",
                    },
                )
            ],
            repaired,
        ]
    )
    proposal = model.step(
        original="200",
        current="200",
        instruction="填写本工作簿的合计公式",
        feedback=(),
        index=0,
        total=1,
        cancelled=threading.Event(),
        context={},
        document=TextSnapshot("预算.xlsx", "研发120.1，运营79.9"),
        references=LocalWorkspace().session(),
        progress=lambda *events: None,
        editor=editor_profile("excel", Fragment("c0", "200", kind="cell")),
    )
    assert isinstance(proposal, CellEditProposal) and proposal.value == "=SUM(B2:B3)"
    assert len(requests) == 3  # goal handshake + invalid and repaired formulas


def test_skip_keeps_header_and_user_feedback_advances_to_next_cell():
    class Cells(Documents):
        def connect(self, host):
            return DocumentTarget(
                "pinned-document",
                "excel",
                "费用.xlsx",
                "选中单元格",
                tuple(
                    Fragment(k, v, label=k, kind="cell") for k, v in self.text.items()
                ),
            )

        def replace_cell(self, target, fragment, expected, kind, value, permitted):
            assert kind == "number"
            return self.replace(target, fragment, expected, value, permitted)

    documents = Cells()
    model, _ = agent_for(
        [
            [("skip_current_fragment", {"reason": "表头保留"})],
            [
                (
                    "set_current_cell",
                    {"value_type": "number", "value": "200", "note": "合计"},
                )
            ],
        ]
    )
    session = EditingSession(documents, lambda: model)
    session.submit("保留表头，填写下一格")
    state = settled(session)
    assert (
        state["phase"] == "review"
        and state["latest"]["kind"] == "skipped"
        and not documents.writes
    )
    session.advance("填写200")
    assert (
        settled(session)["phase"] == "review"
        and documents.writes == ["two"]
        and documents.text["one"] == "first original"
    )


def test_pptx_reference_reads_slide_order_table_and_notes(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    for label in ["甲项目", "乙项目"]:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = (
            label
        )
        table = slide.shapes.add_table(
            1, 2, Inches(1), Inches(2), Inches(5), Inches(1)
        ).table
        table.cell(0, 0).text = "研发"
        table.cell(0, 1).text = "9876万元"
        slide.notes_slide.notes_text_frame.text = "这页备注需读取。"
    path = tmp_path / "项目.pptx"
    presentation.save(path)
    snapshot = parse_file(path)
    assert snapshot.text.index("甲项目") < snapshot.text.index("乙项目")
    assert "9876万元" in snapshot.text and "这页备注需读取" in snapshot.text
    assert any("备注" in value for value in snapshot.coverage)
    assert any("SmartArt" in value for value in snapshot.limitations)
