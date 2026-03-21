# -*- coding: utf-8 -*-
"""
Deep Research Agent
===================
仿照 OpenAI Deep Research / Perplexity Deep Research / Google Gemini Deep Research
的迭代调研模式，原创实现，无任何复制自闭源代码。

核心流程（参考公开论文和产品文档中的描述）：

  1. Query Decomposition  — 将用户问题拆解为 N 个子问题
  2. Parallel Search       — 并行网络搜索每个子问题
  3. Evidence Aggregation  — 合并证据，去重，格式化
  4. Gap Detection         — LLM 判断还缺哪些信息
  5. Follow-up Search      — 针对 gap 再搜索（最多 MAX_ROUNDS 轮）
  6. Final Synthesis       — 合成带引用的完整调研报告

与 Koto 集成方式
-----------------
  - 依赖 ToolRegistry 中已注册的 web_search 工具（来自 SearchPlugin）
  - 直接调用 LLMProvider.generate_text() 接口
  - 通过 progress_bus 发送实时进度事件（前端可实时展示）
  - 最终报告写入 TaskLedger

用法
----
    from app.core.agent.deep_research import DeepResearchAgent

    agent = DeepResearchAgent(
        llm_provider=get_llm_provider(),
        tool_registry=registry,          # 需已注册 web_search
        model_id="gemini-2.5-flash",
        max_rounds=3,
        queries_per_round=4,
    )

    for event in agent.run("分析2026年大模型Agent技术的最新进展和竞争格局"):
        print(event)                      # dict: {"type": "progress"|"result", ...}
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

# ── 默认参数 ──────────────────────────────────────────────────────────────────
_DEFAULT_MAX_ROUNDS = 3          # 最多几轮迭代搜索
_DEFAULT_QUERIES_PER_ROUND = 4   # 每轮并行子查询数
_DEFAULT_MAX_RESULTS_PER_Q = 5   # 每个查询最多取几条结果
_DEFAULT_SEARCH_TIMEOUT = 15     # 单次搜索超时秒数


# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    query: str
    content: str
    source: str = ""
    round_num: int = 0


@dataclass
class ResearchState:
    original_query: str
    sub_queries: List[str] = field(default_factory=list)
    results: List[SearchResult] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    current_round: int = 0
    final_report: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Prompt 模板
# ─────────────────────────────────────────────────────────────────────────────

_DECOMPOSE_PROMPT = """\
你是一位专业调研策略师。用户想深入了解以下问题：

"{query}"

请将这个问题拆解为 {n} 个独立的、互补的搜索子问题。
每个子问题应聚焦于不同的角度（如：技术原理、市场格局、最新进展、案例对比、未来趋势等）。

要求：
- 每个子问题都是完整、具体、可被搜索引擎理解的查询语句
- 子问题之间不重叠
- 使用中文提问

输出格式（只输出 JSON，无其他文字）：
{{"queries": ["子问题1", "子问题2", "子问题3", "子问题4"]}}
"""

_GAP_DETECTION_PROMPT = """\
你是一位批判性调研分析师。用户的原始问题是：
"{original_query}"

目前已通过多次搜索收集到以下证据（摘要）：
{evidence_summary}

请评估：
1. 上述证据是否足以全面回答用户的问题？
2. 还缺少哪些关键信息？

如果信息已经足够，输出：
{{"sufficient": true, "gaps": []}}

如果信息不足，列出 2-3 个具体的补充搜索问题：
{{"sufficient": false, "gaps": ["补充问题1", "补充问题2"]}}

只输出 JSON，无其他文字。
"""

_SYNTHESIS_PROMPT = """\
你是一位专业调研报告撰写者。请根据以下收集到的证据，为用户撰写一份**深度调研报告**。

用户的原始问题：
{original_query}

收集到的证据：
{evidence}

撰写要求：
- 用 Markdown 格式
- 包含：执行摘要、背景分析、核心发现（多角度）、深度分析、结论与展望
- 如证据中有来源信息，在对应内容后标注 [来源]
- 语言：中文，专业严谨
- 长度：1500-3000字（根据问题复杂度）
- 在报告末尾列出《参考来源》

不要编造任何超出提供证据范围的事实。
"""


# ─────────────────────────────────────────────────────────────────────────────
# DeepResearchAgent
# ─────────────────────────────────────────────────────────────────────────────

class DeepResearchAgent:
    """
    迭代式深度调研代理。

    不依赖 UnifiedAgent / LangGraph，作为独立的高层编排器，
    内部直接调用 LLMProvider 和搜索工具。
    """

    def __init__(
        self,
        llm_provider,
        tool_registry=None,
        model_id: str = "gemini-2.5-flash",
        max_rounds: int = _DEFAULT_MAX_ROUNDS,
        queries_per_round: int = _DEFAULT_QUERIES_PER_ROUND,
        max_results_per_query: int = _DEFAULT_MAX_RESULTS_PER_Q,
        search_timeout: int = _DEFAULT_SEARCH_TIMEOUT,
        session_id: str = "",
    ):
        self.llm = llm_provider
        self.registry = tool_registry
        self.model_id = model_id
        self.max_rounds = max_rounds
        self.queries_per_round = queries_per_round
        self.max_results_per_query = max_results_per_query
        self.search_timeout = search_timeout
        self.session_id = session_id

        # 尝试获取 progress bus
        self._progress_bus = None
        self._ProgressEvent = None
        try:
            from app.core.tasks.progress_bus import ProgressEvent, get_progress_bus
            self._progress_bus = get_progress_bus()
            self._ProgressEvent = ProgressEvent
        except Exception as _e:
            logger.warning("[DeepResearch] ProgressBus 加载失败: %s", _e)

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def run(
        self,
        query: str,
        task_id: str = "",
    ) -> Generator[Dict[str, Any], None, None]:
        """
        执行深度调研，通过 Generator 流式输出进度事件和最终报告。

        每个 yield 的 dict 格式：
          {"type": "progress", "stage": str, "message": str, "round": int}
          {"type": "result",   "report": str, "query": str, "rounds": int}
          {"type": "error",    "message": str}
        """
        state = ResearchState(original_query=query)
        start_time = time.time()

        try:
            # ── 阶段 1：问题分解 ─────────────────────────────────────────
            yield self._evt("progress", "decompose", f"正在分解问题：{query[:50]}...", 0)
            state.sub_queries = self._decompose_query(query, self.queries_per_round)
            yield self._evt(
                "progress", "decompose",
                f"拆解出 {len(state.sub_queries)} 个子问题：{', '.join(state.sub_queries[:2])}...", 0
            )

            # ── 阶段 2-4：迭代搜索 ──────────────────────────────────────
            for round_num in range(1, self.max_rounds + 1):
                state.current_round = round_num
                queries_this_round = (
                    state.sub_queries if round_num == 1 else state.gaps
                )

                if not queries_this_round:
                    break

                yield self._evt(
                    "progress", "search",
                    f"第 {round_num} 轮搜索：{len(queries_this_round)} 个查询...", round_num
                )

                # 并行搜索
                new_results = self._parallel_search(queries_this_round, round_num)
                state.results.extend(new_results)

                yield self._evt(
                    "progress", "search",
                    f"第 {round_num} 轮完成，共获得 {len(new_results)} 条新证据", round_num
                )

                # 最后一轮无需检测 gap
                if round_num >= self.max_rounds:
                    break

                # ── gap 检测 ────────────────────────────────────────────
                yield self._evt("progress", "gap", "正在分析证据缺口...", round_num)
                gap_result = self._detect_gaps(query, state.results)
                state.gaps = gap_result.get("gaps", [])

                if gap_result.get("sufficient", False) or not state.gaps:
                    yield self._evt("progress", "gap", "证据已充分，跳过后续轮次", round_num)
                    break

                yield self._evt(
                    "progress", "gap",
                    f"发现 {len(state.gaps)} 个信息缺口，继续补充搜索", round_num
                )

            # ── 阶段 5：最终合成 ─────────────────────────────────────────
            yield self._evt("progress", "synthesis", "正在合成调研报告...", state.current_round)
            report = self._synthesize(query, state.results)
            state.final_report = report

            elapsed = round(time.time() - start_time, 1)
            yield {
                "type": "result",
                "report": report,
                "query": query,
                "rounds": state.current_round,
                "results_count": len(state.results),
                "elapsed_seconds": elapsed,
            }

        except Exception as exc:
            logger.exception(f"[DeepResearch] 异常: {exc}")
            yield {"type": "error", "message": str(exc)}

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _evt(self, type_: str, stage: str, message: str, round_: int) -> Dict:
        """构造进度事件，同时发布到 progress_bus（如可用）。"""
        evt = {"type": type_, "stage": stage, "message": message, "round": round_}
        if self._progress_bus and self._ProgressEvent and self.session_id:
            try:
                self._progress_bus.publish(
                    self._ProgressEvent(
                        session_id=self.session_id,
                        event_type="deep_research",
                        data=evt,
                    )
                )
            except Exception as _e:
                logger.debug("[DeepResearch] ProgressBus 事件发布失败: %s", _e)
        return evt

    def _llm_call(self, prompt: str, temperature: float = 0.3) -> str:
        """统一的 LLM 调用接口，兼容 Koto LLMProvider。"""
        try:
            result = self.llm.generate_text(
                prompt=prompt,
                model_id=self.model_id,
                temperature=temperature,
            )
            # LLMProvider 可能返回 str 或 dict
            if isinstance(result, dict):
                return result.get("text", result.get("content", str(result)))
            return str(result)
        except Exception as e:
            logger.warning(f"[DeepResearch] LLM 调用失败: {e}")
            return ""

    def _extract_json(self, text: str) -> Optional[Dict]:
        """从 LLM 输出中提取 JSON（兼容 markdown code block）。"""
        # 去掉 ```json ... ``` 包装
        text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
        # 找第一个 { ... }
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError as _e:
                logger.debug("[DeepResearch] JSON 解析失败（将返回 None）: %s", _e)
        return None

    def _decompose_query(self, query: str, n: int) -> List[str]:
        """将原始问题拆解为 n 个子问题。"""
        prompt = _DECOMPOSE_PROMPT.format(query=query, n=n)
        raw = self._llm_call(prompt, temperature=0.5)
        data = self._extract_json(raw)
        if data and "queries" in data:
            queries = [str(q).strip() for q in data["queries"] if q]
            return queries[:n] if queries else [query]
        # fallback：直接用原始问题
        logger.warning("[DeepResearch] 子问题分解失败，使用原始问题")
        return [query]

    def _search_one(self, query: str, round_num: int) -> Optional[SearchResult]:
        """执行单次搜索，返回 SearchResult 或 None。"""
        if not self.registry:
            return None
        try:
            raw = self.registry.call_tool("web_search", {"query": query})
            if raw and not str(raw).startswith("Search failed"):
                return SearchResult(
                    query=query,
                    content=str(raw)[:3000],   # 限制单条长度
                    round_num=round_num,
                )
        except Exception as e:
            logger.debug(f"[DeepResearch] 搜索失败 [{query}]: {e}")
        return None

    def _parallel_search(
        self, queries: List[str], round_num: int
    ) -> List[SearchResult]:
        """并行执行多个搜索查询。"""
        results: List[SearchResult] = []
        with ThreadPoolExecutor(max_workers=min(len(queries), 5)) as pool:
            futures = {
                pool.submit(self._search_one, q, round_num): q for q in queries
            }
            for fut in as_completed(futures, timeout=self.search_timeout * len(queries)):
                try:
                    res = fut.result(timeout=self.search_timeout)
                    if res:
                        results.append(res)
                except Exception as e:
                    logger.debug(f"[DeepResearch] 并行搜索异常: {e}")
        return results

    def _build_evidence_summary(self, results: List[SearchResult]) -> str:
        """将所有搜索结果合并为 LLM 可消化的证据字符串。"""
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(
                f"[证据{i}] 来源查询：{r.query}\n"
                f"{r.content[:800]}\n"
            )
        return "\n".join(lines)

    def _detect_gaps(self, original_query: str, results: List[SearchResult]) -> Dict:
        """检测当前证据的信息缺口。"""
        evidence_summary = self._build_evidence_summary(results[-12:])  # 最近12条
        prompt = _GAP_DETECTION_PROMPT.format(
            original_query=original_query,
            evidence_summary=evidence_summary[:6000],
        )
        raw = self._llm_call(prompt, temperature=0.2)
        data = self._extract_json(raw)
        if data:
            return data
        return {"sufficient": True, "gaps": []}

    def _synthesize(self, original_query: str, results: List[SearchResult]) -> str:
        """基于所有证据合成最终报告。"""
        evidence = self._build_evidence_summary(results)
        prompt = _SYNTHESIS_PROMPT.format(
            original_query=original_query,
            evidence=evidence[:12000],   # Gemini 2.5 Flash 支持长上下文
        )
        raw = self._llm_call(prompt, temperature=0.4)
        # 最终报告有害内容检测
        try:
            from app.core.security.output_validator import OutputValidator
            _val = OutputValidator.validate(text=raw)
            if _val.is_blocked:
                logger.warning("[DeepResearch] synthesis 输出被拦截: %s", _val.reasons)
                return _val.text
            return _val.text
        except Exception:
            return raw


# ─────────────────────────────────────────────────────────────────────────────
# 便捷工厂函数
# ─────────────────────────────────────────────────────────────────────────────

def create_deep_research_agent(
    session_id: str = "",
    max_rounds: int = 3,
    queries_per_round: int = 4,
) -> Optional["DeepResearchAgent"]:
    """
    使用 Koto 默认 LLMProvider 和 ToolRegistry 创建 DeepResearchAgent。

    如依赖不可用则返回 None（降级处理）。
    """
    try:
        from app.core.agent.factory import create_agent  # noqa: F401
        from app.core.llm.gemini import GeminiProvider
        from app.core.agent.tool_registry import ToolRegistry
        from app.core.agent.plugins.search_plugin import SearchPlugin
        import os

        api_key = os.environ.get("GEMINI_API_KEY", "")
        llm = GeminiProvider(api_key=api_key)
        registry = ToolRegistry()
        registry.register_plugin(SearchPlugin())

        return DeepResearchAgent(
            llm_provider=llm,
            tool_registry=registry,
            max_rounds=max_rounds,
            queries_per_round=queries_per_round,
            session_id=session_id,
        )
    except Exception as e:
        logger.error(f"[DeepResearch] 初始化失败: {e}")
        return None
