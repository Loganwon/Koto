from unittest.mock import Mock

from src import model_install_compatibility as compatibility


def test_compatible_model_does_not_change_installer_state(monkeypatch):
    monkeypatch.setattr(
        compatibility,
        "inspect_model_compatibility",
        lambda _tag: {"compatible": True},
    )
    set_error = Mock()

    rejected = compatibility.reject_incompatible_model(
        "model:latest",
        set_error=set_error,
        log=Mock(),
        schedule=Mock(),
        show_error=Mock(),
        restore_actions=Mock(),
    )

    assert rejected is False
    set_error.assert_not_called()


def test_incompatible_model_reports_and_restores_actions(monkeypatch):
    monkeypatch.setattr(
        compatibility,
        "inspect_model_compatibility",
        lambda _tag: {
            "compatible": False,
            "current_version": "0.1.0",
            "required_version": "0.2.0",
        },
    )
    callbacks = []
    set_error = Mock()
    log = Mock()
    show_error = Mock()
    restore_actions = Mock()

    rejected = compatibility.reject_incompatible_model(
        "model:latest",
        set_error=set_error,
        log=log,
        schedule=callbacks.append,
        show_error=show_error,
        restore_actions=restore_actions,
    )
    for callback in callbacks:
        callback()

    assert rejected is True
    set_error.assert_called_once_with()
    assert "Ollama 0.1.0" in log.call_args.args[0]
    show_error.assert_called_once()
    assert "0.2.0" in show_error.call_args.args[1]
    restore_actions.assert_called_once_with()
