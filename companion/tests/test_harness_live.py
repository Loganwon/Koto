"""Opt-in model evaluation on synthetic data, independent of native fixtures."""

import threading

import pytest

from companion.agent import WorkspaceAgent
from companion.config import config_from_key_file
from companion.model import EditProposal
from companion.reading import TextSnapshot
from companion.workspace import LocalWorkspace


def test_live_agent_reads_calculates_and_proposes_verified_evidence(request, tmp_path):
    if not request.config.getoption("--live-model"):
        pytest.skip("explicit --live-model required")
    path = request.config.getoption("--api-key-file")
    if not path:
        pytest.skip("explicit credential file required")
    (tmp_path / "费用.csv").write_text(
        "项目,万元\n研发,120.1\n运营,79.9", encoding="utf-8"
    )
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    events = []
    references = workspace.session()
    model = WorkspaceAgent(config_from_key_file(path))
    proposal = model.step(
        original="预算待补充。",
        current="预算待补充。",
        instruction='读取 @"费用.csv"，用 calculate 工具核算总额，把当前这句话改成简短的预算总额说明，单位万元。不要只回答，要修改当前文字。',
        feedback=(),
        index=0,
        total=1,
        cancelled=threading.Event(),
        context={"selection": {"active": True, "text": "预算待补充。"}},
        document=TextSnapshot("测试文档", "预算待补充。"),
        references=references,
        progress=lambda name, detail: events.append((name, detail)),
    )
    references.verify()
    assert isinstance(proposal, EditProposal)
    assert "200" in proposal.text and "万元" in proposal.text
    assert any(name == "read_reference_file" for name, _ in events)
    assert any(name == "calculate" for name, _ in events)
    assert references.evidence()[0]["file_id"] == "费用.csv"
    state = [detail for name, detail in events if name == "harness_state"][-1]
    assert state["phase"] == "proposed"
