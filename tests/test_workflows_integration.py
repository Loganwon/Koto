#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Workflow 集成测试 — 使用 workspace/ 中的真实文件
验证每个已完成的 workflow 都能端到端产出结果。

运行方式：
  cd C:\\Users\\12524\\Desktop\\Koto
  .venv\\Scripts\\python.exe tests\\test_workflows_integration.py
"""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── 加载 Gemini API Key（config/gemini_config.env）─────────────────────────────
_env_file = ROOT / "config" / "gemini_config.env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# Gemini 超时压缩到 5s，让快速失败后切换到本地 Ollama
os.environ["GEMINI_CALL_TIMEOUT"] = "5"
os.environ["GEMINI_STREAM_CHUNK_TIMEOUT"] = "5"

# ── 测试文件路径 ────────────────────────────────────────────────────────────────
WS = ROOT / "workspace"

FILE_DOCX   = WS / "雷鸟访谈问题.docx"         # 普通 Word 文档
FILE_DOCX2  = WS / "王宇轩-简历（美元).docx"   # 对比用 Word 文档
FILE_DOCX3  = WS / "documents" / "以新质生产力推进文化产业高质量发展.docx"
FILE_XLSX   = WS / "销售台账.xlsx"             # Excel 文件
FILE_PPTX   = WS / "雷鸟投资报告.pptx"         # PPT 文件
FILE_PDF    = WS / "王宇轩-简历.pdf"           # PDF 文件
FILE_TXT    = WS / "KOTO.md"                   # 纯文本/Markdown

# ── 颜色输出 ───────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

results = []  # (name, status, detail)


def _parse_sse(line: str) -> dict:
    """将 SSE 行 'data: {...}' 解析为 dict；失败则返回空 dict。"""
    if isinstance(line, dict):
        return line
    s = line.strip()
    if s.startswith("data:"):
        s = s[5:].strip()
    try:
        return json.loads(s)
    except Exception:
        return {}


def run_workflow(name: str, executor_cls, params: dict):
    """运行一个 workflow，收集所有 SSE 事件，返回 (events_as_dicts, elapsed, exc)。
    
    工作流 execute() 有两种事件发射方式：
    1. generator yield SSE string — 通过 for ev in gen 收集
    2. yield_event(dict) callback — 通过 callback 收集
    两者都支持。
    """
    events = []

    def yield_event(ev):
        if isinstance(ev, str):
            events.append(_parse_sse(ev))
        elif isinstance(ev, dict):
            events.append(ev)

    t0 = time.time()
    try:
        inst = executor_cls()
        gen = inst.execute(params, yield_event)
        if gen is not None:
            for raw_ev in gen:
                # generator 直接 yield SSE 字符串或 dict
                parsed = _parse_sse(raw_ev) if isinstance(raw_ev, str) else (raw_ev or {})
                if parsed:
                    events.append(parsed)
    except Exception as exc:
        return events, time.time() - t0, exc
    return events, time.time() - t0, None


def check(name, events, elapsed, exc=None, required_output_types=None):
    """检查事件流并记录结果。"""
    if exc is not None:
        results.append((name, "FAIL", f"异常: {exc}"))
        print(f"  {RED}✗ {name}{RESET}  —  {RED}{exc}{RESET}")
        return False

    types = [e.get("type") for e in events if isinstance(e, dict)]

    if "error" in types:
        err_msgs = [e.get("text", "") for e in events if isinstance(e, dict) and e.get("type") == "error"]
        results.append((name, "FAIL", f"workflow error: {err_msgs}"))
        print(f"  {RED}✗ {name}{RESET}  —  error: {err_msgs}")
        return False

    has_output = "output" in types or "done" in types
    if not has_output:
        results.append((name, "FAIL", f"无 output/done 事件，实际: {types}"))
        print(f"  {YELLOW}✗ {name}{RESET}  —  无输出事件 (got: {types})")
        return False

    # 检查特定输出类型
    if required_output_types:
        out_events = [e for e in events if isinstance(e, dict) and e.get("type") == "output"]
        got_types = [e.get("output_type") for e in out_events]
        for req in required_output_types:
            if req not in got_types:
                results.append((name, "WARN", f"缺少 {req} 输出（got: {got_types}）"))
                print(f"  {YELLOW}⚠ {name}{RESET}  —  缺少 {req}，实际: {got_types}  ({elapsed:.1f}s)")
                return False

    results.append((name, "PASS", f"events={len(events)} time={elapsed:.1f}s"))
    print(f"  {GREEN}✓ {name}{RESET}  ({elapsed:.1f}s, {len(events)} events)")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 1. comm_digest — 沟通纪要生成
# ═══════════════════════════════════════════════════════════════════════════════
def test_comm_digest():
    print(f"\n{CYAN}{BOLD}[1] comm_digest — 沟通纪要生成{RESET}")
    from app.core.workflows.comm_digest import CommDigest

    # 用 KOTO.md 作为"会议纪要"文本
    text_sample = (FILE_TXT).read_text(encoding="utf-8", errors="ignore")[:4000]
    events, elapsed, exc = run_workflow(
        "comm_digest",
        CommDigest,
        {"texts": [text_sample], "output_mode": "markdown", "output_lang": "zh", "model_mode": "local"},
    )
    check("comm_digest (markdown)", events, elapsed, exc, required_output_types=["markdown"])

    # 用文件输入
    events2, elapsed2, exc2 = run_workflow(
        "comm_digest_file",
        CommDigest,
        {"files": [str(FILE_DOCX)], "output_mode": "auto", "output_lang": "zh", "model_mode": "local"},
    )
    check("comm_digest (docx file)", events2, elapsed2, exc2)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. comm_digest — 待办事项 Excel 输出
# ═══════════════════════════════════════════════════════════════════════════════
def test_comm_digest_excel_output():
    print(f"\n{CYAN}{BOLD}[2] comm_digest — 待办事项 Excel 输出{RESET}")
    from app.core.workflows.comm_digest import CommDigest

    text = """项目周会纪要：
1. 张三负责完成原型设计，截止 2026-05-01。
2. 李四本周五前整理供应商报价并反馈。
3. 王五下周一前发送测试报告。
"""
    events, elapsed, exc = run_workflow(
        "comm_digest_excel",
        CommDigest,
        {"texts": [text], "output_mode": "excel", "output_lang": "zh", "model_mode": "local"},
    )
    check("comm_digest (excel)", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. cross_format_extractor — 跨格式信息搬运
# ═══════════════════════════════════════════════════════════════════════════════
def test_cross_format_extractor():
    print(f"\n{CYAN}{BOLD}[3] cross_format_extractor — 跨格式信息提取{RESET}")
    from app.core.workflows.cross_format_extractor import CrossFormatExtractor

    events, elapsed, exc = run_workflow(
        "cross_format_extractor",
        CrossFormatExtractor,
        {
            "source_files": [str(FILE_PDF)],
            "fields": ["姓名", "联系方式", "教育背景", "工作经历"],
            "model_mode": "local",
        },
    )
    check("cross_format_extractor (PDF→fields)", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. data_format_cleaner — 脏数据格式清洗
# ═══════════════════════════════════════════════════════════════════════════════
def test_data_format_cleaner():
    print(f"\n{CYAN}{BOLD}[4] data_format_cleaner — 数据格式清洗{RESET}")
    from app.core.workflows.data_format_cleaner import DataFormatCleaner

    sample_csv = "行,A,B,C\n1,姓名,销售额,日期\n2,张三,12000.00,2024/1/5\n3,李四,¥8,500,2024-02-10\n4,王五,15000,20240315"
    events, elapsed, exc = run_workflow(
        "data_format_cleaner",
        DataFormatCleaner,
        {
            "csv_data": sample_csv,
            "instruction": "统一日期格式为 YYYY-MM-DD，销售额去除货币符号和逗号转为纯数字",
            "model_mode": "local",
        },
    )
    check("data_format_cleaner", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. data_anomaly_report — 数据异常检测
# ═══════════════════════════════════════════════════════════════════════════════
def test_data_anomaly_report():
    print(f"\n{CYAN}{BOLD}[5] data_anomaly_report — 数据异常检测{RESET}")
    from app.core.workflows.data_anomaly_report import DataAnomalyReport

    events, elapsed, exc = run_workflow(
        "data_anomaly_report",
        DataAnomalyReport,
        {"data_file": str(FILE_XLSX), "model_mode": "local"},
    )
    check("data_anomaly_report (xlsx)", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. doc_smart_compare — 文档智能对比
# ═══════════════════════════════════════════════════════════════════════════════
def test_doc_smart_compare():
    print(f"\n{CYAN}{BOLD}[6] doc_smart_compare — 文档智能对比{RESET}")
    from app.core.workflows.doc_smart_compare import DocSmartCompare

    events, elapsed, exc = run_workflow(
        "doc_smart_compare",
        DocSmartCompare,
        {
            "file_a": str(FILE_DOCX),
            "file_b": str(FILE_DOCX2),
            "output_mode": "html",
            "model_mode": "local",
        },
    )
    check("doc_smart_compare (html)", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. doc_smart_compare — Word 标注输出
# ═══════════════════════════════════════════════════════════════════════════════
def test_doc_smart_compare_docx_output():
    print(f"\n{CYAN}{BOLD}[7] doc_smart_compare — Word 标注输出{RESET}")
    from app.core.workflows.doc_smart_compare import DocSmartCompare

    events, elapsed, exc = run_workflow(
        "doc_smart_compare_docx",
        DocSmartCompare,
        {
            "file_a": str(FILE_DOCX),
            "file_b": str(FILE_DOCX2),
            "output_mode": "docx",
            "model_mode": "local",
        },
    )
    check("doc_smart_compare (docx)", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. multi_file_synthesis_report — 多文档综合报告
# ═══════════════════════════════════════════════════════════════════════════════
def test_multi_file_synthesis_report():
    print(f"\n{CYAN}{BOLD}[8] multi_file_synthesis_report — 多文档综合报告{RESET}")
    from app.core.workflows.multi_file_synthesis_report import MultiFileSynthesisReport

    events, elapsed, exc = run_workflow(
        "multi_file_synthesis_report",
        MultiFileSynthesisReport,
        {
            "source_files": [str(FILE_DOCX), str(FILE_PDF)],
            "report_title": "雷鸟创新综合分析报告",
            "focus": "投资价值和技术亮点",
            "model_mode": "local",
        },
    )
    check("multi_file_synthesis_report", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. contract_clause_matrix — 合同条款提取
# ═══════════════════════════════════════════════════════════════════════════════
def test_contract_clause_matrix():
    print(f"\n{CYAN}{BOLD}[9] contract_clause_matrix — 合同条款提取{RESET}")
    from app.core.workflows.contract_clause_matrix import ContractClauseMatrix

    events, elapsed, exc = run_workflow(
        "contract_clause_matrix",
        ContractClauseMatrix,
        {
            "contract_files": [str(FILE_DOCX), str(FILE_DOCX2)],
            "model_mode": "local",
        },
    )
    check("contract_clause_matrix", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. doc_smart_compare — 自动输出路由
# ═══════════════════════════════════════════════════════════════════════════════
def test_doc_smart_compare_auto_output():
    print(f"\n{CYAN}{BOLD}[10] doc_smart_compare — 自动输出路由{RESET}")
    from app.core.workflows.doc_smart_compare import DocSmartCompare

    events, elapsed, exc = run_workflow(
        "doc_smart_compare_auto",
        DocSmartCompare,
        {
            "file_a": str(FILE_DOCX),
            "file_b": str(FILE_DOCX2),
            "output_mode": "auto",
            "model_mode": "local",
        },
    )
    check("doc_smart_compare (auto)", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. comm_digest — 邮件线程摘要
# ═══════════════════════════════════════════════════════════════════════════════
def test_comm_digest_thread_file():
    print(f"\n{CYAN}{BOLD}[11] comm_digest — 邮件线程摘要{RESET}")
    from app.core.workflows.comm_digest import CommDigest

    # 创建一个临时邮件文本文件
    import tempfile
    email_text = """From: alice@company.com
To: bob@company.com
Date: Mon, 14 Apr 2026 10:00:00 +0800
Subject: 项目进度讨论

Bob，

昨天的会议我们确认了以下事项：
1. 产品原型需要在本周五前完成
2. 李四负责前端开发，王五负责后端API
3. 数据库设计方案待确认，需要张三反馈

另外，下周一开项目复盘会，请提前准备进度报告。

Alice

---
From: bob@company.com
To: alice@company.com
Date: Mon, 14 Apr 2026 11:30:00 +0800
Re: 项目进度讨论

Alice，

收到。补充一点：
- 测试环境搭建需要运维配合，我已经提交工单（#12345）
- 原型演示建议邀请产品总监参加

Bob
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                     encoding="utf-8") as f:
        f.write(email_text)
        tmp_path = f.name

    try:
        events, elapsed, exc = run_workflow(
            "comm_digest_thread_file",
            CommDigest,
            {
                "files": [tmp_path],
                "output_mode": "markdown",
                "output_lang": "zh",
                "model_mode": "local",
            },
        )
        check("comm_digest (thread file)", events, elapsed, exc)
    finally:
        os.unlink(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. doc_ai_review — AI 文档审阅
# ═══════════════════════════════════════════════════════════════════════════════
def test_doc_ai_review():
    print(f"\n{CYAN}{BOLD}[12] doc_ai_review — AI 文档审阅{RESET}")
    from app.core.workflows.doc_ai_review import DocAIReview

    events, elapsed, exc = run_workflow(
        "doc_ai_review",
        DocAIReview,
        {
            "doc_file": str(FILE_DOCX),
            "review_focus": "all",
            "model_mode": "local",
        },
    )
    check("doc_ai_review", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. pptx_data_refresh — PPT 数据刷新
# ═══════════════════════════════════════════════════════════════════════════════
def test_pptx_data_refresh():
    print(f"\n{CYAN}{BOLD}[13] pptx_data_refresh — PPT 数据刷新{RESET}")
    from app.core.workflows.pptx_data_refresh import PptxDataRefresh

    events, elapsed, exc = run_workflow(
        "pptx_data_refresh",
        PptxDataRefresh,
        {
            "pptx_file": str(FILE_PPTX),
            "data_file": str(FILE_XLSX),
            "instruction": "用销售台账中的数据替换PPT中相应的数字",
            "model_mode": "local",
        },
    )
    check("pptx_data_refresh", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. questionnaire_filler — 问卷自动填写
# ═══════════════════════════════════════════════════════════════════════════════
def test_questionnaire_filler():
    print(f"\n{CYAN}{BOLD}[14] questionnaire_filler — 问卷自动填写{RESET}")
    from app.core.workflows.questionnaire_filler import QuestionnaireFiller

    # 检查是否有 xlsx 文件可作为问卷
    events, elapsed, exc = run_workflow(
        "questionnaire_filler",
        QuestionnaireFiller,
        {
            "question_file": str(FILE_XLSX),
            "reference_files": [str(FILE_DOCX)],
            "model_mode": "local",
        },
    )
    check("questionnaire_filler", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 15. data_fill_report — 数据填报
# ═══════════════════════════════════════════════════════════════════════════════
def test_data_fill_report():
    print(f"\n{CYAN}{BOLD}[15] data_fill_report — 数据填报{RESET}")
    from app.core.workflows.data_fill_report import DataFillReport

    events, elapsed, exc = run_workflow(
        "data_fill_report",
        DataFillReport,
        {
            "data_file": str(FILE_XLSX),
            "template_file": str(FILE_DOCX),
            "instruction": "将销售台账数据填入文档对应位置",
            "model_mode": "local",
        },
    )
    check("data_fill_report", events, elapsed, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n{BOLD}{'='*60}")
    print(f"  Koto Workflow 集成测试")
    print(f"  使用 workspace/ 真实文件验证每个 workflow 的输出")
    print(f"{'='*60}{RESET}")

    # 检查所需文件是否存在
    print(f"\n{BOLD}>> 检查测试文件{RESET}")
    test_files = {
        "DOCX  (雷鸟访谈问题)": FILE_DOCX,
        "DOCX2 (王宇轩简历)":   FILE_DOCX2,
        "DOCX3 (新质生产力)":   FILE_DOCX3,
        "XLSX  (销售台账)":     FILE_XLSX,
        "PPTX  (雷鸟报告)":     FILE_PPTX,
        "PDF   (王宇轩简历)":   FILE_PDF,
        "TXT   (KOTO.md)":      FILE_TXT,
    }
    missing = []
    for label, path in test_files.items():
        exists = path.exists()
        sym = f"{GREEN}✓{RESET}" if exists else f"{RED}✗{RESET}"
        print(f"  {sym} {label}: {path.name}")
        if not exists:
            missing.append(str(path))

    if missing:
        print(f"\n{YELLOW}警告: 部分文件不存在，相关测试将跳过或失败{RESET}")

    t_total = time.time()

    test_comm_digest()
    test_comm_digest_excel_output()
    test_cross_format_extractor()
    test_data_format_cleaner()
    test_data_anomaly_report()
    test_doc_smart_compare()
    test_doc_smart_compare_docx_output()
    test_multi_file_synthesis_report()
    test_contract_clause_matrix()
    test_doc_smart_compare_auto_output()
    test_comm_digest_thread_file()
    test_doc_ai_review()
    test_pptx_data_refresh()
    test_questionnaire_filler()
    test_data_fill_report()

    elapsed_total = time.time() - t_total

    # ── 汇总 ───────────────────────────────────────────────────────────────────
    passed = [r for r in results if r[1] == "PASS"]
    warned = [r for r in results if r[1] == "WARN"]
    failed = [r for r in results if r[1] == "FAIL"]

    print(f"\n{BOLD}{'='*60}")
    print(f"  测试结果汇总  (总耗时 {elapsed_total:.1f}s)")
    print(f"{'='*60}{RESET}")
    print(f"  {GREEN}通过: {len(passed)}{RESET}  {YELLOW}警告: {len(warned)}{RESET}  {RED}失败: {len(failed)}{RESET}  / {len(results)} 总计\n")

    if warned:
        print(f"{YELLOW}── 警告详情 ──{RESET}")
        for name, _, detail in warned:
            print(f"  ⚠ {name}: {detail}")

    if failed:
        print(f"\n{RED}── 失败详情 ──{RESET}")
        for name, _, detail in failed:
            print(f"  ✗ {name}: {detail}")
    else:
        print(f"{GREEN}🎉 所有 workflow 均成功产出结果！{RESET}")

    sys.exit(0 if not failed else 1)
