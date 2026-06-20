# -*- coding: utf-8 -*-
"""
优化验证测试

覆盖2项改进：
1. ToolRouter 双层语义匹配
2. ToolRegistry 工具执行超时
"""

import sys
import time

import pytest

sys.path.insert(0, ".")


# ─────────────────────────────────────────────────────────────────────────────
# 1. ToolRouter
# ─────────────────────────────────────────────────────────────────────────────


class TestToolRouter:
    @pytest.fixture
    def router_and_tools(self):
        from app.core.routing.tool_router import ToolRouter

        router = ToolRouter(max_tools=20, semantic_topk=8)
        tools = [
            {
                "name": "analyze_excel_data",
                "description": "分析Excel数据，计算统计指标",
            },
            {"name": "web_search", "description": "Search the web 联网搜索"},
            {"name": "run_python_code", "description": "运行Python代码脚本"},
            {"name": "read_file", "description": "读取文件内容"},
            {"name": "write_file", "description": "写入文件内容"},
            {"name": "get_current_time", "description": "获取当前时间"},
            {"name": "get_clipboard_text", "description": "读取剪贴板文本"},
            {"name": "query_cpu_status", "description": "查询CPU状态"},
        ]
        return router, tools

    def test_token_builder_chinese(self):
        from app.core.routing.tool_router import _build_tokens

        toks = _build_tokens("分析这个CSV里的趋势")
        assert "分" in toks
        assert "析" in toks
        assert "分析" in toks  # bigram of 2-char Chinese word

    def test_token_builder_english(self):
        from app.core.routing.tool_router import _build_tokens

        toks = _build_tokens("analyze_excel_data")
        assert "analyze" in toks
        assert "excel" in toks
        assert "data" in toks

    def test_overlap_score_basic(self):
        from app.core.routing.tool_router import _build_tokens, _overlap_score

        q = _build_tokens("分析Excel数据")
        d1 = _build_tokens("分析Excel数据，计算统计指标 analyze excel data")
        d2 = _build_tokens("运行Python脚本 run python code")
        assert _overlap_score(q, d1) > _overlap_score(q, d2)

    def test_keyword_tier_web_search(self, router_and_tools):
        router, tools = router_and_tools
        selected = router.select(tools, "帮我搜索最新新闻")
        names = [t["name"] for t in selected]
        assert "web_search" in names

    def test_semantic_tier_csv_analysis(self, router_and_tools):
        """CSV分析查询无法命中关键词规则，应由语义层捞起 analyze_excel_data。"""
        router, tools = router_and_tools
        selected = router.select(tools, "分析这个CSV里的趋势")
        names = [t["name"] for t in selected]
        assert (
            "analyze_excel_data" in names
        ), f"Semantic tier should select analyze_excel_data. Got: {names}"

    def test_description_index_cached(self, router_and_tools):
        router, tools = router_and_tools
        router.select(tools, "first query")
        key_before = router._index_cache_key
        router.select(tools, "second query")
        assert (
            router._index_cache_key == key_before
        ), "Index should be reused when tool set unchanged"

    def test_index_rebuilds_on_tool_change(self, router_and_tools):
        router, tools = router_and_tools
        router.select(tools, "query")
        key_before = router._index_cache_key
        new_tools = tools + [{"name": "new_tool", "description": "新工具"}]
        router.select(new_tools, "query")
        assert (
            router._index_cache_key != key_before
        ), "Index should rebuild when tool set changes"

    def test_force_all_returns_capped(self, router_and_tools):
        router, tools = router_and_tools
        result = router.select(tools, "anything", force_all=True)
        assert len(result) == len(tools)  # 8 tools < 20 max


# ─────────────────────────────────────────────────────────────────────────────
# 2. ToolRegistry Timeout
# ─────────────────────────────────────────────────────────────────────────────


class TestToolRegistryTimeout:
    def test_timeout_constant_exists(self):
        from app.core.agent.tool_registry import _TOOL_TIMEOUT

        assert _TOOL_TIMEOUT == 60

    def test_fast_tool_executes_normally(self):
        from app.core.agent.tool_registry import ToolRegistry

        reg = ToolRegistry()
        reg.register_tool(
            "double",
            lambda x: x * 2,
            "double a number",
            {
                "type": "OBJECT",
                "properties": {"x": {"type": "INTEGER"}},
                "required": ["x"],
            },
        )
        result = reg.execute("double", {"x": 21})
        assert result == 42

    def test_timeout_raises_runtime_error(self, monkeypatch):
        import app.core.agent.tool_registry as tool_registry
        from app.core.agent.tool_registry import ToolRegistry

        monkeypatch.setattr(tool_registry, "_TOOL_TIMEOUT", 0.2)
        reg = ToolRegistry()

        def hang():
            time.sleep(2)

        reg.register_tool(
            "hang", hang, "hangs forever", {"type": "OBJECT", "properties": {}}
        )
        t0 = time.time()
        with pytest.raises(RuntimeError, match="timed out"):
            reg.execute("hang", {})
        elapsed = time.time() - t0
        assert elapsed < 1.0, f"Should timeout quickly, took {elapsed:.1f}s"

    def test_missing_tool_raises_value_error(self):
        from app.core.agent.tool_registry import ToolRegistry

        reg = ToolRegistry()
        with pytest.raises(ValueError, match="not found"):
            reg.execute("nonexistent_tool", {})
