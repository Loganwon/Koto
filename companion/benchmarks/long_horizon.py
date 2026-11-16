"""Opt-in real-model long tasks with frozen inputs; never opens native apps."""

import argparse
from pathlib import Path
import json

from .run import freeze
from .worker import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument(
        "--case", choices=("sales_full", "finance_matrix", "cross_format_feedback")
    )
    parser.add_argument("--key-file", default="C:/Users/12524/Desktop/DS_KEY.txt")
    args = parser.parse_args()
    if args.freeze:
        freeze(args.root)
        path = args.root / "cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        common = "在当前任务继续，只修订已有管理层短版.docx和管理层短版.pptx，不改收入明细.xlsx，不新建文件。两份文稿正文都加入准确文字“负责人{mark}Alice”。保留原有金额、同比、三档年费、示例及待验证限定和来源，Word仍300字以内，PPT仍3页且每页正文45字以内。先改Word，再改PPT。"
        cases["cross_format_feedback"]["turns"].extend(
            [
                {
                    "mode": "read",
                    "message": "只解释短版保留了哪些尚未验证的限定，不修改文件或任务清单。",
                },
                {"message": common.format(mark="：")},
                {
                    "message": common.format(mark="="),
                    "stop_after_change": "管理层短版.docx",
                },
                {
                    "message": "继续当前任务，完成被中断的剩余修改和验收，不重做已经成功的操作。",
                    "interaction": "continue",
                    "acknowledge": True,
                },
                {
                    "mode": "read",
                    "message": "只回答目前交付与仍待核实事项；不修改、不新建文件。",
                },
            ]
        )
        path.write_text(
            json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "frozen": str(args.root),
                    "scope": "Real model and real file tools; editor is a fixture, not native Office/WPS",
                }
            ),
            flush=True,
        )
    if args.case:
        run(args.root, args.case, "koto", 1, args.key_file)


if __name__ == "__main__":
    main()
