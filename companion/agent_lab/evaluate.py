"""Real-model comparison. Synthetic fixtures only; no native Office windows."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
import html
import json
from pathlib import Path
import random
import subprocess
import sys
import time

from companion.agent import WorkspaceAgent
from companion.config import config_from_key_file
from companion.contracts import DocumentTarget, Fragment
from companion.file_actions import FileActions
from companion.journal import EventJournal
from companion.reading import TextSnapshot
from companion.session import EditingSession
from companion.tests.run_agent_evaluation import wait_for_session
from companion.workspace import LocalWorkspace
from .cli import open_session
from .tools import JsonDocument


class Legacy:
    """Unmodified installed Agent/session, using the same lab document and files."""

    def __init__(self, folder, config, goal):
        class Port:
            def bind_current(port, host):
                return DocumentTarget(
                    "lab",
                    "word",
                    "隔离评测.docx",
                    "选区",
                    tuple(Fragment(k, v) for k, v in self.document.contents().items()),
                    str(folder / "document.json"),
                )

            def read(port, target, fragment):
                return self.document.read(fragment)

            def replace(port, target, fragment, expected, text, permitted):
                return self.document.replace(fragment, expected, text, permitted)

            def text_snapshot(port, target):
                return TextSnapshot(
                    "隔离评测.docx", "\n".join(self.document.contents().values())
                )

        self.document = JsonDocument(
            folder / "document.json", ["甲方将在全部验收完成之后再进行付款。"]
        )
        self.workspace = LocalWorkspace()
        self.workspace.open(folder / "references")
        out = LocalWorkspace()
        out.open(folder / "outputs")
        self.port = Port()
        self.journal = EventJournal(folder / "legacy.sqlite3")
        self.session = EditingSession(
            self.port,
            lambda: WorkspaceAgent(config),
            self.workspace.session,
            journal=self.journal,
            file_actions=FileActions(out, self.port),
        )
        self.goal = goal
        self.started = False
        self.runs = []

    def send(self, message, *, mode="auto", acknowledge=False):
        if not self.started:
            self.session.submit(self.goal)
            self.started = True
        elif acknowledge:
            self.session.advance(message)
        elif self.session.snapshot()["can_revise"]:
            self.session.revise(message)
        else:
            self.session.submit(message)
        state, timing = wait_for_session(self.session, 180)
        result = {
            "answer": state["answer"],
            "state": state,
            "seconds": timing["completed_seconds"],
        }
        self.runs.append(result)
        return result

    def close(self):
        self.session.stop()
        self.journal.close()


class Candidate:
    def __init__(self, folder, engine, config, goal, expected=(), compact=None):
        self.session = open_session(
            folder,
            engine,
            config,
            goal=goal,
            expected_outputs=expected,
            compact_messages=compact,
        )
        self.document = self.session.broker.document
        self.runs = []

    def send(self, *args, **kwargs):
        result = self.session.send(*args, **kwargs)
        self.runs.append(result)
        return result

    def close(self):
        self.session.close()
        self.session.store.close()


def fixture(folder, paragraphs=None):
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "references").mkdir()
    (folder / "outputs").mkdir()
    JsonDocument(
        folder / "document.json", paragraphs or ["甲方将在全部验收完成之后再进行付款。"]
    )
    (folder / "references/项目.json").write_text(
        json.dumps(
            {
                "项目": "云杉",
                "营收万元": 378.5,
                "审计": "尚未经审计",
                "站点": 31,
                "研发万元": 123.45,
                "运营万元": 67.89,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def run(engine, case, root, config, key_file):
    folder = root / engine / case
    fixture(folder)
    driver = None
    checks = {}
    started = time.monotonic()
    extra = {}

    def make(goal, expected=(), compact=None):
        nonlocal driver
        driver = (
            Legacy(folder, config, goal)
            if engine == "legacy"
            else Candidate(folder, engine, config, goal, expected, compact)
        )
        return driver

    try:
        if case in ("readonly_continuity", "readonly_then_edit"):
            goal = (
                "精简当前这句，保留验收后付款的关系。改完等我检查。"
                if case == "readonly_continuity"
                else "这句稍后需要对外发布。现在只回复收到，不改正文。"
            )
            d = make(goal)
            first = d.send(goal)
            before = d.document.contents()
            checks["首轮行为符合要求"] = (
                (before["0"] != "甲方将在全部验收完成之后再进行付款。")
                if case == "readonly_continuity"
                else before["0"] == "甲方将在全部验收完成之后再进行付款。"
            )
            d.send(
                "本轮以后对外统一称‘客户方’，不用‘甲方’。先记住，只回复收到，不修改正文。"
            )
            for i in range(1, 7):
                d.send(f"这是第{i}次追问。只回复‘已记录{i}’，不要修改正文。")
                checks[f"只读追问{i}零修改"] = d.document.contents() == before
            d.send(
                "现在按之前约定的称呼正式改好当前句子，保留验收后付款关系。",
                acknowledge=engine != "legacy",
            )
            after = d.document.contents()["0"]
            checks["保留长期称呼约束"] = "客户方" in after and "甲方" not in after
        elif case == "multiple_files":
            goal = "读取项目.json，生成摘要.docx、预算.xlsx和汇报.pptx。摘要保留营收和审计状态；预算列研发、运营及合计，金额保持数字；PPT恰好3页，包含站点数。当前正文不改。"
            d = make(goal, ("摘要.docx", "预算.xlsx", "汇报.pptx"))
            before = d.document.contents()
            d.send(goal)
            checks["当前正文未改"] = d.document.contents() == before
            for name in ("摘要.docx", "预算.xlsx", "汇报.pptx"):
                checks[name + "真实生成"] = (folder / "outputs" / name).is_file()
            if all(checks.values()):
                from companion.file_readers import parse_file
                from openpyxl import load_workbook
                from pptx import Presentation

                text = parse_file(folder / "outputs/摘要.docx").text
                checks["摘要事实保留"] = "378.5" in text and "尚未经审计" in text
                wb = load_workbook(folder / "outputs/预算.xlsx")
                rows = list(wb.active.values)
                wb.close()
                checks["数值合计正确"] = any(
                    any(type(v) in (int, float) and abs(v - 191.34) < 1e-7 for v in row)
                    for row in rows
                )
                checks["PPT三页"] = (
                    len(Presentation(folder / "outputs/汇报.pptx").slides) == 3
                )
        elif case == "single_checkpoint_restart":
            goal = "先把唯一选中段落改成‘本项目预算86.2万元。’，等我检查。确认后再生成摘要.docx，正文用同一句。"
            d = make(goal, ("摘要.docx",))
            d.send(goal)
            checks["先改唯一段落"] = d.document.read("0") == "本项目预算86.2万元。"
            checks["确认前未提前生成"] = not (folder / "outputs/摘要.docx").exists()
            if engine == "legacy":
                d.send("确认了，继续完成最初要求的后续工作。", acknowledge=True)
            else:
                task = d.session.task
                d.close()
                driver = None
                cmd = [
                    sys.executable,
                    "-m",
                    "companion.agent_lab.cli",
                    "--directory",
                    str(folder),
                    "--engine",
                    engine,
                    "--api-key-file",
                    str(key_file),
                    "--task",
                    task,
                    "--message",
                    "确认了，继续完成最初要求的后续工作。",
                    "--acknowledge",
                ]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", timeout=180
                )
                checks["新进程恢复无错误"] = result.returncode == 0
                if result.returncode == 0:
                    restored = json.loads(result.stdout)
                    checks["恢复后完整任务已确认完成"] = (
                        restored["state"]["phase"] == "complete"
                    )
                (folder / "restart-output.json").write_text(
                    (
                        result.stdout
                        if result.returncode == 0
                        else json.dumps(
                            {
                                "error": result.stderr[-2000:].replace(
                                    config.api_key, "[redacted]"
                                )
                            }
                        )
                    ),
                    encoding="utf-8",
                )
                extra["actual_process_restart"] = True
                extra["first_process_runs"] = d.runs
            checks["确认后生成原任务文件"] = (folder / "outputs/摘要.docx").is_file()
        elif case == "real_word_table":
            goal = "读取项目.json，生成预算说明.docx，包含真正的三行两列Word表格：项目/万元、研发/123.45、运营/67.89。不得用纯文字或Markdown代替。当前正文不改。"
            d = make(goal, ("预算说明.docx",))
            before = d.document.contents()
            d.send(goal)
            checks["正文未改"] = d.document.contents() == before
            path = folder / "outputs/预算说明.docx"
            checks["真实文件存在"] = path.exists()
            if path.exists():
                from docx import Document

                doc = Document(path)
                checks["真实表格内容准确"] = len(doc.tables) == 1 and [
                    [c.text for c in row.cells] for row in doc.tables[0].rows
                ] == [["项目", "万元"], ["研发", "123.45"], ["运营", "67.89"]]
        elif case == "recoverable_error":
            goal = "读取项目.json，生成预算.xlsx，列出研发、运营和合计的数值。遇到临时失败可修正重试，当前正文不改。"
            d = make(goal, ("预算.xlsx",))
            before = d.document.contents()
            if engine != "legacy":
                # Cover every creation tool. The model may legitimately use
                # create_workbook instead of the older create_spreadsheet.
                original = d.session.broker._run
                fault = [True]

                def temporary(name, args):
                    from companion.contracts import CompanionError

                    if name.startswith("create_") and fault[0]:
                        fault[0] = False
                        raise CompanionError(
                            "评测注入：本次生成暂时失败，尚未创建文件，可以重试。"
                        )
                    return original(name, args)

                d.session.broker._run = temporary
                extra["injected_failure"] = True
            else:
                extra["injected_failure"] = False
            d.send(goal)
            checks["正文未改"] = d.document.contents() == before
            checks["恢复后有真实输出"] = (folder / "outputs/预算.xlsx").exists()
            if engine != "legacy":
                checks["错误被处理并继续"] = not fault[0]
        elif case == "long_chain":
            generator = random.Random(7319)
            ids = [f"资料-{generator.getrandbits(40):010x}.json" for _ in range(20)]
            amounts = [generator.randrange(100, 9999) for _ in ids]
            for i, name in enumerate(ids):
                (folder / "references" / name).write_text(
                    json.dumps(
                        {
                            "项目": f"P{i+1}",
                            "万元": str(Decimal(amounts[i]) / 100),
                            "next": ids[i + 1] if i + 1 < len(ids) else None,
                            "签章": "COMPLETE-7319" if i + 1 == len(ids) else None,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            goal = f"从{ids[0]}开始，严格按每份资料的next顺序核对整条链，不能跳过中间资料，直到next为空。逐项记录各项目预算（万元）并核算合计；末份有签章，把签章写入表中。生成合计.xlsx，金额保持数字，当前正文不改。"
            d = make(
                goal, ("合计.xlsx",), compact=16 if engine == "deepagents" else None
            )
            before = d.document.contents()
            d.send(goal)
            checks["正文未改"] = d.document.contents() == before
            path = folder / "outputs/合计.xlsx"
            checks["全部资料处理后生成文件"] = path.exists()
            if path.exists():
                from openpyxl import load_workbook

                wb = load_workbook(path)
                rows = list(wb.active.values)
                wb.close()
                target = sum(amounts) / 100
                checks["合计金额正确"] = any(
                    any(type(v) in (int, float) and abs(v - target) < 1e-7 for v in row)
                    for row in rows
                )
                checks["末尾签章保留"] = any(
                    "COMPLETE-7319" in str(v) for row in rows for v in row
                )
                checks["二十个项目均保留"] = all(
                    any(f"P{i+1}" in [str(v) for v in row] for row in rows)
                    for i in range(20)
                )
            extra["source_count"] = 20
            extra["gold_total"] = sum(amounts) / 100
        else:
            raise ValueError(case)
        if engine != "legacy" and driver:
            phase = driver.session.store.get(driver.session.task)["phase"]
            checks["执行结果没有待核实错误"] = phase != "uncertain"
            if case not in ("readonly_continuity", "readonly_then_edit"):
                checks["任务按完整目标结束"] = phase == "complete"
            events = driver.session.store.events(driver.session.task)
            extra["events"] = events
            extra["model_requests"] = sum(
                e["kind"] == "model_requested" for e in events
            )
            extra["verification_requests"] = sum(
                e["kind"] == "verifier_usage" for e in events
            )
            extra["compactions"] = sum(e["kind"] == "context_compacted" for e in events)
            if case == "long_chain":
                checks["二十份来源均实际读取"] = set(ids) <= {
                    e["body"]["file_id"] for e in events if e["kind"] == "source_read"
                }
            extra["usage"] = [
                e["body"].get("usage", {})
                for e in events
                if e["kind"] == "model_completed"
            ]
        result = {
            "engine": engine,
            "case": case,
            "passed": all(checks.values()),
            "checks": checks,
            "seconds": round(time.monotonic() - started, 3),
            "runs": driver.runs if driver else [],
            **extra,
        }
    except Exception as error:
        result = {
            "engine": engine,
            "case": case,
            "passed": False,
            "checks": checks,
            "seconds": round(time.monotonic() - started, 3),
            "error": str(error).replace(config.api_key, "[redacted]"),
            "runs": driver.runs if driver else [],
            **extra,
        }
    finally:
        if driver:
            driver.close()
    (folder / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def report(root, results):
    payload = {
        "real_model": True,
        "native_editor": False,
        "model": "deepseek-chat",
        "legacy_unchanged": True,
        "shared_tools": "Candidate Deep Agents and Pi use the same tools, write verifier, state and budget. Legacy uses the installed unmodified harness; it is not a pure engine-only comparison.",
        "versions": {"deepagents": "0.7.28", "pi-agent-core": "1.3.0"},
        "results": results,
    }
    (root / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    blocks = []
    for r in results:
        checks = "".join(
            f"<li>{'✓' if value else '✗'} {html.escape(key)}</li>"
            for key, value in r["checks"].items()
        )
        blocks.append(
            f'<article><h3>{html.escape(r["engine"])} · {html.escape(r["case"])} · {"通过" if r["passed"] else "未通过"}</h3><p>{r["seconds"]} 秒 · 模型请求 {r.get("model_requests","见轨迹")} 次</p><ul>{checks}</ul><p>{html.escape(r.get("error",""))}</p><a href="{r["engine"]}/{r["case"]}/result.json">原始结果</a></article>'
        )
    page = (
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Koto 新内核验证</title><style>body{font:15px/1.7 system-ui;background:#f5f6f8;color:#20242d;margin:0}main{max-width:1000px;padding:32px;margin:auto}article{background:white;border:1px solid #dce0e7;border-radius:8px;padding:16px 22px;margin:14px 0}h1{font-size:28px}h3{font-size:17px}a{color:#2856a2}p{overflow-wrap:anywhere}</style><main><h1>Koto 下一轮 Agent 架构验证</h1><p>真实 DeepSeek · 隔离文档与真实文件输出 · 未接入正式 Office/WPS 插件</p><p>新候选共用任务状态、工具、写入核对与预算。旧版保持原实现，因此结果包含 Koto 宿主执行层的改进，不能把所有提升归因于开源框架。Pi 本轮使用 Agent Core 与 Koto 持久化包装；未包含 Pi Coding Agent 的完整压缩系统。</p>"""
        + "".join(blocks)
        + '<p><a href="report.json">汇总记录</a></p></main></html>'
    )
    (root / "report.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key-file", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=("legacy", "deepagents", "pi"),
        default=["legacy", "deepagents", "pi"],
    )
    parser.add_argument(
        "--cases",
        nargs="+",
        default=[
            "readonly_continuity",
            "readonly_then_edit",
            "multiple_files",
            "single_checkpoint_restart",
            "real_word_table",
            "recoverable_error",
            "long_chain",
        ],
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = config_from_key_file(args.api_key_file)
    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [
            pool.submit(run, engine, case, args.output, config, args.api_key_file)
            for engine in args.engines
            for case in args.cases
        ]
        for future in as_completed(jobs):
            result = future.result()
            results.append(result)
            report(args.output, results)
            print(
                json.dumps(
                    {
                        k: result.get(k)
                        for k in (
                            "engine",
                            "case",
                            "passed",
                            "checks",
                            "seconds",
                            "error",
                        )
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    from .reporting import build_report

    build_report(args.output, results)
    return 0


if __name__ == "__main__":
    main()
