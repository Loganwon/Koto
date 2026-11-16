"""Opt-in real-model file outputs and stale-binding conversations; no native apps."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import time

from companion.config import config_from_key_file
from companion.agent import WorkspaceAgent
from companion.file_actions import FileActions
from companion.file_readers import parse_file
from companion.journal import EventJournal
from companion.reading import TextSnapshot
from companion.session import EditingSession
from companion.workspace import LocalWorkspace
from companion.tests.test_journal import FileDocument


def settle(session):
    deadline = time.monotonic() + 120
    while session.snapshot()["busy"]:
        if time.monotonic() > deadline:
            session.stop()
            raise TimeoutError("model workflow did not finish")
        time.sleep(0.03)
    return session.snapshot()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key-file", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = config_from_key_file(args.api_key_file)
    results = []
    for extension, request in [
        (
            "pptx",
            '读取 @"计划.txt"，生成5页项目汇报PPT，保留日期和6个团队的事实，保存为汇报.pptx；不要修改当前Word。',
        ),
        (
            "docx",
            '读取 @"计划.txt"，新建一份项目备忘录，包含项目概况与下一步两节，保存为备忘录.docx；不要修改当前Word。',
        ),
        (
            "xlsx",
            '读取 @"计划.txt"，新建预算.xlsx，三行：表头为项目与万元；研发120.1、运营79.9。金额保留数值类型，不用公式。不要修改当前Word。',
        ),
    ]:
        folder = args.output / extension
        folder.mkdir(exist_ok=True)
        (folder / "计划.txt").write_text(
            "青岚项目于2027年3月18日上线，参与团队6个。研发预算120.1万元，运营79.9万元。",
            encoding="utf-8",
        )
        workspace = LocalWorkspace()
        workspace.open(folder)
        docs = FileDocument()
        journal = EventJournal(args.output / (extension + ".sqlite3"))
        session = EditingSession(
            docs,
            lambda: WorkspaceAgent(config),
            workspace.session,
            journal=journal,
            file_actions=FileActions(workspace, docs),
        )
        try:
            session.submit(request)
            state = settle(session)
            artifact = state.get("artifact")
            checks = {
                "真实文件回执": bool(artifact and artifact["verified"]),
                "当前Word未改": docs.writes == [],
            }
            if artifact:
                path = Path(artifact["path"])
                text = parse_file(path).text
                checks["可重新读取"] = bool(text)
                if extension == "pptx":
                    from pptx import Presentation

                    checks["五页并保留事实"] = (
                        len(Presentation(path).slides) == 5
                        and "6" in text
                        and "2027" in text
                    )
                elif extension == "xlsx":
                    from openpyxl import load_workbook

                    book = load_workbook(path)
                    checks["金额为数值"] = (
                        book.active["B2"].value == 120.1
                        and book.active["B3"].value == 79.9
                    )
                    book.close()
                else:
                    checks["保留来源事实"] = "2027" in text and "6" in text
            results.append(
                {
                    "case": extension,
                    "passed": all(checks.values()),
                    "checks": checks,
                    "answer": state["answer"],
                    "phase": state["phase"],
                    "artifact": artifact,
                    "harness": state["harness"],
                }
            )
        finally:
            session.stop()
            journal.close()
        print(
            json.dumps({"case": extension, "passed": results[-1]["passed"]}), flush=True
        )

    class StaleDocument(FileDocument):
        drift = False
        reads = 0

        def read(self, *args):
            self.reads += 1
            return "失效范围读到了别处" if self.drift else super().read(*args)

        def text_snapshot(self, target):
            return TextSnapshot("test.docx", "\n".join(self.text.values()))

    docs = StaleDocument()
    session = EditingSession(docs, lambda: WorkspaceAgent(config))
    try:
        session.submit("把当前第一段改成“首段已精简。”，后续段落保持不变。")
        first = settle(session)
        docs.drift = True
        reads_before = docs.reads
        session.revise("只解释上次已确认的修改，不要读取最新原文，也不要修改。")
        answered = settle(session)
        session.revise("现在把当前第一段改成“进一步精简。”")
        conflict = settle(session)
        session.revise("只解释刚才的上次已验证修改，不要尝试继续编辑。")
        continued = settle(session)
        checks = {
            "首段完成": first["phase"] == "review",
            "失效后仍能只读回答": bool(answered["answer"])
            and answered["phase"] == "review",
            "继续编辑仍被阻止": conflict["phase"] == "conflict",
            "冲突状态仍能对话": bool(continued["answer"])
            and continued["phase"] == "conflict",
            "没有第二次写入": docs.writes == ["one"],
        }
        results.append(
            {
                "case": "失效绑定与对话分离",
                "passed": all(checks.values()),
                "checks": checks,
                "outputs": [
                    answered["answer"],
                    conflict["message"],
                    continued["answer"],
                ],
            }
        )
    finally:
        session.stop()
    report = {
        "model": config.model,
        "real_model": True,
        "native_editor": False,
        "real_files": True,
        "results": results,
    }
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {"passed": sum(r["passed"] for r in results), "total": len(results)},
            ensure_ascii=False,
        )
    )
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
