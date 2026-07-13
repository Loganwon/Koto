# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from web.local_executor import LocalExecutor


def test_whitelisted_app_launch_is_system_command() -> None:
    assert LocalExecutor.is_system_command("打开微信")
    assert LocalExecutor.is_system_command("open wechat")
    assert not LocalExecutor.is_system_command("打开微信给张三发消息")
    assert not LocalExecutor.is_system_command("怎么打开微信")


def test_whitelisted_app_launch_uses_resolved_target(monkeypatch) -> None:
    launched = []

    monkeypatch.setattr(
        LocalExecutor, "_is_app_running", classmethod(lambda cls, config: False)
    )
    monkeypatch.setattr(
        LocalExecutor,
        "_resolve_app_launch_target",
        classmethod(lambda cls, config: r"C:\Apps\WeChat.exe"),
    )
    monkeypatch.setattr(
        LocalExecutor,
        "_launch_target",
        classmethod(lambda cls, target: launched.append(target)),
    )

    result = LocalExecutor.execute("打开微信")

    assert result["success"] is True
    assert result["action"] == "open_app"
    assert "微信" in result["message"]
    assert launched == [r"C:\Apps\WeChat.exe"]


def test_missing_whitelisted_app_does_not_request_model_retry(monkeypatch) -> None:
    monkeypatch.setattr(
        LocalExecutor, "_is_app_running", classmethod(lambda cls, config: False)
    )
    monkeypatch.setattr(
        LocalExecutor, "_resolve_app_launch_target", classmethod(lambda cls, config: "")
    )

    result = LocalExecutor.execute("打开微信")

    assert result["success"] is False
    assert result["action"] == "open_app"
    assert result["retryable"] is False
