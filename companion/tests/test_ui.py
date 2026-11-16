"""Production HTML/JS connected to the real session API and a memory document."""

import json
import threading
from copy import deepcopy
from pathlib import Path

import pytest

from companion.contracts import DocumentConflict, DocumentTarget, Fragment
from companion.desktop import CompanionAPI
from companion.model import EditProposal, ModelConfig
from companion.agent import AnswerProposal


class MemoryDocument:
    def __init__(self):
        self.content = {"a": "原始第一段。", "b": "原始第二段。"}

    def connect(self, host):
        return DocumentTarget(
            "ui-doc",
            host,
            "界面测试.docx",
            "已选文字",
            tuple(Fragment(k, v) for k, v in self.content.items()),
            "C:\\long-folder\\" + "子目录" * 30 + "\\界面测试.docx",
        )

    def read(self, target, fragment):
        return self.content[fragment]

    def replace(self, target, fragment, expected, replacement, permitted):
        if self.content[fragment] != expected:
            raise DocumentConflict("conflict")
        assert permitted()
        self.content[fragment] = replacement
        return replacement

    def locate(self, *args):
        pass

    def close(self):
        pass


class Model:
    def step(self, **kwargs):
        if kwargs["instruction"] == "研发金额是多少？":
            return AnswerProposal(self.answer(**kwargs))
        return self.propose(**kwargs)

    def propose(self, **kwargs):
        return EditProposal(
            kwargs["current"] + " 已修改。", "更简洁 <img src=x onerror=alert(1)>"
        )

    def answer(self, **kwargs):
        amount = kwargs["context"]["tables"][0]["cells"][-1]["text"]
        return "研发金额为" + amount + "。"


class LiveMemoryDocument(MemoryDocument):
    def __init__(self):
        super().__init__()
        self.live = {
            "watching": True,
            "connected": True,
            "revision": 1,
            "host": "word",
            "name": "项目预算.docx",
            "saved": False,
            "path": "C:/工作文档/项目预算.docx",
            "location": "第 2 段",
            "document_chars": 120,
            "selection": {"active": False},
            "current_text": "项目拟于本月开始，详细预算见下表。",
            "activity": [{"text": "文档内容已更新"}],
            "table_count": 1,
            "tables": [
                {
                    "label": "表格 1",
                    "cells": [
                        {"row": 1, "column": 1, "text": "项目"},
                        {"row": 1, "column": 2, "text": "金额"},
                        {"row": 2, "column": 1, "text": "研发"},
                        {"row": 2, "column": 2, "text": "120"},
                    ],
                }
            ],
        }

    def observation(self):
        return deepcopy(self.live)

    def watch(self, host, enabled):
        self.live["watching"] = enabled

    def read_current(self, host):
        return deepcopy(self.live)

    def context(self, target_id):
        return deepcopy(self.live)


def test_desktop_ui_feedback_flow_and_small_window(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.is_file():
        pytest.skip("Edge required for the local browser smoke test")
    documents = MemoryDocument()
    api = CompanionAPI(
        ModelConfig("https://example.test", "test-model", "secret"), documents
    )
    api._get_session()._model_factory = Model
    errors = []

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(edge), headless=True)
        page = browser.new_page(viewport={"width": 410, "height": 850})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.expose_function(
            "companionCall", lambda name, args: getattr(api, name)(*args)
        )
        page.add_init_script(
            """window.pywebview={api:Object.fromEntries(['status','watch','submit','connect','start','advance','revise','stop','locate','configure'].map(name=>[name,(...args)=>window.companionCall(name,args)]))};"""
        )
        page.goto((Path(__file__).resolve().parents[1] / "ui" / "legacy" / "index.html").as_uri())
        playwright.expect(page.locator("#api-status")).to_have_text("test-model")
        page.locator("#instruction").fill("逐段润色，每段让我检查。")
        page.locator("#start").click()
        playwright.expect(page.locator("#phase-label")).to_have_text(
            "等你检查", timeout=7000
        )
        playwright.expect(page.locator("#target-name")).to_have_text("界面测试.docx")
        assert documents.content["a"].endswith("已修改。")
        assert documents.content["b"] == "原始第二段。"
        assert page.locator("#edit-note img").count() == 0
        page.locator("#instruction").fill("后面先说结论")
        page.locator("#continue").click()
        playwright.expect(page.locator("#progress")).to_have_text(
            "已显示 2 / 2 段", timeout=7000
        )
        page.locator("#continue").click()
        playwright.expect(page.locator("#phase-label")).to_have_text("本轮完成")
        for width in (350, 410):
            page.set_viewport_size({"width": width, "height": 850})
            dimensions = page.evaluate(
                "({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})"
            )
            assert dimensions["scroll"] <= dimensions["width"]
        page.screenshot(path=str(tmp_path / "companion-ui.png"), full_page=True)
        assert not errors, errors
        browser.close()
    api._close()


def test_enter_sends_immediate_feedback_and_same_button_stops(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.is_file():
        pytest.skip("Edge required")
    binding, release, started, finish = [threading.Event() for _ in range(4)]

    class WaitingDocument(LiveMemoryDocument):
        def bind_current(self, host):
            binding.set()
            assert release.wait(8)
            return self.connect("word")

    class StreamingModel:
        def step(self, **kwargs):
            kwargs["progress"]("answer_delta", "**重点**：这是正在出现的回答。")
            started.set()
            assert finish.wait(8)
            return AnswerProposal("完整回答，不应在停止后确认。")

    documents = WaitingDocument()
    api = CompanionAPI(
        ModelConfig("https://example.test", "test", "never-show-the-key"),
        documents,
        key_source="DS_KEY.txt",
    )
    api._get_session()._model_factory = StreamingModel
    errors = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(edge), headless=True)
        page = browser.new_page(viewport={"width": 430, "height": 700})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.expose_function(
            "companionCall", lambda name, args: getattr(api, name)(*args)
        )
        page.add_init_script(
            "window.pywebview={api:Object.fromEntries(['status','watch','submit','connect','advance','revise','stop','locate','configure'].map(name=>[name,(...args)=>window.companionCall(name,args)]))};"
        )
        page.goto((Path(__file__).resolve().parents[1] / "ui" / "legacy" / "index.html").as_uri())
        playwright.expect(page.locator("#api-status")).to_have_text("test")
        page.locator("#instruction").fill("总结选中的内容")
        page.locator("#instruction").press("Enter")
        playwright.expect(page.locator("#task-request")).to_have_text(
            "总结选中的内容", timeout=1000
        )
        playwright.expect(page.locator("#start")).to_have_attribute(
            "aria-label", "停止", timeout=1000
        )
        assert binding.is_set()
        release.set()
        playwright.expect(page.locator("#answer strong")).to_have_text(
            "重点", timeout=2000
        )
        assert started.is_set() and api._session.snapshot()["busy"]
        page.locator("#start").click()
        finish.set()
        playwright.expect(page.locator("#phase-label")).to_have_text("已停止")
        playwright.expect(page.locator("#message")).to_be_visible()
        assert "完整回答" not in page.locator("#answer").inner_text()
        assert documents.content == {"a": "原始第一段。", "b": "原始第二段。"}
        page.locator("#api-status").click()
        playwright.expect(page.locator("#connection-summary")).to_contain_text(
            "DS_KEY.txt"
        )
        assert page.locator("#api-key").input_value() == ""
        assert "never-show-the-key" not in page.locator("body").inner_text()
        assert not errors
        browser.close()
    api._close()


def test_live_ui_updates_table_answers_without_manual_bind_and_keeps_composer_visible(
    tmp_path,
):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.is_file():
        pytest.skip("Edge required")
    documents = LiveMemoryDocument()
    api = CompanionAPI(ModelConfig("https://example.test", "test", "secret"), documents)
    api._get_session()._model_factory = Model
    errors = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(edge), headless=True)
        page = browser.new_page(viewport={"width": 410, "height": 760})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.expose_function(
            "companionCall", lambda name, args: getattr(api, name)(*args)
        )
        page.add_init_script(
            "window.pywebview={api:Object.fromEntries(['status','watch','submit','connect','advance','revise','stop','locate','configure'].map(name=>[name,(...args)=>window.companionCall(name,args)]))};"
        )
        page.goto((Path(__file__).resolve().parents[1] / "ui" / "legacy" / "index.html").as_uri())
        playwright.expect(page.locator("#target-name")).to_have_text("项目预算.docx")
        playwright.expect(page.locator("#follow-status")).to_have_text("实时跟随")
        assert api._session.snapshot()["phase"] == "idle"
        page.screenshot(path=str(tmp_path / "companion-welcome.png"))
        page.locator("#source-preview summary").click()
        playwright.expect(page.locator("#table-preview td").last).to_have_text("120")
        documents.live["revision"] += 1
        documents.live["current_text"] = "手动新增的进度：研发已开始。"
        documents.live["saved"] = True
        documents.live["tables"][0]["cells"][-1]["text"] = "150"
        playwright.expect(page.locator("#source-text")).to_have_text(
            "手动新增的进度：研发已开始。"
        )
        playwright.expect(page.locator("#save-state")).to_have_text("已保存")
        playwright.expect(page.locator("#table-preview td").last).to_have_text("150")
        page.locator("#instruction").fill("研发金额是多少？")
        page.locator("#start").click()
        playwright.expect(page.locator("#answer")).to_have_text("研发金额为150。")
        assert documents.content == {"a": "原始第一段。", "b": "原始第二段。"}
        for width, height in ((350, 480), (410, 760)):
            page.set_viewport_size({"width": width, "height": height})
            bounds = page.locator("#start").bounding_box()
            assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "companion-table-answer.png"))
        page.locator("#api-status").click()
        page.locator("#watch-toggle").click()
        playwright.expect(page.locator("#follow-status")).to_have_text("跟随已暂停")
        page.locator("#watch-toggle").click()
        playwright.expect(page.locator("#follow-status")).to_have_text("实时跟随")
        page.locator("#base-url").fill("not-a-url")
        page.locator("#save-settings").click()
        playwright.expect(page.locator("#settings-error")).to_be_visible()
        assert not errors, errors
        browser.close()
    api._close()
