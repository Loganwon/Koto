"""Reference ablations need equal mechanical write access, without Koto critics."""

from companion.agent_lab.evaluate_comparison import session
from companion.model import ModelConfig


def test_reference_tools_can_publish_and_complete_while_read_mode_cannot(tmp_path):
    (tmp_path / "references").mkdir()
    s = session(
        tmp_path,
        "upstream-deepagents",
        ModelConfig("https://example.test", "test", "synthetic-only"),
        goal="生成预算.xlsx",
        outputs=("预算.xlsx",),
    )

    def run(broker, prompt, message):
        created = broker.invoke(
            "create_workbook",
            {
                "action_id": "make",
                "file_name": "预算.xlsx",
                "sheets": [{"name": "预算", "rows": [["金额"], [54]]}],
            },
        )
        assert created["ok"], created
        assert broker.invoke("complete_task", {"summary": "完成"})["ok"]
        return "完成"

    s.engine.run = run
    try:
        result = s.send("生成预算.xlsx")
        assert result["state"]["phase"] == "complete"
        assert (tmp_path / "outputs/预算.xlsx").exists()
        assert not result["state"].get("contract_required")

        def readonly(broker, prompt, message):
            assert not broker.invoke(
                "create_workbook",
                {
                    "action_id": "bad",
                    "file_name": "预算.xlsx",
                    "sheets": [{"name": "预算", "rows": [[1]]}],
                },
            )["ok"]
            return "只回复"

        s.engine.run = readonly
        s.send("只回答，不修改", mode="read")
    finally:
        s.close()
        s.store.close()
