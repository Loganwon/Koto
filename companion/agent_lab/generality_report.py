"""Combine preserved before/after evidence, without converting skipped tests to passes."""

import argparse
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

LABELS = {
    "changed_deliverables": "临时取消、改名交付物",
    "relational_data": "跨文件关联、去重和异常处理",
    "workbook_formulas": "多个工作表与显式公式",
    "revise_artifact": "反馈后修订原工作簿",
    "untrusted_source": "不执行资料中的指令",
    "missing_information": "缺少数据时先追问",
    "large_export_restart": "625 条记录跨进程完整导出",
    "source_feedback": "更新来源后重新计算并定点修改",
}


def build(before, after, pi, pi_final, previous, output):
    output.mkdir(parents=True, exist_ok=True)
    read = lambda folder: json.loads(
        (folder / "report.json").read_text(encoding="utf-8")
    )["results"]
    old = {r["case"]: r for r in read(before)}
    new = {r["case"]: r for r in read(after)}
    comparators = {r["case"]: (pi, r) for r in read(pi)}
    comparators.update({r["case"]: (pi_final, r) for r in read(pi_final)})
    previous_results = read(previous)
    suites = list(ET.parse(after / "regression.xml").getroot().iter("testsuite"))
    checks = {
        k: sum(int(s.attrib.get(k, 0)) for s in suites)
        for k in ("tests", "failures", "errors", "skipped")
    }
    checks["passed"] = (
        checks["tests"] - checks["failures"] - checks["errors"] - checks["skipped"]
    )
    source = Path(__file__).parent
    code_hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob("*.py")
    }
    shared = set(old) & set(new)
    totals = {
        "before_shared": [sum(old[c]["passed"] for c in shared), len(shared)],
        "after_shared": [sum(new[c]["passed"] for c in shared), len(shared)],
        "new_all": [sum(r["passed"] for r in new.values()), len(new)],
        "pi": [sum(r["passed"] for _, r in comparators.values()), len(comparators)],
        "previous": [sum(r["passed"] for r in previous_results), len(previous_results)],
    }
    payload = {
        "created_at": datetime.now().astimezone().isoformat(),
        "real_model": True,
        "native_editor": False,
        "model": "deepseek-chat",
        "totals": totals,
        "automated_checks": checks,
        "source_sha256": code_hashes,
        "before": list(old.values()),
        "after": list(new.values()),
        "pi": [r for _, r in comparators.values()],
        "previous_regression": previous_results,
        "limits": [
            "Development after observing failures; six before/after families are not an independent benchmark.",
            "Two additional task families were designed after mechanisms existed, without further task-specific fixes.",
            "Pi four families; only relational_data and revise_artifact repeated after the final state/resource guard changes.",
            "Seven previous scenarios ran before final state/resource guards, which were additionally checked by the full automated suite and eight final real-model tasks.",
            "Real API and real Office packages, JSON editor substitute; no native WPS/Mac or production deployment.",
        ],
    }
    (output / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    esc = lambda value: html.escape(str(value), quote=True)
    link = lambda path: esc(os.path.relpath(path, output).replace("\\", "/"))

    def status(folder, r):
        if r is None:
            return '<span class="muted">本轮未测</span>'
        return f'<a class="{"ok" if r["passed"] else "fail"}" href="{link(folder / r["engine"] / r["case"] / "result.json")}">{"通过" if r["passed"] else "未通过"}</a>'

    rows, details = [], []
    for case, label in LABELS.items():
        other = comparators.get(case)
        rows.append(
            f'<tr><th>{esc(label)}</th><td>{status(before, old.get(case))}</td><td>{status(after, new.get(case))}</td><td>{status(*other) if other else "未测"}</td></tr>'
        )
        r = new.get(case)
        if not r:
            continue
        assertions = "".join(
            f'<li>{"✓" if value else "✗"} {esc(name)}</li>'
            for name, value in r["checks"].items()
        )
        outputs = after / r["engine"] / case / "outputs"
        files = " · ".join(
            f'<a href="{link(p)}">{esc(p.name)}</a>'
            for p in sorted(outputs.glob("*"))
            if not p.name.startswith(".")
        )
        events = r.get("events", [])
        counts = {
            kind: sum(e["kind"] == kind for e in events)
            for kind in (
                "model_requested",
                "verifier_usage",
                "data_query",
                "action_verified",
            )
        }
        details.append(
            f'<details><summary>{esc(label)}</summary><section><ul>{assertions}</ul><p class="muted">主模型请求 {counts["model_requested"]} 次 · 独立核对 {counts["verifier_usage"]} 次 · 查询 {counts["data_query"]} 次 · 已验证动作 {counts["action_verified"]} 次</p><p>{files or "此项按要求不生成文件。"}</p><a href="{link(after / r["engine"] / case / "result.json")}">原始对话与执行事件</a></section></details>'
        )
    table = "".join(rows)
    cards = "".join(
        f"<div><b>{a} / {b}</b>{label}</div>"
        for (a, b), label in [
            (totals["before_shared"], "补强前的新任务"),
            (totals["after_shared"], "同批任务补强后"),
            (totals["new_all"], "主候选本轮最终结果"),
            (totals["previous"], "原七类回归"),
        ]
    )
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Koto Agent 通用性测试与补强</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f5f6f8;color:#20242d;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}}main{{max-width:1050px;margin:auto;padding:30px 24px 60px}}h1{{font-size:29px;line-height:1.4}}h2{{font-size:21px;margin-top:30px}}a{{color:#2856a2;text-decoration:none}}a:hover{{text-decoration:underline}}.muted{{color:#687384}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.stats div{{background:white;padding:16px;border:1px solid #dce1e8;border-radius:8px}}.stats b{{display:block;font-size:25px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:11px 12px;border-bottom:1px solid #dde1e8;text-align:left}}thead{{background:#e9edf3}}.note{{background:#edf1f6;border-left:3px solid #778da7;padding:14px 18px}}.ok{{color:#28567a}}.fail{{color:#a04444}}details{{border:1px solid #dce1e8;border-radius:7px;background:white;margin:10px 0}}summary{{padding:13px 16px;cursor:pointer}}section{{padding:0 18px 15px}}li{{margin:6px 0}}footer{{border-top:1px solid #dce1e8;padding-top:18px;margin-top:26px}}@media(max-width:650px){{main{{padding:20px 12px}}.stats{{grid-template-columns:1fr 1fr}}table{{font-size:12px}}th,td{{padding:9px 6px}}}}</style>
<main><p class="muted">{datetime.now().date().isoformat()} · Deep Agents / LangGraph 主候选 · 真实 DeepSeek API</p><h1>Agent 能力已补测并补强，正式侧栏尚未切换</h1>
<p>六类新增任务先测得 {totals['before_shared'][0]} / {totals['before_shared'][1]}，再按失败原因补机制。最终主候选通过 {totals['new_all'][0]} / {totals['new_all'][1]} 类任务，包含两项后来追加的不同形态任务。生成结果经过独立文件读取核对。</p><div class="stats">{cards}</div>
<p class="note">这轮测试使用合成资料与 JSON 文档替身，实际调用模型并生成 DOCX/XLSX/PPTX 文件，没有打开或修改真实 WPS 工作文档。这里的通过率只针对列出的场景，不能解释为任意文件任务的成功率。补强后重复测试了已知失败，属于开发验证；追加两项也不是外部独立基准。</p>
<h2>实际结果</h2><table><thead><tr><th>任务</th><th>补强前</th><th>Deep Agents 最终</th><th>Pi 对照</th></tr></thead><tbody>{table}</tbody></table>
<p class="muted">Pi 四类对照通过 {totals['pi'][0]} / {totals['pi'][1]}；最终状态与资源保护调整后又复测了关联统计和原文件修订。原七类回归通过 {totals['previous'][0]} / {totals['previous'][1]}，包括逐段检查点、只读追问、三文件交付、跨进程续接、真实 Word 表格、错误恢复和 20 份顺序资料；该组在最后的保护调整前运行。完整自动检查在最后代码上通过 {checks['passed']} 项、跳过 {checks['skipped']} 项，失败 {checks['failures']} 项、错误 {checks['errors']} 项。跳过项不计作通过。</p>
<h2>失败原因与机制改动</h2><ul><li><strong>改向后被旧目标卡住：</strong>原交付物清单固定。现在由最新用户要求触发受验证的清单更新，保留版本和原始反馈；模型不能自行删除待办。</li><li><strong>较多数据耗尽调用预算：</strong>原工具只能逐项计算。现在用有边界的只读关系查询做关联、去重、筛选、聚合；金额用整数分处理，异常值保留，不按零计算。</li><li><strong>多表和公式无法表达：</strong>新增多个命名工作表、显式单元格类型及本地纯计算公式。普通等号文本保持文本，公式缓存不宣称已算出。</li><li><strong>无法修改已有输出：</strong>新增本任务生成工作簿的定点修订，校验文件版本与单元格旧值，保留旧文件，独立读回后记录新回执；修订后重新核对完成。</li><li><strong>预览与全量易混淆：</strong>完整分析结果以内容哈希编号保存，导出使用完整结果并检查来源是否变化；625 条记录已在新进程中完整恢复导出。</li></ul>
<h2>本轮能力边界</h2><p>数据查询覆盖 UTF-8 CSV/TSV、标量 JSON 对象数组和无公式 XLSX，可组合处理常见结构化文件任务。查询不开放任意 Python、Shell、网络或宿主文件读取。输入公式、复杂日期类型或缺少表头会明确拒绝。表格修订仅覆盖本任务已生成且有回执的 XLSX，不代表可以安全修改任意现有工作簿。</p><p>仍待完成：复杂 Word/PPT 编辑、OCR、通用代码沙箱、网页与 MCP、小时级长任务、运行中输入队列、正式 Office/WPS 接入及 Mac 原生验收。保持逐段可见和反馈改向的约束，后续宿主接入还需真实界面测试。</p>
<h2>逐项证据与真实生成文件</h2>{''.join(details)}
<footer><a href="{link(output / 'report.json')}">完整汇总</a> · <a href="{link(before / 'report.html')}">补强前记录</a> · <a href="{link(after / 'report.html')}">最终原始报告</a> · <a href="{link(previous / 'report.html')}">原七类回归</a> · <a href="{link(after / 'regression.xml')}">自动检查记录</a> · <a href="{link(source / 'README.md')}">运行说明与限额</a></footer></main></html>"""
    (output / "report.html").write_text(page, encoding="utf-8")
    return totals, checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "pi", "pi-final", "previous", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    totals, checks = build(
        args.before, args.after, args.pi, args.pi_final, args.previous, args.output
    )
    print(json.dumps({"totals": totals, "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
