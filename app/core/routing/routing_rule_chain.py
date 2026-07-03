# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Composable Routing Rule Chain.

Replaces the monolithic if/elif cascade in SmartDispatcher.analyze() with
a pipeline of independent RoutingRuleNode objects.  Each node checks a specific
condition and either produces a routing result or passes control to the next node.

Architecture:
    analyze(input)  -->  [RuleNode] --> [RuleNode] --> ... --> fallback(CHAT)
"""

from __future__ import annotations

import logging
import re as _re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.agent.file_task_review_intent import should_route_docx_file_edit
from app.core.routing.routing_config import (
    AGENT_NOTIFY_PATTERNS,
    AGENT_SAFETY_PATTERNS,
    ANNOTATE_FILE_TYPES,
    CHART_KEYWORDS,
    CHART_KNOWLEDGE_GUARDS,
    CODE_CONCEPTS,
    CODE_LANGS,
    CODE_WRITE_VERBS,
    DOC_GEN_ACTION_KEYWORDS,
    DOC_GEN_OUTPUT_KEYWORDS,
    DOC_GEN_QUESTION_GUARDS,
    EDIT_INTENT_KEYWORDS,
    FILE_SEARCH_PATTERNS,
    FORCE_PLAN_TRIGGERS,
    MEETING_NOUNS,
    MEETING_QUESTION_GUARDS,
    MEETING_VERBS,
    PAINTER_CHART_EXCLUDE,
    PAINTER_PATTERNS,
    PATH_LIST_KEYWORDS,
    PPT_ACTION_WORDS,
    PPT_DIRECT_KEYWORDS,
    PPT_QUESTION_GUARDS,
    PRICE_ASSETS,
    PRICE_SIGNALS,
    REALTIME_EXCLUDE,
    REALTIME_SIGNALS,
    REALTIME_TOPICS,
    SEARCH_FOLLOWUP_VERBS,
    TRAVEL_BUY_KEYWORDS,
    TRAVEL_SEARCH_PATTERNS,
    WEATHER_KEYWORDS,
    WORKFLOW_FILE_TYPES,
)

logger = logging.getLogger(__name__)

# ── Result type for rule chain ────────────────────────────────────────────────
RoutingResult = Optional[Tuple[str, str, Optional[Dict]]]


def _has_workflow_file_edit_intent(user_lower: str) -> bool:
    return any(kw in user_lower for kw in EDIT_INTENT_KEYWORDS)


@dataclass
class RuleContext:
    """Immutable context passed through the rule chain."""

    user_input: str
    user_lower: str
    file_context: Optional[Dict]
    similarity_scores: Dict[str, float]
    LocalExecutor: Any = None
    ContextAnalyzer: Any = None
    WebSearcher: Any = None
    history: Optional[List] = None


class RuleNode:
    """One link in the routing chain.  Has a check function and optional
    routing result builder."""

    def __init__(
        self,
        name: str,
        check: Callable[[RuleContext], bool],
        build_result: Callable[[RuleContext], RoutingResult],
    ) -> None:
        self.name = name
        self._check = check
        self._build = build_result
        self._next: "Optional[RuleNode]" = None


class RuleChain:
    """Ordered chain of RuleNodes evaluated sequentially.

    Usage::

        chain = RuleChain()
        chain.add_node("trivial", check_fn, build_fn)
        chain.add_node("weather", check_fn, build_fn)
        ...
        result = chain.run(ctx)
    """

    def __init__(self, smart_dispatcher: Any) -> None:
        self._head: Optional[RuleNode] = None
        self._tail: Optional[RuleNode] = None
        self._dispatcher = smart_dispatcher  # for _build_routing_list etc.

    def add_node(
        self,
        name: str,
        check: Callable[[RuleContext], bool],
        build: Callable[[RuleContext], RoutingResult],
    ) -> None:
        node = RuleNode(name, check, build)
        if self._head is None:
            self._head = node
            self._tail = node
        else:
            self._tail._next = node
            self._tail = node

    def run(self, ctx: RuleContext) -> RoutingResult:
        node = self._head
        while node is not None:
            if node._check(ctx):
                return node._build(ctx)
            node = node._next
        return None

    # ── helpers that delegate to dispatcher classmethods ──────────────────────

    def _build_routing_list(
        self,
        scores: Dict[str, float],
        boosts: Dict[str, float] = None,
        reasons: Dict[str, List[str]] = None,
    ) -> List[Dict]:
        return self._dispatcher._build_routing_list(scores, boosts=boosts, reasons=reasons)

    def _apply_safety(
        self, task_type: str, ctx: RuleContext
    ) -> str:
        return self._dispatcher._apply_routing_safety(
            task_type,
            ctx.user_input,
            ctx.user_lower,
            ctx.file_context,
            ctx.LocalExecutor,
            ctx.WebSearcher,
        )

    # ── check/build functions for each rule ───────────────────────────────────

    # 0. Force Plan
    def _check_force_plan(self, ctx: RuleContext) -> bool:
        return ctx.user_input.strip().startswith("/plan ") or any(
            t in ctx.user_input for t in FORCE_PLAN_TRIGGERS
        )

    def _build_force_plan(self, ctx: RuleContext) -> RoutingResult:
        info = {"complexity": "complex", "is_multi_step_task": True}
        info["multi_step_info"] = {
            "pattern": "forced_plan",
            "description": "User forced planning mode",
        }
        info["routing_list"] = self._build_routing_list(
            ctx.similarity_scores,
            boosts={"MULTI_STEP": 1.0},
            reasons={"MULTI_STEP": ["user_forced"]},
        )
        return "MULTI_STEP", "🛠️ Forced-Plan", info

    # 1. Capability / How-To Query
    def _check_capability_query(self, ctx: RuleContext) -> bool:
        from app.core.routing.rule_router import RuleRouter
        return RuleRouter.is_capability_or_howto_query(ctx.user_input)

    def _build_capability_query(self, ctx: RuleContext) -> RoutingResult:
        info = {}
        info["routing_list"] = self._build_routing_list(
            ctx.similarity_scores,
            boosts={"CHAT": 1.0},
            reasons={"CHAT": ["rule:capability_or_howto_query"]},
        )
        logger.info("[RuleChain] 💬 能力/方法询问快速通道 → CHAT")
        return "CHAT", "💬 Capability/HowTo-Query", info

    # 2. File attachment with edit intent
    def _check_file_edit(self, ctx: RuleContext) -> bool:
        fc = ctx.file_context
        if not (fc and fc.get("has_file")):
            return False
        file_ext = fc.get("file_type", "")
        if file_ext in ANNOTATE_FILE_TYPES:
            return should_route_docx_file_edit(ctx.user_input, has_file=True)
        if file_ext in WORKFLOW_FILE_TYPES:
            return _has_workflow_file_edit_intent(ctx.user_lower)
        return False

    def _build_file_edit(self, ctx: RuleContext) -> RoutingResult:
        file_ext = ctx.file_context.get("file_type", "")
        if file_ext in ANNOTATE_FILE_TYPES:
            info = {"complexity": "complex"}
            info["routing_list"] = self._build_routing_list(
                ctx.similarity_scores,
                boosts={"DOC_ANNOTATE": 1.0},
                reasons={"DOC_ANNOTATE": ["rule:doc_annotate"]},
            )
            logger.info(f"[RuleChain] 📄 Word 文档标注请求: {file_ext}")
            return "DOC_ANNOTATE", "📄 Doc-Annotate", info
        info = {"complexity": "complex"}
        info["routing_list"] = self._build_routing_list(
            ctx.similarity_scores,
            boosts={"FILE_GEN": 0.9},
            reasons={"FILE_GEN": ["rule:file_edit"]},
        )
        logger.info(f"[RuleChain] 📄 文件编辑请求: {file_ext}")
        return "FILE_GEN", "📄 File-Edit", info

    # 3. Short input (≤3 chars) → SYSTEM or CHAT
    def _check_short_input(self, ctx: RuleContext) -> bool:
        # strip [FILE_ATTACHED:ext] prefix for length check
        from app.core.routing.rule_router import RuleRouter
        cleaned = _re.sub(r"^\[FILE_ATTACHED:[^\]]+\]\s*", "", ctx.user_input).strip()
        return len(cleaned) <= 3 and RuleRouter.quick_task_hint(cleaned) == "CHAT"

    def _build_short_input(self, ctx: RuleContext) -> RoutingResult:
        cleaned = _re.sub(r"^\[FILE_ATTACHED:[^\]]+\]\s*", "", ctx.user_input).strip()
        if ctx.LocalExecutor and ctx.LocalExecutor.is_system_command(cleaned):
            info = {"routing_list": self._build_routing_list(
                ctx.similarity_scores,
                boosts={"SYSTEM": 1.0},
                reasons={"SYSTEM": ["rule:standalone_command"]},
            )}
            return "SYSTEM", "🖥️ Rule-Detected", info
        return "CHAT", "⚡ Quick", None

    # 4. Path listing (Windows path in input)
    def _check_path_listing(self, ctx: RuleContext) -> bool:
        return bool(_re.search(r"[A-Za-z]:[\\]", ctx.user_input)) and any(
            k in ctx.user_input for k in PATH_LIST_KEYWORDS
        )

    def _build_path_listing(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"FILE_SEARCH": 1.0},
            reasons={"FILE_SEARCH": ["rule:path_listing"]},
        )}
        logger.info("[RuleChain] 📁 指定路径列举快速通道 → FILE_SEARCH")
        return "FILE_SEARCH", "📁 Path-Listing", info

    # 5. Agent Notify (reminders, messages)
    def _check_agent_notify(self, ctx: RuleContext) -> bool:
        return any(_re.search(p, ctx.user_input) for p in AGENT_NOTIFY_PATTERNS)

    def _build_agent_notify(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"AGENT": 1.0},
            reasons={"AGENT": ["rule:agent_notify_direct"]},
        )}
        logger.info("[RuleChain] 🤖 提醒/消息快速通道 → AGENT")
        return "AGENT", "🤖 Notify-Direct", info

    # 6. Painter (AI image generation)
    def _check_painter(self, ctx: RuleContext) -> bool:
        if not any(_re.search(p, ctx.user_input) for p in PAINTER_PATTERNS):
            return False
        return not any(k in ctx.user_lower for k in PAINTER_CHART_EXCLUDE)

    def _build_painter(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"PAINTER": 1.0},
            reasons={"PAINTER": ["rule:image_gen"]},
        )}
        logger.info("[RuleChain] 🎨 图片生成快速通道 → PAINTER")
        return "PAINTER", "🎨 Image-Direct", info

    # 7. Trivial input
    def _check_trivial(self, ctx: RuleContext) -> bool:
        from app.core.routing.rule_router import RuleRouter
        cleaned = _re.sub(r"^\[FILE_ATTACHED:[^\]]+\]\s*", "", ctx.user_input).strip()
        return RuleRouter.is_trivial(cleaned)

    def _build_trivial(self, ctx: RuleContext) -> RoutingResult:
        cleaned = _re.sub(r"^\[FILE_ATTACHED:[^\]]+\]\s*", "", ctx.user_input).strip()
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"CHAT": 1.0},
            reasons={"CHAT": ["rule:trivial"]},
        )}
        logger.info(f"[RuleChain] ⚡ 极简通道: '{cleaned[:20]}' → CHAT")
        return "CHAT", "⚡ Trivial", info

    # 8. Weather
    def _check_weather(self, ctx: RuleContext) -> bool:
        return any(k in ctx.user_lower for k in WEATHER_KEYWORDS)

    def _build_weather(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"WEB_SEARCH": 1.0},
            reasons={"WEB_SEARCH": ["rule:weather_direct"]},
        )}
        return "WEB_SEARCH", "🌤️ Weather-Direct", info

    # 9. Meeting extract
    def _check_meeting(self, ctx: RuleContext) -> bool:
        return (
            any(v in ctx.user_lower for v in MEETING_VERBS)
            and any(n in ctx.user_lower for n in MEETING_NOUNS)
            and not any(g in ctx.user_lower for g in MEETING_QUESTION_GUARDS)
        )

    def _build_meeting(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"MEETING_EXTRACT": 1.0},
            reasons={"MEETING_EXTRACT": ["rule:meeting_extract_direct"]},
        )}
        return "MEETING_EXTRACT", "📝 Meeting-Extract-Direct", info

    # 10. Code writing
    def _check_code(self, ctx: RuleContext) -> bool:
        has_verb = any(v in ctx.user_lower for v in CODE_WRITE_VERBS)
        has_concept = any(c in ctx.user_lower for c in CODE_CONCEPTS)
        has_lang = any(l in ctx.user_lower for l in CODE_LANGS)
        return has_verb and (has_concept or has_lang)

    def _build_code(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"CODER": 1.0},
            reasons={"CODER": ["rule:code_write_direct"]},
        )}
        return "CODER", "💻 Code-Write-Direct", info

    # 11. Realtime info
    def _check_realtime(self, ctx: RuleContext) -> bool:
        return (
            any(s in ctx.user_lower for s in REALTIME_SIGNALS)
            and any(t in ctx.user_lower for t in REALTIME_TOPICS)
            and not any(e in ctx.user_lower for e in REALTIME_EXCLUDE)
        )

    def _build_realtime(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"WEB_SEARCH": 1.0},
            reasons={"WEB_SEARCH": ["rule:realtime_signal"]},
        )}
        return "WEB_SEARCH", "⏰ Realtime-Direct", info

    # 12. Charts / data visualization
    def _check_chart(self, ctx: RuleContext) -> bool:
        return any(k in ctx.user_lower for k in CHART_KEYWORDS) and not any(
            g in ctx.user_lower for g in CHART_KNOWLEDGE_GUARDS
        )

    def _build_chart(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"CODER": 1.0},
            reasons={"CODER": ["rule:chart_viz"]},
        )}
        return "CODER", "📊 Chart-Direct", info

    # 13. Travel search
    def _check_travel(self, ctx: RuleContext) -> bool:
        return any(_re.search(p, ctx.user_input) for p in TRAVEL_SEARCH_PATTERNS)

    def _build_travel(self, ctx: RuleContext) -> RoutingResult:
        if any(k in ctx.user_lower for k in TRAVEL_BUY_KEYWORDS):
            info = {"routing_list": self._build_routing_list(
                ctx.similarity_scores,
                boosts={"AGENT": 1.0},
                reasons={"AGENT": ["rule:ticket_buy"]},
            )}
            return "AGENT", "🤖 Ticket-Buy", info
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"WEB_SEARCH": 1.0},
            reasons={"WEB_SEARCH": ["rule:travel_query"]},
        )}
        return "WEB_SEARCH", "🌐 Travel-Query", info

    # 14. Financial price
    def _check_finance(self, ctx: RuleContext) -> bool:
        has_asset = any(k in ctx.user_lower for k in PRICE_ASSETS)
        has_signal = any(k in ctx.user_lower for k in PRICE_SIGNALS)
        return has_asset and (has_signal or len(ctx.user_input.strip()) <= 12)

    def _build_finance(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"WEB_SEARCH": 1.0},
            reasons={"WEB_SEARCH": ["rule:financial_price"]},
        )}
        return "WEB_SEARCH", "💹 Price-Direct", info

    # 15. PPT direct
    def _check_ppt(self, ctx: RuleContext) -> bool:
        return (
            any(k in ctx.user_lower for k in PPT_DIRECT_KEYWORDS)
            and any(a in ctx.user_lower for a in PPT_ACTION_WORDS)
            and not any(q in ctx.user_lower for q in PPT_QUESTION_GUARDS)
        )

    def _build_ppt(self, ctx: RuleContext) -> RoutingResult:
        info = {"complexity": "complex"}
        info["routing_list"] = self._build_routing_list(
            ctx.similarity_scores,
            boosts={"FILE_GEN": 1.0},
            reasons={"FILE_GEN": ["fallback:ppt_direct"]},
        )
        return "FILE_GEN", "📄 PPT-Direct", info

    # 16. Document generation
    def _check_docgen(self, ctx: RuleContext) -> bool:
        return (
            any(k in ctx.user_lower for k in DOC_GEN_OUTPUT_KEYWORDS)
            and any(a in ctx.user_lower for a in DOC_GEN_ACTION_KEYWORDS)
            and not any(q in ctx.user_lower for q in DOC_GEN_QUESTION_GUARDS)
        )

    def _build_docgen(self, ctx: RuleContext) -> RoutingResult:
        info = {"complexity": "complex"}
        info["routing_list"] = self._build_routing_list(
            ctx.similarity_scores,
            boosts={"FILE_GEN": 1.0},
            reasons={"FILE_GEN": ["fallback:doc_gen_direct"]},
        )
        return "FILE_GEN", "📄 DocGen-Direct", info

    # 17. File search (global)
    def _check_file_search(self, ctx: RuleContext) -> bool:
        return any(_re.search(p, ctx.user_input) for p in FILE_SEARCH_PATTERNS)

    def _build_file_search(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"FILE_SEARCH": 1.0},
            reasons={"FILE_SEARCH": ["rule:disk_file_search"]},
        )}
        return "FILE_SEARCH", "🔍 FileSearch-Direct", info

    # 18. System command
    def _check_system(self, ctx: RuleContext) -> bool:
        return bool(ctx.LocalExecutor and ctx.LocalExecutor.is_system_command(ctx.user_input))

    def _build_system(self, ctx: RuleContext) -> RoutingResult:
        info = {"routing_list": self._build_routing_list(
            ctx.similarity_scores,
            boosts={"SYSTEM": 0.9},
            reasons={"SYSTEM": ["fallback:system"]},
        )}
        return "SYSTEM", "🖥️ Fallback-System", info


def build_rule_chain(dispatcher: Any) -> RuleChain:
    """Construct the standard rule chain for SmartDispatcher."""
    chain = RuleChain(dispatcher)

    chain.add_node("force_plan", chain._check_force_plan, chain._build_force_plan)
    chain.add_node("capability_query", chain._check_capability_query, chain._build_capability_query)
    # Deterministic rules run before model_primary_route so obvious action
    # requests cannot be downgraded by a weak or unavailable classifier.
    chain.add_node("file_edit", chain._check_file_edit, chain._build_file_edit)
    chain.add_node("short_input", chain._check_short_input, chain._build_short_input)
    chain.add_node("path_listing", chain._check_path_listing, chain._build_path_listing)
    chain.add_node("agent_notify", chain._check_agent_notify, chain._build_agent_notify)
    chain.add_node("painter", chain._check_painter, chain._build_painter)
    chain.add_node("trivial", chain._check_trivial, chain._build_trivial)
    chain.add_node("weather", chain._check_weather, chain._build_weather)
    chain.add_node("meeting", chain._check_meeting, chain._build_meeting)
    chain.add_node("code", chain._check_code, chain._build_code)
    chain.add_node("realtime", chain._check_realtime, chain._build_realtime)
    chain.add_node("chart", chain._check_chart, chain._build_chart)
    chain.add_node("travel", chain._check_travel, chain._build_travel)
    chain.add_node("finance", chain._check_finance, chain._build_finance)
    chain.add_node("ppt", chain._check_ppt, chain._build_ppt)
    chain.add_node("docgen", chain._check_docgen, chain._build_docgen)
    chain.add_node("file_search", chain._check_file_search, chain._build_file_search)
    chain.add_node("system", chain._check_system, chain._build_system)

    return chain
