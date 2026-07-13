from web.document_feedback_background import BackgroundProgressBridge


def test_background_bridge_returns_progress_and_result() -> None:
    bridge = BackgroundProgressBridge()

    def work():
        bridge.emit({"stage": "analyzing", "progress": 20})
        return {"success": True}

    bridge.start(work)
    event = bridge.get(timeout=1)
    terminal = bridge.get(timeout=1)
    bridge.join(timeout=1)

    assert event["stage"] == "analyzing"
    assert bridge.is_complete(terminal)
    assert bridge.result == {"success": True}
    assert bridge.error is None
