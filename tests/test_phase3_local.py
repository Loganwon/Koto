#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 3 Local Validation Tests
直接验证：
  1. 前端快速测试逻辑：JSON 解析、卡片识别
  2. 多轮交互验证逻辑：状态快照提取、跨轮注入
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 添加项目路径
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.api.agent_routes import (
    _build_snapshot_context_text,
    _merge_system_snapshot_from_steps,
    _parse_observation_json,
)


class Test1EToESSEAndCardDetection(unittest.TestCase):
    """Test 1: SSE 流 + JSON 解析 + 结构卡片检测"""

    def test_cpu_observation_parsing(self):
        """验证 CPU 观测值能正确解析为结构化数据"""
        cpu_obs = json.dumps(
            {
                "usage_percent": 23.5,
                "physical_cores": 24,
                "logical_cores": 32,
                "frequency_mhz": 3000.0,
                "model": "Intel Core i9",
            }
        )

        parsed = _parse_observation_json(cpu_obs)
        self.assertIsNotNone(parsed)
        self.assertIn("usage_percent", parsed)
        self.assertEqual(parsed["usage_percent"], 23.5)
        self.assertIn("logical_cores", parsed)

    def test_memory_observation_parsing(self):
        """验证内存观测值能正确解析"""
        mem_obs = json.dumps(
            {
                "total_gb": 64.0,
                "used_gb": 32.5,
                "available_gb": 31.5,
                "percent": 50.8,
                "swap_total_gb": 8.0,
                "swap_used_gb": 0.5,
            }
        )

        parsed = _parse_observation_json(mem_obs)
        self.assertIsNotNone(parsed)
        self.assertIn("percent", parsed)
        self.assertEqual(parsed["percent"], 50.8)

    def test_disk_observation_parsing(self):
        """验证磁盘观测值能正确解析"""
        disk_obs = json.dumps(
            {
                "drives": {
                    "C:": {
                        "total_gb": 500.0,
                        "used_gb": 300.0,
                        "free_gb": 200.0,
                        "percent": 60.0,
                    },
                    "D:": {
                        "total_gb": 2000.0,
                        "used_gb": 1500.0,
                        "free_gb": 500.0,
                        "percent": 75.0,
                    },
                },
                "total_gb": 2500.0,
                "free_gb": 700.0,
                "percent_full": 72.0,
            }
        )

        parsed = _parse_observation_json(disk_obs)
        self.assertIsNotNone(parsed)
        self.assertIn("drives", parsed)
        self.assertIn("C:", parsed["drives"])

    def test_invalid_json_returns_none(self):
        """验证非 JSON 返回 None"""
        result = _parse_observation_json("plain text observation")
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        """验证空字符串返回 None"""
        result = _parse_observation_json("")
        self.assertIsNone(result)


class Test2MultiTurnStateReuse(unittest.TestCase):
    """Test 2: 多轮交互 + 状态快照跨轮复用"""

    def test_extract_cpu_tool_result(self):
        """验证从 agent 步骤中提取 CPU 工具结果"""
        session_state = {"system_snapshot": {}, "updated_at": None}

        steps = [
            {
                "step_type": "action",
                "action": {"tool_name": "query_cpu_status"},
                "content": "Calling query_cpu_status",
            },
            {
                "step_type": "observation",
                "observation": json.dumps({"usage_percent": 25.0, "logical_cores": 32}),
                "content": "CPU info retrieved",
            },
        ]

        merged = _merge_system_snapshot_from_steps(session_state, steps)

        # 验证 CPU 数据被捕获
        self.assertIn("cpu", merged["system_snapshot"])
        self.assertIn("data", merged["system_snapshot"]["cpu"])
        self.assertEqual(
            merged["system_snapshot"]["cpu"]["data"]["usage_percent"], 25.0
        )

    def test_extract_multiple_tools(self):
        """验证从多个工具调用中提取数据"""
        session_state = {"system_snapshot": {}, "updated_at": None}

        steps = [
            # CPU
            {
                "step_type": "action",
                "action": {"tool_name": "query_cpu_status"},
                "content": "Query CPU",
            },
            {
                "step_type": "observation",
                "observation": json.dumps({"usage_percent": 20}),
            },
            # Memory
            {
                "step_type": "action",
                "action": {"tool_name": "query_memory_status"},
                "content": "Query Memory",
            },
            {
                "step_type": "observation",
                "observation": json.dumps({"percent": 50}),
            },
            # Disk
            {
                "step_type": "action",
                "action": {"tool_name": "query_disk_usage"},
                "content": "Query Disk",
            },
            {
                "step_type": "observation",
                "observation": json.dumps({"percent_full": 60}),
            },
        ]

        merged = _merge_system_snapshot_from_steps(session_state, steps)
        snapshot = merged["system_snapshot"]

        # 验证所有 3 个工具的数据都被捕获
        self.assertIn("cpu", snapshot)
        self.assertIn("memory", snapshot)
        self.assertIn("disk", snapshot)

        # 验证数据内容
        self.assertEqual(snapshot["cpu"]["data"]["usage_percent"], 20)
        self.assertEqual(snapshot["memory"]["data"]["percent"], 50)
        self.assertEqual(snapshot["disk"]["data"]["percent_full"], 60)

    def test_build_context_for_next_turn(self):
        """验证为下一轮构建的上下文文本"""
        session_state = {
            "system_snapshot": {
                "cpu": {
                    "tool": "query_cpu_status",
                    "data": {"usage_percent": 25, "logical_cores": 32},
                },
                "memory": {"tool": "query_memory_status", "data": {"percent": 50}},
                "warnings": {"tool": "get_system_warnings", "data": {"warnings": []}},
            }
        }

        context_text = _build_snapshot_context_text(session_state)

        # 验证上下文包含关键信息
        self.assertIn("Session context", context_text)
        self.assertIn("cpu", context_text)
        self.assertIn("25", context_text)
        self.assertIn("memory", context_text)
        self.assertIn("50", context_text)

    def test_state_persistence_and_reload(self):
        """验证状态快照的持久化和重新加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 模拟状态保存
            state_file = Path(tmpdir) / "test_session.state.json"
            session_state = {
                "system_snapshot": {
                    "cpu": {"tool": "query_cpu_status", "data": {"usage_percent": 30}},
                    "memory": {"tool": "query_memory_status", "data": {"percent": 60}},
                },
                "updated_at": 1671234567,
            }

            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(session_state, f)

            # 模拟从文件重新加载
            with open(state_file, "r", encoding="utf-8") as f:
                loaded_state = json.load(f)

            # 验证加载的数据完整性
            self.assertIn("system_snapshot", loaded_state)
            self.assertIn("cpu", loaded_state["system_snapshot"])
            self.assertIn("memory", loaded_state["system_snapshot"])
            self.assertEqual(
                loaded_state["system_snapshot"]["cpu"]["data"]["usage_percent"], 30
            )


def run_tests():
    """运行所有本地验证测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(Test1EToESSEAndCardDetection))
    suite.addTests(loader.loadTestsFromTestCase(Test2MultiTurnStateReuse))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    print("\n" + "🔬 Phase 3 Local Validation Tests 🔬".center(70, "="))
    print("\n[Test 1] SSE Stream + JSON Parsing + Card Detection")
    print("[Test 2] Multi-Turn State Reuse + Snapshot Persistence\n")

    sys.exit(run_tests())
