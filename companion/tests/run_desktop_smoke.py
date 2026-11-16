"""Opt-in real WebView + API + native host smoke; uses marked test documents."""

import argparse
import json
from pathlib import Path
import tempfile
import threading
import time

from dotenv import dotenv_values

from companion.desktop import CompanionAPI
from companion.model import ModelConfig
from companion.tests.test_native_live import NativeFixture
from companion.workspace import LocalWorkspace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=["word", "wps"], default="word")
    parser.add_argument("--api-key-file")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.api_key_file:
        from companion.config import config_from_key_file

        config = config_from_key_file(args.api_key_file)
    else:
        values = dotenv_values(root / "config" / "deepseek_config.env")
        key = values.get("DEEPSEEK_API_KEY")
        if not key:
            raise SystemExit(
                "A configured DeepSeek key is required for this opt-in smoke test."
            )
        config = ModelConfig("https://api.deepseek.com", "deepseek-chat", key)
    import webview

    directory = Path(tempfile.mkdtemp(prefix="koto-companion-smoke-"))
    documents = NativeFixture(directory)
    workspace = LocalWorkspace(
        excluded=[args.api_key_file] if args.api_key_file else []
    )
    workspace.open(directory)
    api = CompanionAPI(config, documents, workspace)
    window = webview.create_window(
        "Koto 原生协作验证",
        url=str(root / "companion" / "ui" / "legacy" / "index.html"),
        js_api=api,
        width=410,
        height=760,
    )
    api._window = window
    outcome = {}

    def wait_for(expression, expected, timeout=85):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if window.evaluate_js(expression) == expected:
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise AssertionError("Desktop state did not settle: " + expression)

    def run():
        try:
            outcome["stage"] = "window_ready"
            assert window.events.loaded.wait(25)
            wait_for(
                "document.getElementById('api-status').textContent", "DeepSeek", 15
            )
            before_width, before_x = window.width, window.x
            before_chat = window.evaluate_js(
                "document.querySelector('.assistant').getBoundingClientRect().width"
            )
            window.evaluate_js("document.getElementById('files-toggle').click()")
            wait_for("document.getElementById('files-pane').hidden", False, 15)
            assert window.width == before_width + 224
            assert (
                abs(
                    window.evaluate_js(
                        "document.querySelector('.assistant').getBoundingClientRect().width"
                    )
                    - before_chat
                )
                <= 2
            )
            window.evaluate_js("document.getElementById('files-close').click()")
            wait_for("document.getElementById('files-pane').hidden", True, 15)
            assert window.width == before_width
            outcome["outward_drawer"] = True
            window.evaluate_js(
                "document.getElementById('host').value="
                + json.dumps(args.host)
                + ";document.getElementById('connect').click()"
            )
            wait_for("document.getElementById('phase-label').textContent", "可以开始")
            window.evaluate_js(
                "document.getElementById('host').dispatchEvent(new Event('change'))"
            )
            wait_for(
                "document.getElementById('follow-status').textContent", "实时跟随", 15
            )
            wait_for("document.getElementById('start').disabled", False, 15)
            outcome["stage"] = "first_fragment"
            request = "在当前段落末尾追加 [首轮核验]，其他内容不变。"
            window.evaluate_js(
                "document.getElementById('instruction').value="
                + json.dumps(request)
                + ";document.getElementById('start').click()"
            )
            wait_for(
                "document.getElementById('phase-label').textContent", "正在处理", 10
            )
            documents._call(
                "test_manual", 4, "Manual input while the real model is pending"
            )
            wait_for("document.getElementById('phase-label').textContent", "等你检查")
            first = documents._call("test_state")
            assert "[首轮核验]" in first["paragraphs"][0]
            assert first["paragraphs"][1] == "Second fixture paragraph."
            outcome["stage"] = "feedback"
            feedback = (
                "后续段落只在末尾追加 [反馈已生效]，不要追加首轮核验，其他内容不变。"
            )
            window.evaluate_js(
                "document.getElementById('instruction').value="
                + json.dumps(feedback)
                + ";document.getElementById('continue').click()"
            )
            wait_for(
                "document.getElementById('progress').textContent", "已显示 2 / 3 段"
            )
            window.evaluate_js("document.getElementById('stop').click()")
            wait_for("document.getElementById('phase-label').textContent", "已停止")
            outcome["stage"] = "verify_results"
            actual = documents._call("test_state")
            outcome["native"] = actual
            assert actual["paragraphs"][0] == first["paragraphs"][0]
            assert "[反馈已生效]" in actual["paragraphs"][1]
            assert "[首轮核验]" not in actual["paragraphs"][1]
            assert actual["paragraphs"][2] == "Third fixture paragraph."
            assert (
                actual["paragraphs"][3]
                == "Manual input while the real model is pending"
            )
            assert actual["tables"] == actual["images"] == 1
            outcome["stage"] = "live_table_context"
            documents._call("test_select_cell", 2, 2)
            wait_for(
                "document.getElementById('scope').textContent.includes('第 2 行')",
                True,
                15,
            )
            wait_for("document.getElementById('source-text').textContent", "120", 15)
            window.evaluate_js("document.getElementById('source-preview').open=true")
            wait_for("document.querySelectorAll('#table-preview td').length", 4, 15)
            outcome["live_context"] = True
            window.evaluate_js(
                "document.getElementById('instruction').value='只根据表格回答：研发对应的金额是多少？请写出项目名称和金额。';document.getElementById('start').click()"
            )
            wait_for("document.getElementById('phase-label').textContent", "已回答")
            answer = window.evaluate_js("document.getElementById('answer').textContent")
            assert "120" in answer and "研发" in answer
            assert documents._call("test_state") == actual
            outcome["table_answer"] = answer
            outcome["stage"] = "cross_file_agent"
            source = directory / "研发预算.docx"
            source_text = documents._call("test_reference", str(source))
            documents._call("test_select_paragraph", 1)
            window.evaluate_js(
                "document.getElementById('files-toggle').click();document.getElementById('refresh-files').click()"
            )
            wait_for(
                "document.querySelectorAll('#file-tree .reference-file').length", 1, 15
            )
            window.evaluate_js(
                "document.querySelector('#file-tree .reference-file').click()"
            )
            assert "研发预算.docx" in window.evaluate_js(
                "document.getElementById('instruction').value"
            )
            window.evaluate_js(
                "document.getElementById('instruction').value='读取 @\"研发预算.docx\" 中最新尚未保存的研发预算金额，保留当前段落原文，并在末尾补充该金额，单位万元。';document.getElementById('start').click()"
            )
            wait_for("document.getElementById('phase-label').textContent", "等你检查")
            cross = documents._call("test_state")
            assert "9876" in cross["paragraphs"][0]
            assert cross["paragraphs"][1:] == actual["paragraphs"][1:]
            assert documents._call("test_other_text") == source_text
            outcome["cross_file"] = {
                "passed": True,
                "source": source.name,
                "latest_unsaved_value": 9876,
            }
            actual = cross
            output = documents._call("test_save")
            outcome.update(
                passed=True, host=args.host, native=actual, result_file=output
            )
        except Exception as error:
            outcome.update(
                passed=False, host=args.host, error=str(error) or type(error).__name__
            )
            if api._session:
                outcome["session"] = api._session.snapshot()
            try:
                outcome["ui_error"] = window.evaluate_js(
                    "document.getElementById('error').textContent"
                )
            except Exception:
                pass
            try:
                outcome["native"] = documents._call("test_state")
            except Exception:
                pass
        finally:
            try:
                documents._call("test_cleanup")
            except Exception:
                pass
            api._close()
            documents.close()
            documents._thread.join(timeout=30)
            window.destroy()

    webview.start(run, debug=False)
    evidence = root / ".pytest_tmp" / ("companion-desktop-" + args.host + ".json")
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text(
        json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "passed": outcome.get("passed"),
                "host": args.host,
                "evidence": str(evidence),
            },
            ensure_ascii=False,
        )
    )
    if not outcome.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
