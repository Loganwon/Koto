"""Readable comparison artifact; preserves raw failures and separates controls."""

from collections import defaultdict
import hashlib
import html
import json
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET

LABELS = {
    "readonly_continuity": "编辑后连续只读追问",
    "readonly_then_edit": "先对话后修改，保留约定",
    "multiple_files": "连续生成 Word、Excel、PPT",
    "single_checkpoint_restart": "单段确认后跨进程续接",
    "real_word_table": "生成真正的 Word 表格",
    "recoverable_error": "工具失败后继续原任务",
    "long_chain": "20 份顺序依赖资料与合计",
}


def build_report(root, results):
    root = Path(root)
    groups = defaultdict(dict)
    for item in results:
        groups[item["case"]][item["engine"]] = item
    checks_path = root / "regression.xml"
    regression = None
    if checks_path.exists():
        suites = list(ET.parse(checks_path).getroot().iter("testsuite"))
        regression = {
            key: sum(int(s.attrib.get(key, 0)) for s in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        regression["passed"] = (
            regression["tests"]
            - regression["failures"]
            - regression["errors"]
            - regression["skipped"]
        )
    source = Path(__file__).resolve().parents[1]
    hashes = {
        str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__).parent).glob("*.py")
    }
    hashes["file_readers.py"] = hashlib.sha256(
        (source / "file_readers.py").read_bytes()
    ).hexdigest()
    payload = {
        "real_model": True,
        "native_editor": False,
        "model": "deepseek-chat",
        "scope": "Independent architecture validation, not installed in the production add-in",
        "versions": {"deepagents": "0.7.28", "pi-agent-core": "1.3.0"},
        "source_hashes": hashes,
        "regression": regression,
        "comparison_limits": [
            "Targeted known weakness scenarios, one final run per engine; not a broad independent benchmark",
            "Candidate engines share improved tools, verifier, task state and budget; legacy is unmodified except shared XLSX reader bugfix",
            "Temporary tool failure injected for candidates only; legacy row is a normal generation control",
            "Pi uses Agent Core with host persistence; not the full Pi Coding Agent compaction system",
            "No arbitrary code execution, browser/MCP, in-flight input queue, native WPS or Mac acceptance in this round; contract revision and structured data are tested in the separate generality suite",
        ],
        "results": results,
    }
    (root / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    esc = lambda value: html.escape(str(value))
    table = []
    details = []
    for case, label in LABELS.items():
        cells = []
        for engine in ("legacy", "deepagents", "pi"):
            r = groups.get(case, {}).get(engine)
            if not r:
                cells.append("<td>待运行</td>")
                continue
            text = (
                "正常生成对照，未注入故障"
                if engine == "legacy" and case == "recoverable_error"
                else "通过" if r["passed"] else "未完成"
            )
            css = "pass" if r["passed"] else "fail"
            cells.append(
                f'<td><a class="{css}" href="#{engine}-{case}">{text}</a><small>{r["seconds"]} 秒</small></td>'
            )
            before = []
            for run in r.get("runs", []) or r.get("first_process_runs", []):
                answer = run.get("answer", "")
                state = run.get("state", {})
                if not answer and state.get("latest"):
                    answer = state["latest"].get("after", "")
                if answer:
                    before.append(answer)
            evidence = f"{engine}/{case}/result.json"
            verification = "".join(
                f'<li>{"✓" if ok else "✗"} {esc(name)}</li>'
                for name, ok in r["checks"].items()
            )
            details.append(
                f'<details id="{engine}-{case}"><summary>{esc(label)} · {engine} · {esc(text)}</summary><section><ul>{verification}</ul><p class="muted">{r.get("model_requests","见轨迹")} 次模型请求 · {r.get("verification_requests","见轨迹")} 次写入核对 · {r.get("compactions",0)} 次已记录压缩</p><pre>{esc(chr(10).join(before)[:3000] or r.get("error") or "完整执行证据见原始结果。")}</pre><a href="{evidence}">原始状态与事件记录</a></section></details>'
            )
        table.append(f'<tr><th>{esc(label)}</th>{"".join(cells)}</tr>')
    passed = {
        engine: sum(r["passed"] for r in results if r["engine"] == engine)
        for engine in ("deepagents", "pi")
    }
    totals = {
        engine: sum(r["engine"] == engine for r in results)
        for engine in ("deepagents", "pi")
    }
    long_result = groups.get("long_chain", {}).get("deepagents", {})
    long_evidence = f"链式任务中记录到 {long_result.get('compactions',0)} 次压缩、{long_result.get('model_requests','未记录')} 次模型请求；最终检查{'通过' if long_result.get('passed') else '未通过或尚未运行'}。"
    links = '<a href="report.json">完整汇总</a> · <a href="../../companion/agent_lab/README.md">运行说明</a> · <a href="../../companion/design/agent-runtime-next.md">设计与边界</a>'
    if regression:
        links += ' · <a href="regression.xml">回归记录</a>'
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Koto 新 Agent 内核验证</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f5f6f8;color:#20242d;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}}main{{max-width:1080px;margin:auto;padding:36px 24px 64px}}h1{{font-size:30px;line-height:1.35}}h2{{font-size:21px;margin-top:32px}}p{{margin:9px 0 15px}}a{{color:#2856a2;text-decoration:none}}a:hover{{text-decoration:underline}}.muted,small{{color:#697383}}.lead{{font-size:18px}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}}.stats>div{{padding:17px;background:white;border:1px solid #dce1e8;border-radius:8px}}.stats b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{text-align:left;padding:13px 12px;border-bottom:1px solid #e0e5ec;vertical-align:top}}thead{{background:#e9edf3}}td small{{display:block;font-size:12px}}.pass{{color:#29567a}}.fail{{color:#a04444}}.note{{border-left:3px solid #788da9;background:#edf1f6;padding:14px 18px}}details{{margin:9px 0;background:white;border:1px solid #dce1e8;border-radius:7px}}summary{{padding:13px 16px;cursor:pointer}}section{{padding:0 18px 15px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f4f6;padding:12px;font:13px/1.65 system-ui}}li{{margin:6px 0}}footer{{margin-top:28px;border-top:1px solid #d8dfe7;padding-top:18px}}@media(max-width:650px){{main{{padding:22px 14px}}.stats{{grid-template-columns:1fr 1fr}}table{{font-size:12px}}td,th{{padding:9px 7px}}}}</style>
<main><p class="muted">{datetime.now().date().isoformat()} · 真实 DeepSeek · 独立架构验证</p><h1>新版 Agent 执行基础验证，正式插件暂未切换</h1><p class="lead">任务目标、持续约束、逐段检查点与文件结果分别保存。Deep Agents 通过 {passed['deepagents']} / {totals['deepagents']} 项，Pi 通过 {passed['pi']} / {totals['pi']} 项；失败项和对照条件见下表。</p>
<div class="stats"><div><b>{passed['deepagents']} / {totals['deepagents']}</b>Deep Agents 定向场景</div><div><b>{passed['pi']} / {totals['pi']}</b>Pi 定向场景</div><div><b>20</b>份顺序依赖资料场景</div><div><b>{regression['passed'] if regression else '待检查'}</b>项回归通过</div></div>
<div class="note">这轮没有操作真实 WPS 文档。编辑端为持久化的 JSON 文档替身，模型调用和生成的 Office 文件真实执行。两套候选共用改进后的 Koto 状态与工具，结果不能全部归因于开源框架，也不表示已能处理任意文件任务。</div>
<h2>实际对照结果</h2><table><thead><tr><th>场景</th><th>旧执行结构</th><th>Deep Agents</th><th>Pi Core</th></tr></thead><tbody>{''.join(table)}</tbody></table>
<p class="muted">每项为最终一轮定向复测；不是随机样本。故障恢复项只对新候选注入错误，旧版该项仅作正常生成对照。用时是整项完成时间，不是界面响应速度，也不足以形成性能排名。</p>
<h2>这轮具体实现了什么</h2><ul><li>持续任务状态：目标、约束、待办和交付物不会随一次回答清空。</li><li>本轮写入控制：显式只读硬禁写；自动模式在提交具体修改前核对最新请求。</li><li>检查点：单段改完先显示；用户明确确认后继续剩余工作，唯一段落结束不再提前结束文件任务。</li><li>执行结果：多文件逐个记录回执，失败可继续；原生结果不明时保持待核实，不自动重做。</li><li>重启与并发：实际跨进程恢复；同一任务有进程间锁，已验证动作按编号防重复。</li><li>真实 Word 表格及基本三种 Office 文件生成；格式化工具与开源内核分别实现。</li></ul>
<h2>框架选择</h2><p>继续以 <strong>Deep Agents / LangGraph 为主候选</strong>，Pi 保留轻量对照。选型依据是 Deep Agents 的持久化与压缩整合更完整。{long_evidence}Pi 本轮使用 Agent Core 与 Koto 持久化包装，未测试完整 Coding Agent 压缩系统，因此不做两者压缩能力排名。</p>
<h2>实测修复与保留的失败</h2><p>首轮发现 Windows 下 Excel 读取器未及时释放校验文件，导致文件虽已出现却无法完成回执。共享读取器改为从内存字节流解析，并补充无垃圾回收等待的文件释放检查。早期评测只看文件存在会误判，最终检查已增加“无待核实错误”和“完整任务结束”。Pi 第二轮出现真实网络连接错误，随后补齐了有界模型重试；本地故障服务也验证了重试不会重复生成已完成文件。</p><p><a href="../agent-lab-comparison-20261019/report.html">修复前记录</a> · <a href="../agent-lab-comparison-fixed-20261019/report.html">中间复测（含网络失败）</a></p>
<h2>目前仍未完成</h2><ul><li>正式侧栏接入与原生 WPS / Word / Excel / PowerPoint / Mac 验收。</li><li>小时级任务、更多未见场景，以及运行中的完整输入队列。</li><li>交付清单改向、结构化分析及表格修订已加入独立通用性补测；本页仍只报告原七类回归。</li><li>任意代码执行、网页检索、MCP、微信投递和复杂排版。</li><li>跨模型比较、精确费用限制和全面的语义质量保证。</li></ul>
<h2>逐项证据</h2>{''.join(details)}<footer>{links}<p class="muted">API key 未写入报告或任务记录。失败记录保留，未覆盖工作文档。</p></footer></main></html>"""
    (root / "report.html").write_text(page, encoding="utf-8")
