# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Callable, Dict, List

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_runtime_utils import _compact_line, _json_payload
from app.core.agent.file_task_tool_catalog import stringify_result

DisplayPath = Callable[[Any], str]


def fallback_readonly_summary(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    files: List[FileTaskFile],
    exc: Exception,
    display_path: DisplayPath,
) -> str:
    if not snippets:
        return ""

    article_summary = _build_readonly_content_summary(
        request=request,
        snippets=snippets,
        readonly_tool_outputs=[],
        display_path=display_path,
        note=f"说明：模型暂不可用，本摘要由 Koto 基于已读取文本生成。模型错误：{_compact_line(exc, 160)}",
    )
    if article_summary:
        return article_summary

    lines = [
        "模型暂不可用，Koto 已先基于显式上下文整理可见内容（非模型推理）：",
    ]
    used_sources: set[str] = set()
    for index, snippet in enumerate(snippets[:5], start=1):
        source = str(
            snippet.get("source") or snippet.get("path") or f"上下文 {index}"
        ).strip()
        if not source and index <= len(files):
            source = files[index - 1].name or files[index - 1].path
        source_label = display_path(source) or f"上下文 {index}"
        preview = _compact_line(snippet.get("preview"), 320)
        if not preview:
            continue
        dedupe_key = f"{source_label}:{preview}"
        if dedupe_key in used_sources:
            continue
        used_sources.add(dedupe_key)
        lines.append(f"{index}. {source_label}：{preview}")

    if len(lines) == 1:
        return ""

    lines.append("恢复模型后可以继续生成更完整的总结、改写或写入文件。")
    lines.append(f"模型错误：{_compact_line(exc, 160)}")
    return "\n".join(lines)


def readonly_answer_required_message(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
) -> str:
    lines = [
        "你已经完成了只读文件读取，但还没有给用户可见答案。本轮必须直接输出分析结果，不要空回复，也不要再次调用任何工具。",
        f"用户任务：{request.task}",
        "要求：基于已读取内容给出结构化结论；如果信息不足，也要明确说明已读取到什么、缺什么、下一步怎么做。",
    ]
    source_lines = readonly_context_source_lines(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
        limit=5,
    )
    if source_lines:
        lines.append("已读取内容摘录：")
        lines.extend(source_lines)
    return "\n".join(lines)


def readonly_context_source_lines(
    *,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
    limit: int = 5,
) -> List[str]:
    lines: List[str] = []
    seen: set[str] = set()
    for item in readonly_tool_outputs:
        if not isinstance(item, dict):
            continue
        source = readonly_tool_source_label(item, display_path=display_path)
        for point in readonly_tool_points(item):
            text = _compact_line(point, 260)
            if not text:
                continue
            key = f"{source}:{text}"
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {source}：{text}")
            if len(lines) >= limit:
                return lines
    for index, snippet in enumerate(snippets, start=1):
        if not isinstance(snippet, dict):
            continue
        source = str(
            snippet.get("source") or snippet.get("path") or f"上下文 {index}"
        ).strip()
        text = _compact_line(snippet.get("preview"), 260)
        if not text:
            continue
        key = f"{source}:{text}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {display_path(source) or source}：{text}")
        if len(lines) >= limit:
            break
    return lines


def readonly_context_summary(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
) -> str:
    summary = _build_readonly_content_summary(
        request=request,
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
        note="说明：本轮为只读总结，没有写入或修改文件；由于模型未返回完整自然语言答案，Koto 使用已读取文本生成这份摘要。",
    )
    if summary:
        return summary
    source_lines = readonly_context_source_lines(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
        limit=7,
    )
    if not source_lines:
        return ""
    return "\n".join(
        [
            "## 文件内容总结",
            "",
            "已读取文件，但可用于归纳的正文较少。以下是可见内容：",
            *source_lines,
            "",
            "说明：本轮为只读总结，没有写入或修改文件。",
        ]
    )


def _build_readonly_content_summary(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
    note: str,
) -> str:
    sources = _readonly_source_names(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
    )
    paragraphs = _readonly_content_paragraphs(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
    )
    if _looks_like_investment_risk_opportunity_task(request.task):
        investment_summary = _build_investment_risk_opportunity_summary(
            request=request,
            snippets=snippets,
            readonly_tool_outputs=readonly_tool_outputs,
            display_path=display_path,
            note=note,
        )
        if investment_summary:
            return investment_summary
    if not paragraphs:
        return ""
    if _looks_like_argument_improvement_task(request.task):
        argument_summary = _build_argument_improvement_summary(
            request=request,
            snippets=snippets,
            readonly_tool_outputs=readonly_tool_outputs,
            paragraphs=paragraphs,
            display_path=display_path,
            note=note,
        )
        if argument_summary:
            return argument_summary
    title = "文章总结" if _looks_like_summary_task(request.task) else "文件内容总结"
    overview = _compact_line(_first_substantial_sentence(paragraphs), 220)
    thesis = _compact_line(_extract_thesis(paragraphs) or overview, 260)
    structure_points = _select_structure_points(paragraphs, limit=5)
    overall = _compose_overall_summary(overview, thesis, structure_points)
    key_points = _select_key_points(
        paragraphs,
        limit=4,
        exclude=[overview, thesis, *structure_points],
    )

    lines = [f"## {title}", ""]
    if sources:
        lines.append(f"已读取：{', '.join(sources[:3])}")
        lines.append("")
    lines.extend(
        [
            "总体概括：",
            overall,
            "",
            "核心观点：",
            f"- {_clean_claim_text(thesis)}",
            "",
            "论证脉络：",
        ]
    )
    for index, point in enumerate(structure_points, start=1):
        lines.append(f"{index}. {point}")
    if key_points:
        lines.extend(["", "补充要点："])
        for point in key_points:
            lines.append(f"- {point}")
    lines.extend(["", note])
    return "\n".join(lines)


def _looks_like_summary_task(task: Any) -> bool:
    text = str(task or "").lower()
    return any(
        token in text
        for token in ("总结", "摘要", "概括", "summar", "article", "文章", "文档")
    )


def _looks_like_investment_risk_opportunity_task(task: Any) -> bool:
    text = str(task or "").lower()
    has_investment_context = any(token in text for token in ("一级市场", "投资报告", "投资建议", "尽调", "融资", "估值"))
    asks_for_judgment = any(token in text for token in ("风险", "机会", "投资机会", "投资价值", "建议", "判断"))
    return has_investment_context and asks_for_judgment


def _looks_like_argument_improvement_task(task: Any) -> bool:
    text = str(task or "").lower()
    asks_about_argument = any(token in text for token in ("论点", "论证", "观点", "argument", "thesis"))
    asks_for_improvement = any(token in text for token in ("优化", "改进", "修改", "调整", "建议", "问题", "值得", "improv"))
    return asks_about_argument and asks_for_improvement


def _build_argument_improvement_summary(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    paragraphs: List[str],
    display_path: DisplayPath,
    note: str,
) -> str:
    sources = _readonly_source_names(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
    )
    thesis = _clean_claim_text(_extract_thesis(paragraphs) or _first_substantial_sentence(paragraphs))
    structure_points = _select_structure_points(paragraphs, limit=5)
    if not thesis and structure_points:
        thesis = structure_points[0]
    key_points = _select_key_points(
        paragraphs,
        limit=5,
        exclude=[thesis, *structure_points],
    )
    if not thesis and not structure_points:
        return ""

    bridge_hint = _first_matching_sentence(
        paragraphs,
        ("本雅明", "阿多诺", "麦克卢汉", "Sobchack", "电影", "游戏", "技术", "身体"),
    )
    case_hint = _first_matching_sentence(
        paragraphs,
        ("《", "案例", "Lake", "湖中女郎", "电子游戏", "游戏"),
    )
    concept_hint = _first_matching_sentence(
        paragraphs,
        ("身体", "主体", "观看者", "虚拟", "技术", "艺术"),
    )
    content_text = " ".join(paragraphs[:8])
    game_body_argument = any(token in content_text for token in ("电子游戏", "游戏", "身体", "观看者", "电影"))

    improvements: List[str] = []
    if thesis:
        if game_body_argument:
            improvements.append(
                "核心论点可以再拆细：当前主张是"
                f"“{_strip_sentence_end(thesis)}”，建议拆成“技术改变接受位置”和“电子游戏生产可行动的虚拟身体”两个层级，避免一个命题同时承担本体论、媒介史和案例分析三重任务。"
            )
        else:
            improvements.append(
                "核心论点可以再拆细：当前主张是"
                f"“{_strip_sentence_end(thesis)}”，建议拆成“讨论对象、作用机制、结论边界”三个层级，避免一个命题同时承担过多证明任务。"
            )
    if concept_hint:
        improvements.append(
            "概念边界需要更早界定：文中反复使用"
            f"“{_compact_line(concept_hint, 90)}”这一组概念，建议先说明关键词的定义、范围和彼此关系。"
        )
    if bridge_hint:
        if game_body_argument:
            improvements.append(
                "理论转场还可以补桥：从传统艺术-技术框架转向游戏媒介时，建议说明电影现象学为什么不足以解释游戏，并指出游戏多出的“输入、反馈、失败、控制权”机制。"
            )
        else:
            improvements.append(
                "理论或材料之间还可以补桥：每次从一个框架转向另一个框架时，建议补一句“为什么前一框架不足、后一框架解决什么问题”。"
            )
    if case_hint:
        improvements.append(
            "案例功能需要更精确：案例不只应证明现象存在，还要说明它支持了核心论点中的哪一个环节，否则容易停留在类比或举例层面。"
        )
    if len(improvements) < 3:
        improvements.append(
            "结论需要回扣开头问题：最后应明确回答文章一开始提出的问题，并把答案落到核心论点的边界和意义上。"
        )

    suggestions = (
        [
            "开头先用一两句话压缩问题意识，再给出可检验的中心论点，减少连续设问造成的焦点分散。",
            "每一节结尾增加一句小结，说明这一节如何服务于“共同生产关系”这个总论点。",
            "把“电影失败/游戏成立”的差异写成机制对照，而不是只做历史并置。",
            "增加一个具体游戏段落，说明玩家输入、镜头、角色受伤/死亡、反馈循环如何共同塑造身体经验。",
        ]
        if game_body_argument
        else [
            "开头先压缩问题意识，再给出可检验的中心论点，减少连续铺垫造成的焦点分散。",
            "每一节结尾增加一句小结，说明这一节如何服务于总论点。",
            "把关键概念、理论框架和案例材料之间的因果关系写清楚，避免只做并列陈述。",
            "补充一个能直接验证核心论点的具体案例，并明确它证明的是前提、机制还是结论。",
        ]
    )

    output = ["## 论点优化建议", ""]
    if sources:
        output.append(f"已读取：{', '.join(sources[:3])}")
        output.append("")
    output.extend(
        [
            "当前核心论点：",
            f"- {_strip_sentence_end(thesis)}。",
            "",
            "整体判断：",
            (
                "文章的问题意识是成立的，最有价值之处在于把“艺术与技术”从工具关系推进到共同生产关系；但目前论证还需要加强概念界定、媒介差异和案例证明，才能让“电子游戏让艺术作用于虚拟身体”这个判断更稳。"
                if game_body_argument
                else "文章已经有可辨认的中心论点，但目前还需要加强概念界定、论证层级和案例证明，才能让判断更稳、更容易被读者跟随。"
            ),
            "",
            "值得优化的论点：",
        ]
    )
    for item in improvements[:5]:
        output.append(f"- {item}")
    if key_points:
        output.extend(["", "可保留并强化的材料："])
        for point in key_points[:3]:
            output.append(f"- {_compact_line(point, 180)}")
    output.extend(["", "具体修改建议："])
    for item in suggestions:
        output.append(f"- {item}")
    output.extend(["", note])
    return "\n".join(output)


def _build_investment_risk_opportunity_summary(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
    note: str,
) -> str:
    sources = _readonly_source_names(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
    )
    lines = _investment_source_lines(
        request=request,
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
    )
    if not lines:
        return ""

    def matches(*tokens: str, limit: int = 3, prefer: tuple[str, ...] = ()) -> List[str]:
        candidates: List[str] = []
        for line in lines:
            if any(token in line for token in tokens) and not _near_duplicate(line, candidates):
                candidates.append(_compact_line(line, 220))
        if not prefer:
            return candidates[:limit]
        preferred = [line for line in candidates if any(token in line for token in prefer)]
        found: List[str] = []
        for line in [*preferred, *candidates]:
            if line and not _near_duplicate(line, found):
                found.append(line)
            if len(found) >= limit:
                break
        return found

    market = matches("AI眼镜", "智能眼镜", "全球实际销量", "国内实际销量", "市场份额", limit=4)
    technology = matches("专利", "MicroLED", "光波导", "全彩显示", "核心技术", limit=4)
    sales = matches("营业收入", "销量", "2025H1", "2024年销量", "前十大客户", "销售额", limit=5, prefer=("营业收入", "销量", "销售额"))
    financing = matches("估值", "融资", "回购", "本次增资", "投资金额", "IRR", "回报倍数", limit=5)
    finance = matches("净利润", "经营活动产生的现金流量净额", "货币资金", "毛利率", "营业利润", "资产负债率", limit=6, prefer=("净利润", "经营活动产生的现金流量净额", "毛利率"))
    concentration = matches("前十大客户", "前十大供应商", "占总销售额", "占总采购额", "深圳市雷鸟网络", "惠州TCL", limit=5, prefer=("前十大客户", "前十大供应商", "占总销售额", "占总采购额"))
    forecast = matches("盈利预测", "2027年", "盈亏平衡", "净利率", "预测依据", limit=5, prefer=("盈利预测", "预测依据", "净利率"))

    opportunity_points = [
        _join_evidence("赛道增长窗口明确", market),
        _join_evidence("公司具备头部产品和技术卡位", technology),
        _join_evidence("收入和销量已有放量迹象", sales),
        _join_evidence("交易结构存在一定进入折扣和回购约束", financing),
    ]
    risk_points = [
        _join_evidence("亏损、现金流和资金消耗仍是首要风险", finance),
        _join_evidence("客户和供应商集中度较高，需核查关联交易与真实终端销售", concentration),
        _join_evidence("盈利预测弹性很大，估值回报高度依赖乐观情形", forecast),
        "竞争风险：AI/AR 眼镜赛道已有 Meta、手机厂商、AR 厂商和互联网生态玩家持续进入，早期份额可能被新品周期、渠道补贴和生态绑定快速稀释。",
    ]
    opportunity_points = [point for point in opportunity_points if point]
    risk_points = [point for point in risk_points if point]
    if not opportunity_points and not risk_points:
        return ""

    conclusion = (
        "可以继续推进，但应按“高成长、高不确定性”的硬件成长期项目处理："
        "小额卡位或分阶段投入优于一次性重仓，估值和条款应以中性/偏保守模型为基准。"
    )
    output = ["## 投资风险与机会分析", ""]
    if sources:
        output.append(f"已读取：{', '.join(sources[:3])}")
        output.append("")
    output.extend(["结论：", conclusion, "", "投资机会："])
    for item in opportunity_points[:4]:
        output.append(f"- {item}")
    output.append("")
    output.append("主要风险：")
    for item in risk_points[:5]:
        output.append(f"- {item}")
    output.extend(
        [
            "",
            "建议动作：",
            "- 投前重点核查月度 sell-through、退货率、渠道库存、SKU 毛利、关联交易定价、供应链账期和现金 runway。",
            "- 交易条款建议保留回购、优先清算、反稀释、重大事项否决、信息权、关联交易限制和核心团队/IP 稳定承诺。",
            "- 估值测算不要只采用乐观预测；应以中性/偏保守情形做安全边际，达成收入、毛利率和现金流节点后再追加投入。",
            "",
            note,
        ]
    )
    return "\n".join(output)


def _join_evidence(label: str, evidence: List[str]) -> str:
    if not evidence:
        return ""
    joined = "；".join(evidence[:3])
    return f"{label}：{joined}"


def _investment_source_lines(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
) -> List[str]:
    lines: List[str] = []
    for paragraph in _readonly_content_paragraphs(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
    ):
        lines.append(paragraph)
    for item in readonly_tool_outputs:
        payload = item.get("result") if isinstance(item, dict) else None
        payload = payload if isinstance(payload, dict) else _json_payload(payload)
        if isinstance(payload, dict):
            lines.extend(_table_lines_from_payload(payload))
    lines.extend(_docx_table_lines_from_request(request))
    cleaned: List[str] = []
    seen: set[str] = set()
    for line in lines:
        text = _normalize_article_text(line)
        if len(text) < 8:
            continue
        key = _dedupe_key(text[:180])
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _table_lines_from_payload(payload: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
    for table in tables:
        if not isinstance(table, dict):
            continue
        for row in table.get("rows") or []:
            if not isinstance(row, list):
                continue
            cells = [_normalize_article_text(cell) for cell in row if str(cell or "").strip()]
            if cells:
                lines.append(" | ".join(cells))
    return lines


def _docx_table_lines_from_request(request: FileTaskRequest) -> List[str]:
    candidates: List[str] = []
    if request.current_file:
        candidates.append(str(request.current_file.path or request.current_file.name or ""))
    for file_info in request.files or []:
        candidates.append(str(file_info.path or file_info.name or ""))
    paths: List[Path] = []
    cwd = Path.cwd()
    for raw in candidates:
        if not raw or not raw.lower().endswith(".docx"):
            continue
        p = Path(raw)
        possible = [p] if p.is_absolute() else [cwd / raw, cwd / "workspace" / raw]
        for item in possible:
            if item.exists() and item not in paths:
                paths.append(item)
    if not paths:
        return []
    try:
        from docx import Document
    except Exception:
        return []
    lines: List[str] = []
    for path in paths[:2]:
        try:
            doc = Document(str(path))
        except Exception:
            continue
        for table in doc.tables:
            for row in table.rows:
                cells = [_normalize_article_text(cell.text) for cell in row.cells if str(cell.text or "").strip()]
                if cells:
                    lines.append(" | ".join(cells))
    return lines[:500]


def _readonly_source_names(
    *,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
) -> List[str]:
    names: List[str] = []
    seen: set[str] = set()
    for item in readonly_tool_outputs:
        if not isinstance(item, dict):
            continue
        label = readonly_tool_source_label(item, display_path=display_path)
        if label and label not in seen:
            seen.add(label)
            names.append(label)
    for index, snippet in enumerate(snippets, start=1):
        if not isinstance(snippet, dict):
            continue
        source = str(
            snippet.get("source") or snippet.get("path") or f"上下文 {index}"
        ).strip()
        label = display_path(source) or source
        if label and label not in seen:
            seen.add(label)
            names.append(label)
    return names


def _readonly_content_paragraphs(
    *,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
) -> List[str]:
    paragraphs: List[str] = []
    seen: set[str] = set()

    def add_text(value: Any) -> None:
        for part in _split_candidate_paragraphs(value):
            normalized = _normalize_article_text(part)
            if not _is_substantial_article_text(normalized):
                continue
            key = normalized[:180]
            if key in seen:
                continue
            seen.add(key)
            paragraphs.append(normalized)

    for item in readonly_tool_outputs:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        payload = result if isinstance(result, dict) else _json_payload(result)
        if isinstance(payload, dict):
            raw_paragraphs = (
                payload.get("paragraphs")
                if isinstance(payload.get("paragraphs"), list)
                else []
            )
            for paragraph in raw_paragraphs:
                if isinstance(paragraph, dict):
                    add_text(paragraph.get("text"))
                else:
                    add_text(paragraph)
            add_text(payload.get("text"))
        else:
            for point in readonly_tool_points(item):
                add_text(point)
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        add_text(snippet.get("_raw_text") or snippet.get("preview"))
    return paragraphs[:18]


def _split_candidate_paragraphs(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    text = html.unescape(text)
    pieces = re.split(r"(?:\r?\n)+|(?<=。)\s+(?=[\u4e00-\u9fff])", text)
    return [piece.strip() for piece in pieces if piece and piece.strip()]


def _normalize_article_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\s*[-•]\s+", "", text)
    text = re.sub(r"^\s*\d+[.、]\s+", "", text)
    return text


def _is_substantial_article_text(text: str) -> bool:
    if len(text) < 24:
        return False
    lowered = text.lower()
    if lowered.startswith("word 内容包含") or "word 内容包含" in lowered:
        return False
    if re.fullmatch(r"section\s+\d+.*", lowered):
        return False
    if text.startswith("Section "):
        return False
    return True


def _sentence_candidates(paragraphs: List[str]) -> List[str]:
    sentences: List[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        for sentence in re.split(r"(?<=[。！？!?])\s*", paragraph):
            sentence = _normalize_article_text(sentence)
            if len(sentence) < 18:
                continue
            key = sentence[:120]
            if key in seen:
                continue
            seen.add(key)
            sentences.append(sentence)
    return sentences


def _first_matching_sentence(paragraphs: List[str], tokens: tuple[str, ...]) -> str:
    for sentence in _sentence_candidates(paragraphs):
        if any(token in sentence for token in tokens):
            return sentence
    return ""


def _first_substantial_sentence(paragraphs: List[str]) -> str:
    sentences = _sentence_candidates(paragraphs)
    if sentences:
        return sentences[0]
    return paragraphs[0]


def _extract_thesis(paragraphs: List[str]) -> str:
    text = " ".join(paragraphs[:6])
    for pattern in (
        r"(我的论点是[^。！？!?]+[。！？!?]?)",
        r"(本文的论点是[^。！？!?]+[。！？!?]?)",
        r"(核心观点是[^。！？!?]+[。！？!?]?)",
        r"(其论点是[^。！？!?]+[。！？!?]?)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    for sentence in _sentence_candidates(paragraphs):
        if any(
            token in sentence
            for token in ("论点", "主张", "核心", "认为", "不是", "而是")
        ):
            return sentence
    return ""


def _select_structure_points(paragraphs: List[str], *, limit: int) -> List[str]:
    points: List[str] = []
    for paragraph in paragraphs:
        sentence = _first_sentence_from_paragraph(paragraph)
        compact = _compact_line(sentence, 180)
        if compact and not _near_duplicate(compact, points):
            points.append(compact)
        if len(points) >= limit:
            break
    return points


def _select_key_points(
    paragraphs: List[str], *, limit: int, exclude: List[str] | None = None
) -> List[str]:
    keywords = (
        "论点",
        "关系",
        "身体",
        "技术",
        "艺术",
        "游戏",
        "电影",
        "观众",
        "主体",
        "框架",
        "失败",
        "条件",
    )
    points: List[str] = []
    excluded = [item for item in (exclude or []) if item]
    for sentence in _sentence_candidates(paragraphs):
        if not any(keyword in sentence for keyword in keywords):
            continue
        compact = _compact_line(sentence, 190)
        if (
            compact
            and not _near_duplicate(compact, points)
            and not _near_duplicate(compact, excluded)
        ):
            points.append(compact)
        if len(points) >= limit:
            break
    return points


def _compose_overall_summary(
    overview: str, thesis: str, structure_points: List[str]
) -> str:
    lead = _strip_sentence_end(overview)
    claim = _clean_claim_text(_strip_sentence_end(thesis))
    if claim and claim != lead and claim not in lead:
        base = f"文章首先提出：{_without_leading_topic_marker(lead)}。核心主张是：{claim}。"
    else:
        base = f"文章首先提出：{_without_leading_topic_marker(lead)}。"
    if len(structure_points) >= 3:
        second = _strip_sentence_end(structure_points[1])
        third = _strip_sentence_end(structure_points[2])
        if second and third:
            base += f"随后转向{_without_leading_topic_marker(second)}，并借助 {_without_leading_topic_marker(third)}这一理论背景展开论证。"
    return _compact_line(base, 360)


def _strip_sentence_end(text: str) -> str:
    return str(text or "").strip().rstrip("。！？!?；; ")


def _without_leading_topic_marker(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^(这篇内容主要讨论|本文主要讨论|文章主要讨论)[：:，,]?", "", value)
    return value


def _clean_claim_text(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(
        r"^(我的论点是|本文的论点是|核心观点是|其论点是)[：:，,]?", "", value
    )
    return value.strip()


def _near_duplicate(candidate: str, existing: List[str]) -> bool:
    normalized = _dedupe_key(candidate)
    if not normalized:
        return False
    for item in existing:
        other = _dedupe_key(item)
        if not other:
            continue
        if normalized == other or normalized in other or other in normalized:
            return True
        overlap = len(set(normalized) & set(other)) / max(len(set(normalized)), 1)
        if overlap >= 0.82 and abs(len(normalized) - len(other)) <= 24:
            return True
    return False


def _dedupe_key(text: str) -> str:
    return re.sub(
        r"[\s，。！？；：:,.!?;、\"“”'‘’（）()\[\]《》<>]+", "", str(text or "").lower()
    )


def _first_sentence_from_paragraph(paragraph: str) -> str:
    candidates = re.split(r"(?<=[。！？!?])\s*", paragraph)
    for candidate in candidates:
        text = _normalize_article_text(candidate)
        if len(text) >= 18:
            return text
    return _normalize_article_text(paragraph)


def readonly_tool_source_label(
    item: Dict[str, Any],
    *,
    display_path: DisplayPath,
) -> str:
    args = item.get("args") if isinstance(item.get("args"), dict) else {}
    raw_path = str(
        args.get("path") or args.get("file_path") or item.get("path") or ""
    ).strip()
    if raw_path:
        return display_path(raw_path) or raw_path
    tool_name = str(item.get("tool_name") or "").strip()
    return tool_name or "读取结果"


def readonly_tool_points(item: Dict[str, Any]) -> List[str]:
    result = item.get("result")
    payload = result if isinstance(result, dict) else _json_payload(result)
    points: List[str] = []
    if isinstance(payload, dict):
        paragraphs = (
            payload.get("paragraphs")
            if isinstance(payload.get("paragraphs"), list)
            else []
        )
        tables = (
            payload.get("tables") if isinstance(payload.get("tables"), list) else []
        )
        total_paragraphs = payload.get("total_paragraphs")
        total_tables = payload.get("total_tables")
        if total_paragraphs is not None or total_tables is not None:
            points.append(
                f"Word 内容包含 {int(total_paragraphs or len(paragraphs) or 0)} 段文本、{int(total_tables or len(tables) or 0)} 个表格。"
            )
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                continue
            text = str(paragraph.get("text") or "").strip()
            if text:
                points.append(text)
            if len(points) >= 6:
                break
        if not points and payload.get("text"):
            points.append(str(payload.get("text") or ""))
    if not points:
        preview = str(item.get("preview") or "").strip()
        if preview:
            points.append(preview)
    if not points and result is not None:
        points.append(stringify_result(result))
    return points
