"""Normal startup must never select a document or restore the retired GUI."""

import sys

from companion import __main__ as entry
from companion.addins import open_wps


def test_normal_entry_only_ensures_existing_embedded_service(
    tmp_path, monkeypatch, capsys
):
    settings = tmp_path / "host.json"
    settings.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        open_wps,
        "ensure_service",
        lambda p: calls.append(p) or "https://127.0.0.1:19742",
    )
    monkeypatch.setattr(
        open_wps,
        "open_pane",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("startup must not control native windows")
        ),
    )
    entry.main(["--settings", str(settings)])
    assert calls == [settings]
    assert "已就绪" in capsys.readouterr().out


def test_missing_installation_does_not_fall_back_to_floating_gui(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(
        open_wps,
        "ensure_service",
        lambda *a: pytest.fail("must not launch with missing settings"),
    )
    with pytest.raises(SystemExit) as error:
        entry.main(["--settings", str(tmp_path / "absent.json")])
    assert error.value.code == 1
