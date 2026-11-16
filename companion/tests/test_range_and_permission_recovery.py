"""Rejected planning constraints cannot revoke an already-authorized file task."""

from companion.tests.test_agent_lab import make_lab
from companion.agent_lab.output_limits import merge_limits, validate_metrics
from companion.benchmarks.grade import (
    money_present,
    fees_present,
    claims_nonzero_difference,
)


def test_rejected_constraint_can_be_corrected_without_blocking_authorized_mutation(
    tmp_path,
):
    calls = []

    def verifier(turn, tool, args, state):
        calls.append(tool)
        if len(calls) == 1:
            return {
                "allowed": False,
                "kind": "permission",
                "reason": "没有要求固定为五页",
            }
        return {"allowed": True}

    store, task, broker, _ = make_lab(tmp_path, verifier, outputs=("简报.pptx",))
    denied = broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "简报.pptx", "exact_slide_count": 5}]},
    )
    assert not denied["ok"] and not broker.turn.write_denied
    accepted = broker.invoke(
        "set_output_limits",
        {
            "limits": [
                {"file_name": "简报.pptx", "min_slide_count": 3, "max_slide_count": 5}
            ]
        },
    )
    assert accepted["ok"]
    result = broker.invoke(
        "create_presentation",
        {
            "action_id": "four-pages",
            "file_name": "简报.pptx",
            "title": "简报",
            "sections": [{"heading": str(i), "text": "真实内容"} for i in range(4)],
        },
    )
    assert result["ok"]


def test_count_range_replaces_old_exact_policy_and_enforces_both_bounds():
    state = {
        "expected_outputs": ["简报.pptx"],
        "output_limits": {
            "简报.pptx": {"exact_slide_count": 5, "max_slide_body_characters": 45}
        },
    }
    values = merge_limits(
        state, [{"file_name": "简报.pptx", "min_slide_count": 3, "max_slide_count": 4}]
    )["简报.pptx"]
    assert (
        "exact_slide_count" not in values and values["max_slide_body_characters"] == 45
    )
    assert validate_metrics({"slide_count": 3}, values)["passed"]
    assert not validate_metrics({"slide_count": 2}, values)["passed"]
    assert not validate_metrics({"slide_count": 5}, values)["passed"]


def test_independent_money_oracle_accepts_exact_unit_equivalence_not_substrings():
    assert money_present("全年收入935.00万元", 9350000)
    assert money_present("全年收入9,350,000元", 9350000)
    assert not money_present("全年收入928万元", 9350000)
    assert not money_present("全年收入19350000元", 9350000)
    assert fees_present("三档年费12万元、3.99万元、0.99万元")
    assert fees_present("三档年费：12/3.99/0.99万元/年")
    assert not fees_present("三档年费：12/3.99/0.98万元/年")
    assert not money_present("120000万元", 120000)
    assert not money_present("120000%", 120000)


def test_independent_answer_oracle_preserves_negation():
    assert claims_nonzero_difference("资料合计与重新加总有差额，已单列。")
    assert claims_nonzero_difference("资料合计与重新加总存在差额。")
    assert not claims_nonzero_difference("资料合计与重新加总没有差额。")
    assert not claims_nonzero_difference("资料合计与重新加总不存在差额。")
    assert not claims_nonzero_difference("资料合计与重新加总均相等，差额0。")


def test_partial_run_is_not_a_pass_even_without_runtime_errors(tmp_path):
    import json
    from companion.benchmarks.grade import grade

    run = tmp_path / "unfinished"
    run.mkdir()
    (tmp_path / "cases.json").write_text(
        json.dumps({"cross_format_feedback": {"turns": [{}] * 8}}), encoding="utf8"
    )
    (run / "events.json").write_text("[]", encoding="utf8")
    (run / "result.json").write_text(
        json.dumps(
            {
                "engine": "koto",
                "case": "cross_format_feedback",
                "turns": [{"number": 0}],
                "seconds": 10,
            }
        ),
        encoding="utf8",
    )
    value = grade(run, tmp_path)
    assert not value["passed"] and "实际1轮" in value["checks"][0]["detail"]


def test_revision_uses_exact_post_edit_metrics_before_intent_verification(tmp_path):
    seen = []

    def verifier(turn, tool, args, state):
        if tool == "revise_office_text":
            seen.append(state["proposed_metrics"])
        return {"allowed": True}

    store, task, broker, _ = make_lab(tmp_path, verifier, outputs=("简报.pptx",))
    assert broker.invoke(
        "create_presentation",
        {
            "action_id": "make",
            "file_name": "简报.pptx",
            "title": "简报",
            "sections": [{"heading": "不计入正文的标题", "text": "原文"}],
        },
    )["ok"]
    result = broker.invoke("read_artifact", {"file_name": "简报.pptx"})
    block = next(b for b in result["editable_blocks"]["blocks"] if b["text"] == "原文")
    assert broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "简报.pptx", "max_slide_body_characters": 4}]},
    )["ok"]
    args = {
        "action_id": "edit",
        "file_name": "简报.pptx",
        "expected_sha256": result["receipt"]["sha256"],
        "changes": [{"block_id": block["id"], "expected": "原文", "text": "新正文四"}],
    }
    assert broker.invoke("revise_office_text", args)["ok"]
    assert seen[0]["slide_body_characters"] == [4]
    saved = broker.invoke("read_artifact", {"file_name": "简报.pptx"})
    assert saved["metrics"] == seen[0]
    args.update(action_id="too-long", expected_sha256=saved["receipt"]["sha256"])
    args["changes"][0].update(expected="新正文四", text="超过四个字了")
    assert not broker.invoke("revise_office_text", args)["ok"]
    assert len(seen) == 1 and not broker.turn.write_denied
