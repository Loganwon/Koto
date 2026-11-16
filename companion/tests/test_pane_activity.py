"""Only actual operation results may appear as completed native-pane activity."""

from companion.pane_activity import public_activity


def test_model_claims_and_tool_arguments_are_not_public_receipts():
    assert public_activity({"kind": "assistant_message", "body": {"text": "完成"}}) is None
    event = {"seq": 12, "kind": "tool_result", "body": {
        "tool": "read_current_document", "ok": True,
        "arguments": {"api_key": "private"}, "result": "private document text",
    }}
    row = public_activity(event)
    assert row["status"] == "done"
    assert set(row) == {"id", "title", "status"}
    assert "private" not in str(row)


def test_uncertain_or_failed_writes_are_never_presented_as_completed():
    for kind, ok in [("tool_uncertain", True), ("tool_error", True), ("tool_result", False)]:
        row = public_activity({"seq": 7, "kind": kind, "body": {"tool": "apply_edit", "ok": ok}})
        assert row["status"] != "done"


def test_unrecognized_internal_events_stay_out_of_the_user_flow():
    assert public_activity({"seq": 1, "kind": "tool_result", "body": {"tool": "internal", "ok": True}}) is None
