"""Quality limits must survive turns and gate actual outputs, not model claims."""

import threading

from companion.agent_lab.tools import Turn
from companion.tests.test_agent_lab import make_lab


def test_limit_prevents_overlong_write_before_verifier_and_allows_shorter_draft(
    tmp_path,
):
    store, task, broker, _ = make_lab(tmp_path, outputs=("短版.docx", "短版.pptx"))
    assert broker.invoke(
        "set_output_limits",
        {
            "limits": [
                {"file_name": "短版.docx", "max_body_characters": 5},
                {
                    "file_name": "短版.pptx",
                    "max_slide_body_characters": 3,
                    "exact_slide_count": 1,
                },
            ]
        },
    )["ok"]
    measured = broker.invoke(
        "measure_content",
        {
            "format": "docx",
            "file_name": "短版.docx",
            "sections": [{"heading": "标题", "text": "文字超长"}],
        },
    )
    assert measured["metrics"]["body_characters_including_headings_and_tables"] == 6
    assert not measured["validation"]["passed"]
    called = []
    broker.verifier = lambda *a: called.append(True) or {"allowed": True}
    args = {
        "action_id": "long",
        "file_name": "短版.docx",
        "title": "总标题不计入",
        "sections": [{"heading": "标题", "text": "文字超长"}],
    }
    assert not broker.invoke("create_word", args)["ok"]
    assert not called and not (broker.outputs / "短版.docx").exists()
    args.update(action_id="short", sections=[{"heading": "标题", "text": "短文"}])
    assert broker.invoke("create_word", args)["ok"]
    assert broker.invoke(
        "create_presentation",
        {
            "action_id": "slide",
            "file_name": "短版.pptx",
            "title": "标题",
            "sections": [{"heading": "页标题", "text": "短文"}],
        },
    )["ok"]
    assert broker.invoke("complete_task", {"summary": "完成"})["ok"]


def test_completion_rechecks_actual_package_after_a_new_stricter_contract(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("短版.docx",))
    assert broker.invoke(
        "create_word",
        {
            "action_id": "draft",
            "file_name": "短版.docx",
            "title": "标题",
            "sections": [{"heading": "", "text": "一二三四五六"}],
        },
    )["ok"]
    assert broker.invoke("complete_task", {"summary": "初稿完成"})["ok"]
    assert broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "短版.docx", "max_body_characters": 5}]},
    )["ok"]
    assert store.get(task)["phase"] == "active"
    result = broker.invoke("complete_task", {"summary": "声称满足"})
    assert not result["ok"] and "6字" in result["error"]


def test_read_mode_cannot_set_or_relax_limits_and_later_turn_retains_them(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("短版.docx",))
    assert broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "短版.docx", "max_body_characters": 5}]},
    )["ok"]
    n, e = store.begin_turn(task, "只解释", "read")
    broker.bind_turn(Turn(task, n, e, "只解释", "read", threading.Event()))
    assert "set_output_limits" not in {d["name"] for d in broker.definitions()}
    assert not broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "短版.docx", "max_body_characters": 500}]},
    )["ok"]
    measured = broker.invoke(
        "measure_content",
        {"format": "docx", "sections": [{"heading": "", "text": "一二三四五六"}]},
    )
    assert (
        measured["validation"]["file_name"] == "短版.docx"
        and not measured["validation"]["passed"]
    )
    assert store.get(task)["output_limits"]["短版.docx"]["max_body_characters"] == 5


def test_unauthorized_contract_change_does_not_replace_existing_limit(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("短版.docx",))
    assert broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "短版.docx", "max_body_characters": 5}]},
    )["ok"]
    broker.verifier = lambda *a: {
        "allowed": False,
        "reason": "用户没有放宽上限",
        "kind": "permission",
    }
    assert not broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "短版.docx", "max_body_characters": 500}]},
    )["ok"]
    assert store.get(task)["output_limits"]["短版.docx"]["max_body_characters"] == 5


def test_stalled_draft_repair_is_counted_proposal_not_an_automatic_write(tmp_path):
    class Verifier:
        def __call__(self, *args):
            return {"allowed": True}

        def repair_draft(self, turn, arguments, state, validation):
            return {**arguments, "sections": [{"heading": "", "text": "短稿"}]}

    store, task, broker, doc = make_lab(tmp_path, Verifier(), outputs=("短版.docx",))
    broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "短版.docx", "max_body_characters": 5}]},
    )
    args = {
        "file_name": "短版.docx",
        "format": "docx",
        "sections": [{"heading": "", "text": "一二三四五六七八"}],
    }
    for step in (1, 2, 3):
        broker.turn.model_step = step
        result = broker.invoke("measure_content", args)
    assert (
        result["validation"]["passed"]
        and result["original_metrics"]["body_characters_including_headings_and_tables"]
        == 8
    )
    assert result["metrics"]["body_characters_including_headings_and_tables"] == 2
    assert result["proposed_revision"]["sections"][0]["text"] == "短稿"
    assert args["sections"][0]["text"] == "一二三四五六七八"
    assert broker.turn.writes == 0 and not list(broker.outputs.iterdir())
    assert doc.read("0") == "甲方验收后付款。"
    next_tool = result["next_tool"]
    assert broker.invoke(next_tool["name"], next_tool["arguments"])["ok"]
    assert broker.turn.writes == 1
