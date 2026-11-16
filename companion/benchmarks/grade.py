"""Independent OOXML/Decimal acceptance, never reads model-declared success."""

import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import zipfile

from docx import Document
from openpyxl import load_workbook
from pptx import Presentation


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text(path):
    doc = Document(path)
    return "\n".join(
        [p.text for p in doc.paragraphs]
        + [c.text for t in doc.tables for r in t.rows for c in r.cells]
    )


def chars(value):
    return len(value.replace("\r", "").replace("\n", ""))


def numeric(value):
    normalized = str(value).replace(",", "").strip()
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?:%|人民币万元|万元|台)?",
        normalized,
    )
    if not match:
        raise ValueError("not a numeric value with an optional declared unit")
    return Decimal(match[1])


def fees_present(value):
    return all(money_present(value, n) for n in (120000, 39900, 9900))


def money_present(value, yuan):
    normalized = value.replace(",", "")
    for match in re.finditer(
        r"(?<![\d.])([+-]?\d+(?:\.\d+)?(?:\s*[/、]\s*[+-]?\d+(?:\.\d+)?)*)\s*(亿元?|万元?|千元?|元)",
        normalized,
    ):
        scale = {"亿": 100000000, "万": 10000, "千": 1000}.get(match[2][0], 1)
        if any(
            Decimal(number.strip()) * scale == Decimal(yuan)
            for number in re.split(r"[/、]", match[1])
        ):
            return True
    return (
        re.search(
            r"(?<![\d.])" + str(yuan) + r"(?:\.0+)?(?![\d.])(?!\s*[亿万千元%])",
            normalized,
        )
        is not None
    )


def sales_oracle(path):
    formulas = load_workbook(path, data_only=False)
    values = load_workbook(path, data_only=True)
    sheet, cache = formulas["汇总表"], values["汇总表"]
    anchors = {}
    for region in sheet.merged_cells.ranges:
        for r in range(region.min_row, region.max_row + 1):
            for c in range(region.min_col, region.max_col + 1):
                anchors[r, c] = (region.min_row, region.min_col)
    rows = []
    for r in range(2, sheet.max_row + 1):
        customer, product, quantity, price = [
            cache.cell(*anchors.get((r, c), (r, c))).value for c in range(1, 5)
        ]
        cents = (
            int(
                (Decimal(str(quantity)) * Decimal(str(price)) * 100).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
            )
            if type(quantity) in (int, float) and type(price) in (int, float)
            else None
        )
        rows.append([r, customer, product, quantity, price, cents])
    formulas.close()
    values.close()
    return rows


def claims_nonzero_difference(value):
    return bool(
        re.search(
            r"(?:重新加总|资料合计)[^。\n]{0,30}(?:(?<!没)有差额|(?<!不)存在差额)",
            value,
        )
    )


def grade(folder, root):
    result = read(folder / "result.json")
    case = result["case"]
    turns = result["turns"]
    outputs = folder / "outputs"
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    def safely(name, action):
        try:
            action()
        except Exception as error:
            check(name, False, type(error).__name__ + ": " + str(error)[:300])

    expected_turns = len(read(root / "cases.json")[case]["turns"])
    if result.get("aborted") or len(turns) != expected_turns:
        check(
            "全部预定轮次均已执行且未被中止",
            False,
            result.get(
                "aborted_reason",
                f"实际{len(turns)}轮，预定{expected_turns}轮；未完成不能记为通过",
            ),
        )
        events = read(folder / "events.json")
        return {
            "run": folder.name,
            "engine": result["engine"],
            "case": case,
            "passed": False,
            "checks": checks,
            "seconds": result["seconds"],
            "model_requests": sum(e["kind"] == "model_requested" for e in events),
            "tool_calls": sum(
                e["kind"] in ("tool_result", "tool_error") for e in events
            ),
            "verifier_requests": sum(e["kind"] == "verifier_usage" for e in events),
        }

    check("全部预定轮次均已执行且未被中止", True, f"{len(turns)}/{expected_turns}")

    check(
        "全部轮次执行无异常",
        all("error" not in t for t in turns),
        "; ".join(t.get("error", "")[:150] for t in turns if "error" in t),
    )
    check("输入副本未改变", result.get("references_unchanged", False))
    packages = list(outputs.glob("*"))
    try:
        for p in packages:
            with zipfile.ZipFile(p) as z:
                if z.testzip() is not None:
                    raise ValueError("包损坏")
        check("输出包可打开", bool(packages) or case == "edit_feedback")
    except Exception as error:
        check("输出包可打开", False, str(error))

    if case != "edit_feedback":
        check(
            "初始交付齐全且明确完成",
            turns[0]["state"]["phase"] == "complete"
            and set(read(root / "cases.json")[case]["outputs"])
            <= set(turns[0]["after"]),
        )
        check(
            "文件任务未修改正文",
            all(t["document_before"] == t["document_after"] for t in turns),
        )

    if case == "sales_full":

        def sales():
            book = load_workbook(outputs / "审计明细.xlsx", data_only=True)
            check(
                "三张要求的工作表",
                set(book.sheetnames) == {"逐行明细", "按客户汇总", "异常清单"},
            )
            rows = list(book["逐行明细"].values)
            expected = sales_oracle(root / "inputs/销售台账.xlsx")
            check(
                "明细列顺序",
                list(rows[0][:7])
                == ["原始行号", "客户", "产品", "数量", "单价", "金额分", "异常"],
            )
            check(
                "全部原始行连续保留",
                [r[0] for r in rows[1:]] == [r[0] for r in expected],
            )

            # OOXML reserialization may round IEEE floats at ~15 significant
            # digits. Names, quantities, NULLs and integer cents stay exact.
            def same(a, e):
                if list(a[:4]) != e[:4] or a[5] != e[5]:
                    return False
                if a[4] is None or e[4] is None:
                    return a[4] == e[4]
                return abs(numeric(a[4]) - numeric(e[4])) <= max(
                    Decimal(1), abs(numeric(e[4]))
                ) * Decimal("1e-12")

            errors = [e[0] for a, e in zip(rows[1:], expected) if not same(a, e)]
            check(
                "逐行六个原始字段及金额独立核对",
                len(rows) == len(expected) + 1 and not errors,
                f"错误行{errors[:10]}",
            )
            check(
                "总数量与整数分守恒",
                sum(r[3] or 0 for r in rows[1:]) == 2313
                and sum(r[5] or 0 for r in rows[1:]) == 1818873498,
            )
            anomaly_rows = {r[0] for r in list(book["异常清单"].values)[1:]}
            check("三处真实缺失均列异常", {215, 465, 908} <= anomaly_rows)
            book.close()
            memo = text(outputs / "审计说明.docx").replace(",", "")
            check(
                "摘要并列全量与有效口径",
                all(v in memo for v in ["1719", "1718", "1716", "2313"])
                and ("1818873498" in memo or "18188734.98" in memo),
            )
            check(
                "明确缓存未重算",
                "缓存" in memo
                and any(
                    v in memo
                    for v in [
                        "未重算",
                        "未经重算",
                        "未重新计算",
                        "未进行重算",
                        "未执行重算",
                    ]
                ),
            )

        safely("销售交付可检查", sales)
    elif case == "finance_matrix":

        def finance():
            book = load_workbook(outputs / "财务提取.xlsx", data_only=True)
            rows = list(book["指标明细"].values)
            check(
                "矩阵列顺序",
                list(rows[0][:6])
                == ["指标", "年份", "来源单元格", "缓存原值", "展示值", "单位"],
            )
            cache = load_workbook(
                root / "inputs/雷鸟创新-financial model.xlsx", data_only=True
            )
            actual = {
                str(r[2]).replace("'", "").replace("$", "").split("!")[-1]: r
                for r in rows[1:]
            }
            matches, bad = 0, []
            for r, metric in [
                (6, "收入合计"),
                (9, "销量"),
                (68, "净利润"),
                (69, "净利率"),
            ]:
                for c in range(3, 7):
                    cell = cache["P&L"].cell(r, c)
                    value = actual.get(cell.coordinate)
                    wanted = (numeric(cell.value) * (100 if r == 69 else 1)).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    try:
                        valid = (
                            str(2022 + c) in str(value[1])
                            and abs(numeric(value[3]) - numeric(cell.value))
                            < Decimal("0.000001")
                            and abs(numeric(value[4]) - wanted) < Decimal("0.005")
                        )
                    except Exception:
                        valid = False
                    if valid:
                        matches += 1
                    else:
                        bad.append(cell.coordinate)
            check(
                "16项坐标年份缓存原值展示值",
                matches == 16 and len(rows) == 17,
                f"{matches}/16; 错误坐标{bad}",
            )
            cache.close()
            book.close()
            memo = text(outputs / "口径说明.docx")
            check(
                "说明来源缓存与单位",
                all(v in memo for v in ["P&L", "缓存", "万元", "台"]),
            )

        safely("财务交付可检查", finance)
    elif case == "cross_format_feedback":

        def mixed():
            book = load_workbook(outputs / "收入明细.xlsx", data_only=True)
            rows = list(book["季度明细"].values)
            expected = [
                [1200000, 380000, 150000, 1730000],
                [1450000, 420000, 210000, 2080000],
                [1680000, 510000, 280000, 2470000],
                [2100000, 620000, 350000, 3070000],
                [2550000, 780000, 430000, 3760000],
            ]
            quarters = [
                r for r in rows[1:] if re.fullmatch(r"\d{4}\s*Q[1-4]", str(r[0]), re.I)
            ]
            check(
                "五季度原值加总与差额",
                [str(r[0]).replace(" ", "").upper() for r in quarters]
                == ["2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1"]
                and all(
                    list(a[1:5]) == e and a[5] == sum(e[:3]) and a[6] == 0
                    for a, e in zip(quarters, expected)
                ),
            )
            numbers = []
            for sheet in book:
                if sheet.title == "季度明细":
                    continue
                for row in sheet.values:
                    for v in row:
                        try:
                            numbers.append(numeric(v))
                        except (ValueError, ArithmeticError):
                            pass
            check(
                "全年收入与同比独立核算",
                Decimal(9350000) in numbers
                and any(
                    abs(v - Decimal("117.34")) < Decimal("0.005")
                    or abs(v - Decimal("1.1734104046242775")) < Decimal("0.000001")
                    for v in numbers
                ),
            )
            book.close()
            memo = text(outputs / "联合简报.docx").replace(",", "")
            check(
                "初稿三档年费与限定",
                fees_present(memo)
                and "示例" in memo
                and any(v in memo for v in ["待验证", "需验证", "未验证", "验证建议"]),
            )
            first_deck = Presentation(outputs / "联合简报.pptx")
            check("初稿幻灯片3至5页", 3 <= len(first_deck.slides) <= 5)

        safely("跨格式初稿可检查", mixed)
        check(
            "只读追问完全不写入",
            turns[1]["before"] == turns[1]["after"]
            and turns[1]["document_before"] == turns[1]["document_after"]
            and turns[1].get("result", {}).get("write_calls", -1) == 0,
        )
        answer = turns[1].get("result", {}).get("answer", "").replace(",", "")
        check("只读追问回答费用及页码", fees_present(answer) and "6" in answer)
        last = turns[2]
        check(
            "反馈更新交付清单并完成",
            set(last["state"]["expected_outputs"])
            == {"收入明细.xlsx", "管理层短版.docx", "管理层短版.pptx"}
            and last["state"]["phase"] == "complete",
        )
        check(
            "反馈保留全部旧成果和收入表",
            all(last["after"].get(k) == v for k, v in last["before"].items())
            and {"联合简报.docx", "联合简报.pptx", "收入明细.xlsx"}
            <= set(last["before"]),
        )

        def short():
            doc = Document(outputs / "管理层短版.docx")
            count = sum(
                chars(p.text) for p in doc.paragraphs if p.style.name != "Title"
            ) + sum(chars(c.text) for t in doc.tables for r in t.rows for c in r.cells)
            check("Word实际正文不超过300字", count <= 300, str(count))
            deck = Presentation(outputs / "管理层短版.pptx")
            counts = [
                sum(
                    chars(s.text)
                    for s in slide.shapes
                    if s.has_text_frame and s != slide.shapes.title
                )
                for slide in deck.slides
            ]
            check(
                "PPT三页实际正文各不超过45字",
                len(counts) == 3 and max(counts) <= 45,
                str(counts),
            )
            memo = text(outputs / "管理层短版.docx").replace(",", "")
            check(
                "短版仍保留数据费用与限定",
                money_present(memo, 9350000)
                and "117.34" in memo
                and fees_present(memo)
                and "示例" in memo
                and any(v in memo for v in ["待验证", "需验证", "未验证"]),
            )

        safely("反馈短版可检查", short)
        if len(turns) >= 8:
            colon, stopped, resumed = turns[4:7]
            names = ["管理层短版.docx", "管理层短版.pptx"]
            for number in (1, 3, 7):
                current, previous = turns[number], turns[number - 1]
                check(
                    f"第{number + 1}轮只读保留文件与任务合同",
                    current["before"] == current["after"]
                    and current["document_before"] == current["document_after"]
                    and current.get("result", {}).get("write_calls", -1) == 0
                    and current["state"]["expected_outputs"]
                    == previous["state"]["expected_outputs"]
                    and current["state"].get("task_contract")
                    == previous["state"].get("task_contract"),
                )
            check(
                "两份短版均按反馈加入负责人",
                all(
                    "负责人：Alice"
                    in colon.get("artifact_text", {}).get(n, {}).get("text", "")
                    for n in names
                ),
                "从每轮实际保存文件独立读取；缺少快照不记通过",
            )
            check(
                "实际在DOCX文件完成、PPTX未改时停止（非原生应用）",
                stopped.get("interruption", {}).get("requested")
                and stopped["after"].get(names[0]) != stopped["before"].get(names[0])
                and stopped["after"].get(names[1]) == stopped["before"].get(names[1])
                and stopped["state"]["phase"] != "complete",
            )
            check(
                "停止后不重用上轮完成答复",
                "interruption_error" in stopped
                or "已停止" in stopped.get("result", {}).get("answer", ""),
            )
            check(
                "继续后完成剩余PPT且不重写已改Word",
                resumed["state"]["phase"] == "complete"
                and resumed["after"].get(names[0]) == stopped["after"].get(names[0])
                and resumed["after"].get(names[1]) != stopped["after"].get(names[1]),
            )
            check(
                "最终两份文件均采用新格式而非旧反馈",
                all(
                    "负责人=Alice"
                    in resumed.get("artifact_text", {}).get(n, {}).get("text", "")
                    and "负责人：Alice"
                    not in resumed.get("artifact_text", {}).get(n, {}).get("text", "")
                    for n in names
                ),
            )
            check(
                "八轮收入表保持原样且不新增意外交付",
                all(
                    t["after"].get("收入明细.xlsx")
                    == turns[0]["after"].get("收入明细.xlsx")
                    for t in turns
                )
                and set(turns[-1]["after"])
                == {"收入明细.xlsx", "联合简报.docx", "联合简报.pptx", *names},
            )

            def final_ppt():
                from companion.agent_lab.content_checks import body_text

                value = body_text(outputs / names[1]).replace(",", "")
                checks_by_name = {
                    "全年收入": money_present(value, 9350000),
                    "同比": "117.34" in value,
                    "年费": fees_present(value),
                    "示例": "示例" in value,
                    "待验证": any(v in value for v in ["待验证", "需验证", "未验证"]),
                }
                check(
                    "最终PPT独立核对金额同比年费及限定",
                    all(checks_by_name.values()),
                    str(checks_by_name),
                )

            safely("最终PPT可检查", final_ppt)

            final_answer = turns[-1].get("result", {}).get("answer", "")
            check(
                "最终只读答复不把零差额说成存在差额",
                not claims_nonzero_difference(final_answer),
                "五季度实际差额均为0；答复质量单独检查，不由文件完成状态代替",
            )

            def no_instruction_leak():
                from companion.agent_lab.content_checks import body_text

                value = (
                    body_text(outputs / names[0]) + "\n" + body_text(outputs / names[1])
                )
                check(
                    "短版正文不夹入任务运行声明",
                    not re.search(
                        r"交付清单[:：]|仅修订本短版|每页正文[≤<]|不超过300字|共3页",
                        value,
                    ),
                )

            safely("短版正文质量可检查", no_instruction_leak)
    elif case == "edit_feedback":
        original = read(root / "cases.json")[case]["document"]
        first, readonly, direction, second = turns
        a = first["document_after"]
        check(
            "首次只改第一段且保留事实",
            a["0"] != original["0"]
            and all(v in a["0"] for v in ["240", "20%", "分析"])
            and a["1"] == original["1"]
            and a["2"] == original["2"],
        )
        check(
            "首次一处写入后暂停",
            first.get("result", {}).get("write_calls") == 1
            and first["state"]["phase"] == "review",
        )
        check(
            "只读追问不修改不推进",
            readonly["document_before"] == readonly["document_after"]
            and readonly.get("result", {}).get("write_calls") == 0
            and readonly["state"]["phase"] == "review",
        )
        check(
            "反馈后第一段按指定方向修改",
            direction["document_after"]["0"]
            == "本季度营收240万元，同比增长20%。客户转化仍需分析。"
            and direction["document_after"]["1"] == original["1"]
            and direction["state"]["phase"] == "review",
        )
        check(
            "确认后只改第二段并暂停",
            second["document_after"]["0"] == direction["document_after"]["0"]
            and second["document_after"]["1"]
            == "下一季度先核查线索质量，再优化客户转化流程。"
            and second["document_after"]["2"] == original["2"]
            and second["state"]["phase"] == "review"
            and second.get("result", {}).get("write_calls") == 1,
        )
        check("未生成用户未要求的文件", not packages)
    events = read(folder / "events.json")
    failures = [c for c in checks if not c["passed"]]
    return {
        "run": folder.name,
        "engine": result["engine"],
        "case": case,
        "passed": not failures,
        "checks": checks,
        "seconds": result["seconds"],
        "model_requests": sum(e["kind"] == "model_requested" for e in events),
        "tool_calls": sum(e["kind"] in ("tool_result", "tool_error") for e in events),
        "verifier_requests": sum(e["kind"] == "verifier_usage" for e in events),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for path in sorted(args.root.glob("*/result.json")):
        value = read(path)
        if "seconds" not in value or "case" not in value or "engine" not in value:
            continue  # A running case is neither a pass nor a failure yet.
        try:
            results.append(grade(path.parent, args.root))
        except Exception as error:
            results.append(
                {"run": path.parent.name, "passed": False, "grader_error": str(error)}
            )
    manifest = read(args.root / "manifest.json")
    integrity = all(
        sha(Path(v["original"])) == v["sha256"]
        and sha(args.root / "inputs" / k) == v["sha256"]
        for k, v in manifest["sources"].items()
    )
    report = {"originals_unchanged": integrity, "runs": results}
    (args.root / "scores.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "originals_unchanged": integrity,
                "runs": [
                    {k: v for k, v in r.items() if k != "checks"} for r in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
