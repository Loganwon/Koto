# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
import logging
import os
from typing import Optional

# 所有重型导入延迟到工厂函数内部，避免增加启动耗时。

logger = logging.getLogger(__name__)


def _resolve_api_key(api_key: Optional[str] = None) -> Optional[str]:
    """统一读取 API Key，兼容项目内所有环境变量命名。"""
    return (
        api_key
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("DEEPSEEK_KEY")
    )


def _build_registry(api_key: Optional[str] = None, full: bool = True) -> "ToolRegistry":
    """
    构建共用的 ToolRegistry 并注册插件。

    Args:
        api_key: DeepSeek API Key（已解析）。
        full:    True → 注册全量插件（UnifiedAgent 用）；
                 False → 仅注册核心插件（LangGraphAgent 轻量模式）。

    Returns:
        配置好的 ToolRegistry 实例。
    """
    from app.core.agent.plugins.basic_tools_plugin import BasicToolsPlugin
    from app.core.agent.plugins.file_editor_plugin import FileEditorPlugin
    from app.core.agent.plugins.search_plugin import SearchPlugin
    from app.core.agent.plugins.system_info_plugin import SystemInfoPlugin
    from app.core.agent.plugins.system_tools_plugin import SystemToolsPlugin
    from app.core.agent.tool_registry import ToolRegistry

    registry = ToolRegistry()

    # ── 核心插件（全量 & 轻量模式均加载） ──────────────────────────────
    registry.register_plugin(BasicToolsPlugin())
    registry.register_plugin(FileEditorPlugin())
    registry.register_plugin(SearchPlugin(api_key=api_key))
    registry.register_plugin(SystemToolsPlugin())
    registry.register_plugin(SystemInfoPlugin())

    # ── P2: 记忆工具（主动写入/检索，升级为优先加载）──────────────────
    # MemoryToolsPlugin 提供 memory_save / memory_search / context_recall，
    # 配合 UnifiedAgent 系统指令中的主动记忆规则，让 LLM 主动管理长期记忆。
    try:
        from app.core.agent.plugins.memory_tools_plugin import MemoryToolsPlugin

        registry.register_plugin(MemoryToolsPlugin())
        logger.debug("[_build_registry] MemoryToolsPlugin 已加载")
    except Exception as _e:
        logger.warning(
            f"[_build_registry] MemoryToolsPlugin 加载失败（记忆工具不可用）: {_e}"
        )

    # ── 可选生产力插件（两种模式均尝试加载，失败则跳过） ─────────────
    for plugin_path, name in [
        ("app.core.agent.plugins.productivity_plugin", "ProductivityPlugin"),
    ]:
        try:
            import importlib

            mod = importlib.import_module(plugin_path)
            cls = getattr(mod, name)
            registry.register_plugin(cls())
        except Exception as _e:
            logger.debug(f"[_build_registry] {name} 跳过: {_e}")

    # ── MCP servers（config/user_settings.json: mcp_servers / mcpServers）────
    # External MCP tools are loaded early so both lightweight LangGraph agents
    # and the full UnifiedAgent can use them.
    try:
        from app.core.agent.mcp_manager import inject_configured_mcp_tools

        mcp_count = inject_configured_mcp_tools(registry)
        if mcp_count:
            logger.info("[_build_registry] MCP tools 已注入: %s", mcp_count)
    except Exception as _e:
        logger.debug(f"[_build_registry] MCP tools 跳过: {_e}")

    if not full:
        return registry

    # ── 全量插件（仅 UnifiedAgent 使用） ───────────────────────────────
    from app.core.agent.plugins.alerting_plugin import AlertingPlugin
    from app.core.agent.plugins.auto_remediation_plugin import AutoRemediationPlugin
    from app.core.agent.plugins.configuration_plugin import ConfigurationPlugin
    from app.core.agent.plugins.data_process_plugin import DataProcessPlugin
    from app.core.agent.plugins.image_process_plugin import ImageProcessPlugin
    from app.core.agent.plugins.network_plugin import NetworkPlugin
    from app.core.agent.plugins.performance_analysis_plugin import (
        PerformanceAnalysisPlugin,
    )
    from app.core.agent.plugins.system_event_monitoring_plugin import (
        SystemEventMonitoringPlugin,
    )
    from app.core.agent.plugins.trend_analysis_plugin import TrendAnalysisPlugin

    registry.register_plugin(DataProcessPlugin())
    registry.register_plugin(NetworkPlugin())
    registry.register_plugin(ImageProcessPlugin())

    # ── 多模态视觉工具（图表/截图分析）──────────────────────────────────
    try:
        from app.core.agent.plugins.chart_vision_plugin import ChartVisionPlugin

        registry.register_plugin(ChartVisionPlugin())
    except Exception as _e:
        logger.debug(f"[_build_registry] ChartVisionPlugin 跳过: {_e}")
    registry.register_plugin(PerformanceAnalysisPlugin())
    registry.register_plugin(SystemEventMonitoringPlugin())
    registry.register_plugin(AlertingPlugin())
    registry.register_plugin(AutoRemediationPlugin())
    registry.register_plugin(TrendAnalysisPlugin())
    registry.register_plugin(ConfigurationPlugin())

    # ── Word 模板技能工具 ──────────────────────────────────────────────
    try:
        from app.core.agent.plugins.template_fill_plugin import TemplateFillPlugin

        registry.register_plugin(TemplateFillPlugin())
    except Exception as _e:
        logger.debug(f"[_build_registry] TemplateFillPlugin 跳过: {_e}")

    # ── 文档标注技能工具 ───────────────────────────────────────────────
    try:
        from app.core.agent.plugins.annotation_plugin import AnnotationPlugin

        registry.register_plugin(AnnotationPlugin())
    except Exception as _e:
        logger.debug(f"[_build_registry] AnnotationPlugin 跳过: {_e}")

    # ── 文件格式转换工具 ───────────────────────────────────────────────
    try:
        from app.core.agent.plugins.file_converter_plugin import FileConverterPlugin

        registry.register_plugin(FileConverterPlugin())
    except Exception as _e:
        logger.debug(f"[_build_registry] FileConverterPlugin 跳过: {_e}")

    # ── PPT 生成工具（core PPT generation service facade）────────────────
    try:
        from app.core.agent.plugins.ppt_plugin import PPTPlugin

        registry.register_plugin(PPTPlugin())
        logger.debug("[_build_registry] PPTPlugin 已注册")
    except Exception as _e:
        logger.debug(f"[_build_registry] PPTPlugin 跳过: {_e}")

    # ── P0: 沙盒代码执行工具（Python/R/Shell）──────────────────────────
    try:
        from app.core.agent.plugins.sandbox_plugin import SandboxPlugin

        registry.register_plugin(SandboxPlugin())
        logger.debug("[_build_registry] SandboxPlugin 已注册")
    except Exception as _e:
        logger.debug(f"[_build_registry] SandboxPlugin 跳过: {_e}")

    # ── P0: 工作区编辑器桥梁（Agent ↔ 前端编辑器）───────────────────────
    try:
        from app.core.agent.plugins.workspace_editor_plugin import WorkspaceEditorPlugin

        # socketio instance will be injected later via set_workspace_socketio()
        registry.register_plugin(WorkspaceEditorPlugin())
        logger.debug("[_build_registry] WorkspaceEditorPlugin 已注册")
    except Exception as _e:
        logger.debug(f"[_build_registry] WorkspaceEditorPlugin 跳过: {_e}")

    # ── P0: Skills → 原生函数调用（SkillToolAdapter）────────────────────
    # 将所有 Skill 注册为 ToolRegistry 工具，让 LLM 通过原生 function calling
    # 自行决定何时激活哪个技能，取代 SkillAutoMatcher 的猜测式激活。
    try:
        from app.core.skills.skill_tool_adapter import SkillToolAdapter

        SkillToolAdapter.register_all(registry)
    except Exception as _e:
        logger.debug(f"[_build_registry] SkillToolAdapter 跳过: {_e}")

    # ── 用户自定义工具（config/tools/*.py）──────────────────────────────
    try:
        from app.core.tools.user_tool_loader import UserDefinedPlugin, load_user_tools

        load_user_tools()
        plugin = UserDefinedPlugin()
        if plugin.get_tools():
            registry.register_plugin(plugin)
            logger.info(
                f"[_build_registry] UserDefinedPlugin: {len(plugin.get_tools())} 个用户工具"
            )
    except Exception as _e:
        logger.debug(f"[_build_registry] UserDefinedPlugin 跳过: {_e}")

    return registry


def create_agent(
    api_key: Optional[str] = None,
    model_id: str = "deepseek-chat",
    use_langgraph: Optional[bool] = None,
):
    """
    创建 Koto 主 Agent 实例。

    默认优先使用 LangGraphAgent（StateGraph 实现），当 langgraph 不可用或
    ``use_langgraph=False`` 时回退到 UnifiedAgent（while 循环实现）。

    参数:
        api_key       : DeepSeek API Key（默认读取环境变量）
        model_id      : 使用的 DeepSeek 模型
        use_langgraph : True → 强制 LangGraph；False → 强制 UnifiedAgent；
                        None（默认）→ 优先 LangGraph，不可用时自动回退
    """
    from app.core.llm.model_selection import (
        get_configured_cloud_model,
        get_configured_cloud_provider,
    )
    from app.core.llm.provider_factory import get_llm_provider

    usage_api_key = _resolve_api_key(api_key)
    provider_name = get_configured_cloud_provider()
    active_model_id = get_configured_cloud_model(
        task_type="AGENT",
        fallback_model=model_id,
        provider=provider_name,
    )
    if provider_name == "deepseek" and not usage_api_key:
        logger.warning("No API Key provided for Agent. Agent will fail at generation.")

    registry = _build_registry(api_key=usage_api_key, full=True)

    # ── 尝试 LangGraph 路径 ──────────────────────────────────────────────────
    # Both agent implementations resolve generation through provider_factory.
    _want_lg = use_langgraph if use_langgraph is not None else True
    if _want_lg:
        try:
            from app.core.agent.langgraph_agent import _LG_AVAILABLE, LangGraphAgent

            if not _LG_AVAILABLE:
                raise ImportError("langgraph not installed")
            lg_agent = LangGraphAgent(
                registry=registry,
                model_id=active_model_id,
                enable_pii_filter=True,
                enable_output_validation=True,
                restore_pii_in_output=True,
            )
            logger.info("[create_agent] ✅ 使用 LangGraph Agent（StateGraph 路径）")
            return lg_agent
        except Exception as _lg_err:
            if use_langgraph is True:
                # 用户明确要求 LangGraph，不可用则抛出
                raise
            logger.warning(
                "[create_agent] LangGraph 不可用，回退到 UnifiedAgent: %s", _lg_err
            )

    # ── 回退：UnifiedAgent ───────────────────────────────────────────────────
    from app.core.agent.unified_agent import UnifiedAgent

    llm_provider = get_llm_provider(
        provider=provider_name,
        model=active_model_id,
        allow_local_fallback=False,
    )

    # 配置 OutputValidator 的 LLM 质量判断器（复用同一个 provider，避免重复建连接）
    try:
        from app.core.security.output_validator import OutputValidator

        OutputValidator.configure_llm_judge(
            client=llm_provider,
            model_id=get_configured_cloud_model(
                task_type="CHAT",
                fallback_model="deepseek-chat",
                provider=provider_name,
            ),
            timeout=15.0,
        )
    except Exception as _oj_err:
        logger.debug(
            "[create_agent] OutputValidator LLM judge 配置失败（跳过）: %s", _oj_err
        )

    logger.info(
        "[create_agent] ⚙️  使用 UnifiedAgent（provider=%s, model=%s）",
        provider_name,
        active_model_id,
    )
    return UnifiedAgent(
        llm_provider=llm_provider,
        tool_registry=registry,
        model_id=active_model_id,
        use_tool_router=True,
        tool_router_max=20,
    )


def create_local_agent(model: str = None, base_url: str = None) -> "UnifiedAgent":
    """
    创建以本地 Ollama 为 LLM 后端的 UnifiedAgent。

    与 create_agent() 行为完全一致（ReAct + 工具调用 + Skill 注入），
    但底层 LLM 为本地 Ollama 模型，无需 API Key。
    Skills 通过 UnifiedAgent.run() 中的 inject_into_prompt() 自动注入。
    """
    from app.core.agent.unified_agent import UnifiedAgent
    from app.core.llm.ollama_llm_provider import OllamaLLMProvider

    if not model:
        try:
            from app.core.llm.local_model_runtime import get_configured_local_model_tag

            model = get_configured_local_model_tag() or None
        except Exception:
            model = None  # OllamaLLMProvider applies the onboarding fallback.

    llm_kwargs = {}
    if base_url:
        llm_kwargs["base_url"] = base_url
    llm_provider = OllamaLLMProvider(model=model, **llm_kwargs)
    registry = _build_registry(api_key=None, full=True)
    logger.info(f"[create_local_agent] 使用本地模型: {model}")

    return UnifiedAgent(
        llm_provider=llm_provider,
        tool_registry=registry,
        model_id=model,
        use_tool_router=True,
        tool_router_max=15,
    )


def create_langgraph_agent(
    api_key: Optional[str] = None,
    model_id: str = "deepseek-chat",
    enable_pii_filter: bool = True,
    enable_output_validation: bool = True,
) -> "LangGraphAgent":
    """
    创建基于 LangGraph StateGraph 的 ReAct Agent。

    对比 create_agent()（UnifiedAgent）的优势：
      ✅ 状态机替代 while 循环 → 可可视化 / 可调试
      ✅ MemorySaver 检查点 → 多轮对话不丢失上下文
      ✅ 工具节点并行执行
      ✅ 原生 LangGraph streaming
      ✅ 图结构可导出 Mermaid

    当 langgraph 未安装时抛出 ImportError（明确提示安装方式）。
    """
    try:
        from app.core.agent.langgraph_agent import LangGraphAgent
    except ImportError as exc:
        raise ImportError(
            "LangGraph Agent 需要额外依赖：\n"
            "  pip install langgraph langchain-core langchain-google-genai\n"
            f"原始错误: {exc}"
        ) from exc

    _key = _resolve_api_key(api_key)
    registry = _build_registry(api_key=_key, full=False)

    return LangGraphAgent(
        registry=registry,
        model_id=model_id,
        enable_pii_filter=enable_pii_filter,
        enable_output_validation=enable_output_validation,
    )


def create_multi_agent(
    api_key: Optional[str] = None,
    model_id: str = "deepseek-chat",
    max_revisions: int = 1,
) -> "MultiAgentOrchestrator":
    """
    创建多 Agent 协作编排器（Researcher → Writer → Critic 三角协作）。

    支持三种拓扑：
      - sequential  : 顺序管道，每步输出作为下步输入
      - critic_loop : Writer 输出经 Critic 审核，可回退修改（默认最多 max_revisions 轮）
      - parallel    : 并行执行多个 Agent，汇总结果

    使用示例::

        orchestrator = create_multi_agent()
        result = orchestrator.run(
            task="研究并撰写一篇关于量子计算的深度报告",
        )
        print(result["final_output"])

    需要安装：pip install langgraph langchain-core langchain-google-genai
    """
    from app.core.agent.multi_agent import ROLES, MultiAgentOrchestrator

    _key = _resolve_api_key(api_key)
    if _key:
        os.environ.setdefault("DEEPSEEK_API_KEY", _key)

    return MultiAgentOrchestrator(
        roles=[ROLES.RESEARCHER, ROLES.WRITER, ROLES.CRITIC, ROLES.REVISE],
        model_id=model_id,
        max_revisions=max_revisions,
    )
