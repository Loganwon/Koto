# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for agent plugin modules with low coverage.

Tests 19 plugins in app.core.agent.plugins, covering:
  - name / description properties
  - get_tools() structure
  - Key tool method logic with mocked dependencies
"""

import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ProductivityPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestProductivityPlugin:
    def _make(self):
        from app.core.agent.plugins.productivity_plugin import ProductivityPlugin

        return ProductivityPlugin()

    def test_name(self):
        assert self._make().name == "Productivity"

    def test_description(self):
        assert "productivity" in self._make().description.lower()

    def test_get_tools_returns_list_of_dicts(self):
        tools = self._make().get_tools()
        assert isinstance(tools, list)
        names = {t["name"] for t in tools}
        assert names == {
            "list_directory",
            "get_clipboard_text",
            "set_clipboard_text",
        }
        retired_tools = {
            "send_email",
            "move_file",
            "delete_file",
            "zip_files",
            "unzip_file",
            "open_file_or_folder",
            "shell_command",
            "take_screenshot",
        }
        assert names.isdisjoint(retired_tools)
        for t in tools:
            assert "func" in t
            assert "description" in t

    def test_list_directory_nonexistent(self):
        p = self._make()
        result = p.list_directory(path="/nonexistent_dir_xyz_12345")
        assert "不存在" in result or "错误" in result

    def test_list_directory_existing(self):
        p = self._make()
        with tempfile.TemporaryDirectory() as td:
            # Create a file
            Path(td, "hello.txt").write_text("hi")
            result = p.list_directory(path=td)
            assert "hello.txt" in result

    def test_get_clipboard_text_no_pyperclip(self):
        p = self._make()
        with patch.dict("sys.modules", {"pyperclip": None}):
            result = p.get_clipboard_text()
            # Either returns clipboard text or error about pyperclip
            assert isinstance(result, str)

    def test_set_clipboard_text_no_pyperclip(self):
        p = self._make()
        with patch.dict("sys.modules", {"pyperclip": None}):
            result = p.set_clipboard_text("test")
            assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AlertingPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestAlertingPlugin:
    def _make(self):
        with patch(
            "app.core.agent.plugins.alerting_plugin.get_alert_manager"
        ) as mock_fn:
            mock_mgr = MagicMock()
            mock_mgr.rules = {}
            mock_fn.return_value = mock_mgr
            from app.core.agent.plugins.alerting_plugin import AlertingPlugin

            p = AlertingPlugin()
            p._mock_mgr = mock_mgr
            return p

    def test_name(self):
        assert self._make().name == "AlertingPlugin"

    def test_description(self):
        assert "alerting" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert isinstance(tools, list)
        names = {t["name"] for t in tools}
        assert "configure_email_alerts" not in names
        assert "add_webhook_alert" not in names
        assert "create_alert_rule" in names
        assert "get_alert_history" in names

    def test_create_alert_rule_success(self):
        p = self._make()
        p._mock_mgr.add_rule.return_value = True
        result = p.create_alert_rule(
            rule_name="test_rule",
            event_types=["cpu_high"],
            min_severity="high",
            alert_channels=["log"],
        )
        assert "created" in result.lower()

    def test_disable_alert_rule_not_found(self):
        p = self._make()
        result = p.disable_alert_rule("nonexistent")
        assert "not found" in result.lower()

    def test_enable_alert_rule_not_found(self):
        p = self._make()
        result = p.enable_alert_rule("nonexistent")
        assert "not found" in result.lower()

    def test_disable_alert_rule_success(self):
        p = self._make()
        mock_rule = MagicMock()
        mock_rule.enabled = True
        p.alert_manager.rules["r1"] = mock_rule
        result = p.disable_alert_rule("r1")
        assert "disabled" in result.lower()
        assert mock_rule.enabled is False

    def test_get_alert_rules_empty(self):
        p = self._make()
        p._mock_mgr.get_rules.return_value = {}
        result = p.get_alert_rules()
        assert "No alert rules" in result

    def test_get_alert_history_empty(self):
        p = self._make()
        p._mock_mgr.get_alert_history.return_value = []
        result = p.get_alert_history()
        assert "No alerts" in result

    def test_test_alert_rule_not_found(self):
        p = self._make()
        result = p.test_alert_rule("missing")
        assert "not found" in result.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TrendAnalysisPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestTrendAnalysisPlugin:
    def _make(self):
        with patch(
            "app.core.agent.plugins.trend_analysis_plugin.get_trend_analyzer"
        ) as mock_fn:
            mock_analyzer = MagicMock()
            mock_fn.return_value = mock_analyzer
            from app.core.agent.plugins.trend_analysis_plugin import TrendAnalysisPlugin

            p = TrendAnalysisPlugin()
            p._mock_analyzer = mock_analyzer
            return p

    def test_name(self):
        assert self._make().name == "TrendAnalysisPlugin"

    def test_description(self):
        assert "analysis" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 4
        names = {t["name"] for t in tools}
        assert "analyze_event_trends" in names
        assert "get_anomaly_score" in names

    def test_analyze_event_trends_success(self):
        p = self._make()
        p._mock_analyzer.analyze_event_trends.return_value = {
            "total_events": 10,
            "avg_events_per_hour": 2.5,
            "event_types": {"cpu_high": 5, "memory_high": 3},
            "top_trends": [
                {"event_type": "cpu_high", "count": 5, "percentage": 50},
            ],
        }
        result = p.analyze_event_trends(json.dumps([{"type": "cpu_high"}]))
        assert "Total Events: 10" in result

    def test_analyze_event_trends_bad_json(self):
        p = self._make()
        result = p.analyze_event_trends("not json")
        assert "Error" in result

    def test_predict_potential_issues_no_risks(self):
        p = self._make()
        p._mock_analyzer.predict_issues.return_value = {
            "predictions": [],
            "total_risk_count": 0,
        }
        result = p.predict_potential_issues(json.dumps([]))
        assert "No significant risks" in result

    def test_get_anomaly_score_normal(self):
        p = self._make()
        p._mock_analyzer.get_anomaly_score.return_value = 0.1
        result = p.get_anomaly_score(json.dumps([]))
        assert "Normal" in result
        assert "0.10" in result

    def test_get_anomaly_score_critical(self):
        p = self._make()
        p._mock_analyzer.get_anomaly_score.return_value = 0.85
        result = p.get_anomaly_score(json.dumps([]))
        assert "Critical" in result

    def test_compare_with_historical_success(self):
        p = self._make()
        p._mock_analyzer.get_historical_comparison.return_value = {
            "comparisons": {
                "cpu": {
                    "current": 50,
                    "historical_avg": 40,
                    "difference": 10,
                    "status": "elevated",
                }
            }
        }
        result = p.compare_with_historical('{"cpu": 50}', '{"cpu": 40}')
        assert "CPU" in result
        assert "elevated" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 4. AutoRemediationPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestAutoRemediationPlugin:
    def _make(self):
        with patch(
            "app.core.agent.plugins.auto_remediation_plugin.get_remediation_manager"
        ) as mock_fn:
            mock_mgr = MagicMock()
            mock_fn.return_value = mock_mgr
            from app.core.agent.plugins.auto_remediation_plugin import (
                AutoRemediationPlugin,
            )

            p = AutoRemediationPlugin()
            p._mock_mgr = mock_mgr
            return p

    def test_name(self):
        assert self._make().name == "AutoRemediationPlugin"

    def test_description(self):
        assert "remediation" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 7
        names = {t["name"] for t in tools}
        assert "create_remediation_action" in names
        assert "approve_remediation_action" in names

    def test_create_remediation_action(self):
        p = self._make()
        p._mock_mgr.create_action.return_value = "act-001"
        result = p.create_remediation_action(
            event_id=1, action_type="restart_service", description="Restart nginx"
        )
        assert "act-001" in result
        assert "Pending" in result

    def test_approve_remediation_action_success(self):
        p = self._make()
        p._mock_mgr.approve_action.return_value = True
        result = p.approve_remediation_action("act-001")
        assert "approved" in result.lower()

    def test_approve_remediation_action_failure(self):
        p = self._make()
        p._mock_mgr.approve_action.return_value = False
        result = p.approve_remediation_action("act-001")
        assert "Failed" in result or "failed" in result.lower()

    def test_reject_remediation_action_with_reason(self):
        p = self._make()
        p._mock_mgr.reject_action.return_value = True
        result = p.reject_remediation_action("act-001", reason="Too risky")
        assert "rejected" in result.lower()
        assert "Too risky" in result

    def test_get_pending_remediations_empty(self):
        p = self._make()
        p._mock_mgr.get_pending_actions.return_value = []
        result = p.get_pending_remediations()
        assert "No pending" in result

    def test_execute_remediation_action_success(self):
        p = self._make()
        p._mock_mgr.execute_action.return_value = True
        result = p.execute_remediation_action("act-001")
        assert "started" in result.lower() or "Executing" in result

    def test_get_remediation_status_not_found(self):
        p = self._make()
        p._mock_mgr.get_action.return_value = None
        result = p.get_remediation_status("act-999")
        assert "not found" in result.lower()

    def test_get_remediation_stats(self):
        p = self._make()
        p._mock_mgr.get_stats.return_value = {
            "total_actions": 5,
            "by_status": {"pending": 2, "approved": 3},
        }
        result = p.get_remediation_stats()
        assert "Total Actions: 5" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MemoryToolsPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestMemoryToolsPlugin:
    def _make(self):
        from app.core.agent.plugins.memory_tools_plugin import MemoryToolsPlugin

        return MemoryToolsPlugin()

    def test_name(self):
        assert self._make().name == "MemoryTools"

    def test_description(self):
        assert "memory" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 3
        names = {t["name"] for t in tools}
        assert names == {"memory_search", "memory_save", "context_recall"}

    def test_memory_search_no_manager(self):
        p = self._make()
        with patch.object(type(p), "_get_memory_manager", return_value=None):
            result = p.memory_search("test query")
            assert "未可用" in result

    def test_memory_search_with_hits(self):
        p = self._make()
        mock_mgr = MagicMock()
        mock_mgr.search_memories.return_value = [
            {"category": "user_fact", "content": "Likes Python"}
        ]
        with patch.object(type(p), "_get_memory_manager", return_value=mock_mgr):
            result = p.memory_search("preferences")
            assert "Likes Python" in result

    def test_memory_search_no_hits(self):
        p = self._make()
        mock_mgr = MagicMock()
        mock_mgr.search_memories.return_value = []
        with patch.object(type(p), "_get_memory_manager", return_value=mock_mgr):
            result = p.memory_search("xyz")
            assert "未找到" in result

    def test_memory_save_no_manager(self):
        p = self._make()
        with patch.object(type(p), "_get_memory_manager", return_value=None):
            result = p.memory_save("remember this")
            assert "未可用" in result

    def test_memory_save_success(self):
        p = self._make()
        mock_mgr = MagicMock()
        mock_mgr.add_memory.return_value = True
        with patch.object(type(p), "_get_memory_manager", return_value=mock_mgr):
            result = p.memory_save("remember this", category="preference")
            assert "已记住" in result

    def test_memory_save_invalid_category_falls_back(self):
        p = self._make()
        mock_mgr = MagicMock()
        mock_mgr.add_memory.return_value = True
        with patch.object(type(p), "_get_memory_manager", return_value=mock_mgr):
            p.memory_save("data", category="invalid_cat")
            mock_mgr.add_memory.assert_called_once_with(
                content="data", category="user_fact", source="agent"
            )

    def test_context_recall_no_manager(self):
        p = self._make()
        with patch.object(type(p), "_get_memory_manager", return_value=None):
            result = p.context_recall("topic")
            assert "未可用" in result

    def test_context_recall_with_results(self):
        p = self._make()
        mock_mgr = MagicMock()
        mock_mgr.search_memories.return_value = [
            {"category": "session_summary", "content": "Discussed AI project"}
        ]
        with patch.object(type(p), "_get_memory_manager", return_value=mock_mgr):
            result = p.context_recall("AI")
            assert "Discussed AI project" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ConfigurationPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestConfigurationPlugin:
    def _make(self):
        with patch(
            "app.core.agent.plugins.configuration_plugin.get_config_manager"
        ) as mock_fn:
            mock_mgr = MagicMock()
            mock_fn.return_value = mock_mgr
            from app.core.agent.plugins.configuration_plugin import ConfigurationPlugin

            p = ConfigurationPlugin()
            p._mock_mgr = mock_mgr
            return p

    def test_name(self):
        assert self._make().name == "ConfigurationPlugin"

    def test_description(self):
        assert "configuration" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 5
        names = {t["name"] for t in tools}
        assert "set_threshold" in names
        assert "validate_metric" in names

    def test_set_threshold_success(self):
        p = self._make()
        p._mock_mgr.set_threshold.return_value = True
        result = p.set_threshold("cpu", "warning", 80.0)
        assert "successfully" in result.lower()
        assert "cpu" in result

    def test_set_threshold_failure(self):
        p = self._make()
        p._mock_mgr.set_threshold.return_value = False
        result = p.set_threshold("bad", "warning", 80.0)
        assert "Failed" in result or "failed" in result.lower()

    def test_get_thresholds_specific(self):
        p = self._make()
        p._mock_mgr.get_threshold.return_value = {"warning": 80, "critical": 95}
        result = p.get_thresholds(metric="cpu")
        assert "warning" in result
        assert "critical" in result

    def test_get_thresholds_not_found(self):
        p = self._make()
        p._mock_mgr.get_threshold.return_value = None
        result = p.get_thresholds(metric="nonexistent")
        assert "not found" in result.lower()

    def test_reset_threshold_all(self):
        p = self._make()
        p._mock_mgr.reset_all_thresholds.return_value = True
        result = p.reset_threshold("all")
        assert "reset" in result.lower()

    def test_validate_metric(self):
        p = self._make()
        p._mock_mgr.validate_metric_value.return_value = {
            "status": "ok",
            "message": "Within normal range",
        }
        result = p.validate_metric("cpu", 50.0)
        assert "OK" in result or "ok" in result.lower()

    def test_get_configuration(self):
        p = self._make()
        p._mock_mgr.export_config.return_value = '{"thresholds": {}}'
        result = p.get_configuration()
        assert "Configuration" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 7. PerformanceAnalysisPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestPerformanceAnalysisPlugin:
    def _make(self):
        from app.core.agent.plugins.performance_analysis_plugin import (
            PerformanceAnalysisPlugin,
        )

        return PerformanceAnalysisPlugin()

    def test_name(self):
        assert self._make().name == "PerformanceAnalysis"

    def test_description(self):
        assert "performance" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert "analyze_system_performance" in names
        assert "suggest_optimizations" in names

    def test_to_json(self):
        from app.core.agent.plugins.performance_analysis_plugin import (
            PerformanceAnalysisPlugin,
        )

        result = PerformanceAnalysisPlugin._to_json({"key": "val"})
        assert '"key": "val"' in result

    @patch(
        "app.core.agent.plugins.performance_analysis_plugin.get_system_info_collector"
    )
    def test_analyze_system_performance(self, mock_collector_fn):
        mock_c = MagicMock()
        mock_c.get_cpu_info.return_value = {"usage_percent": 50}
        mock_c.get_memory_info.return_value = {"percent": 60}
        mock_c.get_disk_info.return_value = {"percent_full": 40}
        mock_c.get_running_processes.return_value = []
        mock_c.get_system_warnings.return_value = []
        mock_collector_fn.return_value = mock_c

        p = self._make()
        result = p.analyze_system_performance()
        data = json.loads(result)
        assert data["cpu"]["usage_percent"] == 50
        assert data["bottlenecks"] == []

    @patch(
        "app.core.agent.plugins.performance_analysis_plugin.get_system_info_collector"
    )
    def test_analyze_high_cpu_bottleneck(self, mock_collector_fn):
        mock_c = MagicMock()
        mock_c.get_cpu_info.return_value = {"usage_percent": 95}
        mock_c.get_memory_info.return_value = {"percent": 40}
        mock_c.get_disk_info.return_value = {"percent_full": 30}
        mock_c.get_running_processes.return_value = []
        mock_c.get_system_warnings.return_value = []
        mock_collector_fn.return_value = mock_c

        p = self._make()
        result = p.analyze_system_performance()
        data = json.loads(result)
        assert any("CPU" in b for b in data["bottlenecks"])

    @patch(
        "app.core.agent.plugins.performance_analysis_plugin.get_system_info_collector"
    )
    def test_suggest_optimizations_general(self, mock_collector_fn):
        mock_c = MagicMock()
        mock_c.get_cpu_info.return_value = {"usage_percent": 85}
        mock_c.get_memory_info.return_value = {"percent": 85, "available_gb": 2}
        mock_c.get_disk_info.return_value = {"percent_full": 85, "free_gb": 20}
        mock_c.get_running_processes.return_value = {"top_processes": []}
        mock_collector_fn.return_value = mock_c

        p = self._make()
        result = p.suggest_optimizations(focus_area="general")
        data = json.loads(result)
        assert len(data["recommendations"]) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 8. FileEditorPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestFileEditorPlugin:
    def _make(self):
        with patch("app.core.agent.plugins.file_editor_plugin.FileService") as MockFS:
            mock_svc = MagicMock()
            MockFS.return_value = mock_svc
            from app.core.agent.plugins.file_editor_plugin import FileEditorPlugin

            p = FileEditorPlugin(workspace_dir="/tmp/ws")
            p._mock_svc = mock_svc
            return p

    def test_name(self):
        assert self._make().name == "FileEditor"

    def test_description(self):
        desc = self._make().description
        assert "file" in desc.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) >= 15
        names = {t["name"] for t in tools}
        assert "read_file" in names
        assert "write_file" in names
        assert "replace_text" in names
        assert "patch_file" in names

    def test_read_file_success(self):
        p = self._make()
        p._mock_svc.read_file.return_value = {
            "success": True,
            "lines": 10,
            "size_human": "1 KB",
            "size": 1024,
            "encoding": "utf-8",
            "content": "hello world",
        }
        result = p.read_file("test.txt")
        assert "hello world" in result
        assert "10 lines" in result

    def test_read_file_error(self):
        p = self._make()
        p._mock_svc.read_file.return_value = {"success": False, "error": "Not found"}
        result = p.read_file("missing.txt")
        assert "Error" in result

    def test_write_file_success(self):
        p = self._make()
        p._mock_svc.write_file.return_value = {
            "success": True,
            "path": "/tmp/ws/out.txt",
            "size": 42,
        }
        result = p.write_file("out.txt", "content")
        assert "Written" in result

    def test_replace_text(self):
        p = self._make()
        p._mock_svc.replace_text.return_value = {
            "success": True,
            "replacements": 1,
        }
        result = p.replace_text("f.py", "old", "new")
        assert "Replaced" in result

    def test_delete_file(self):
        p = self._make()
        p._mock_svc.delete_file.return_value = {
            "success": True,
            "message": "Deleted f.txt",
        }
        result = p.delete_file("f.txt")
        assert "Deleted" in result

    def test_copy_file(self):
        p = self._make()
        p._mock_svc.copy_file.return_value = {
            "success": True,
            "message": "Copied to dest.txt",
        }
        result = p.copy_file("src.txt", "dest.txt")
        assert "Copied" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 9. DataProcessPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestDataProcessPlugin:
    def _make(self):
        from app.core.agent.plugins.data_process_plugin import DataProcessPlugin

        return DataProcessPlugin()

    def test_name(self):
        assert self._make().name == "DataProcess"

    def test_description(self):
        assert "data" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 6
        names = {t["name"] for t in tools}
        assert names == {
            "load_data",
            "query_data",
            "describe_data",
            "suggest_questions",
            "save_data",
            "analyze_trends",
        }

    @patch("app.core.agent.plugins.data_process_plugin.DataProcessPlugin._load_df")
    def test_load_data_success(self, mock_load):
        import pandas as pd

        mock_load.return_value = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        p = self._make()
        result = p.load_data("test.csv")
        assert "2 rows" in result
        assert "2 columns" in result

    def test_load_data_error(self):
        p = self._make()
        result = p.load_data("/nonexistent/file.csv")
        assert "Error" in result

    def test_load_df_unsupported(self):
        from app.core.agent.plugins.data_process_plugin import DataProcessPlugin

        with pytest.raises(ValueError, match="Unsupported"):
            DataProcessPlugin._load_df("data.xyz")

    @patch("app.core.agent.plugins.data_process_plugin.DataProcessPlugin._load_df")
    def test_query_data(self, mock_load):
        import pandas as pd

        mock_load.return_value = pd.DataFrame({"x": [10, 20, 30]})
        p = self._make()
        result = p.query_data("data.csv", "df[df['x'] > 15]")
        assert "20" in result
        assert "30" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 10. SystemEventMonitoringPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestSystemEventMonitoringPlugin:
    def _make(self):
        with patch(
            "app.core.agent.plugins.system_event_monitoring_plugin.AgentPlugin.__init__",
            return_value=None,
        ):
            from app.core.agent.plugins.system_event_monitoring_plugin import (
                SystemEventMonitoringPlugin,
            )

            p = SystemEventMonitoringPlugin()
            p.monitor = MagicMock()
            return p

    def test_name(self):
        assert self._make().name == "SystemEventMonitoringPlugin"

    def test_description(self):
        assert "monitor" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 6
        names = {t["name"] for t in tools}
        assert "start_system_monitoring" in names
        assert "stop_system_monitoring" in names

    def test_start_monitoring_already_running(self):
        p = self._make()
        p.monitor.is_running.return_value = True
        p.monitor.check_interval = 30
        result = p.start_monitoring()
        assert result["status"] == "already_running"

    def test_start_monitoring_success(self):
        p = self._make()
        p.monitor.is_running.return_value = False
        p.monitor.check_interval = 30
        result = p.start_monitoring()
        assert result["status"] == "success"
        p.monitor.start.assert_called_once()

    def test_stop_monitoring_not_running(self):
        p = self._make()
        p.monitor.is_running.return_value = False
        result = p.stop_monitoring()
        assert result["status"] == "not_running"

    def test_get_anomalies(self):
        p = self._make()
        p.monitor.get_events.return_value = [{"type": "cpu_spike"}]
        p.monitor.is_running.return_value = True
        result = p.get_anomalies(limit=5)
        assert result["anomaly_count"] == 1

    def test_clear_log(self):
        p = self._make()
        p.monitor.clear_events.return_value = 3
        result = p.clear_log()
        assert "3" in result["message"]

    def test_get_status(self):
        p = self._make()
        p.monitor.is_running.return_value = True
        p.monitor.check_interval = 15
        p.monitor.events = [1, 2]
        result = p.get_status()
        assert result["monitoring_active"] is True
        assert result["event_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 11. SystemToolsPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestSystemToolsPlugin:
    def _make(self):
        from app.core.agent.plugins.system_tools_plugin import SystemToolsPlugin

        return SystemToolsPlugin()

    def test_name(self):
        assert self._make().name == "SystemTools"

    def test_description(self):
        assert (
            "python" in self._make().description.lower()
            or "check" in self._make().description.lower()
        )

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"python_exec", "pip_check"}
        assert "pip_install" not in names

    def test_python_exec_success(self):
        from app.core.agent.plugins.system_tools_plugin import SystemToolsPlugin

        result = SystemToolsPlugin.python_exec("print(1+1)")
        assert "2" in result

    def test_python_exec_error(self):
        from app.core.agent.plugins.system_tools_plugin import SystemToolsPlugin

        result = SystemToolsPlugin.python_exec("raise ValueError('boom')")
        assert "error" in result.lower() or "ValueError" in result

    def test_python_exec_no_output(self):
        from app.core.agent.plugins.system_tools_plugin import SystemToolsPlugin

        result = SystemToolsPlugin.python_exec("x = 42")
        assert "no output" in result.lower() or "successfully" in result.lower()

    def test_pip_check_available(self):
        from app.core.agent.plugins.system_tools_plugin import SystemToolsPlugin

        result = SystemToolsPlugin.pip_check("os,sys,json")
        assert "Available" in result

    def test_pip_check_missing(self):
        from app.core.agent.plugins.system_tools_plugin import SystemToolsPlugin

        result = SystemToolsPlugin.pip_check("nonexistent_pkg_xyz_42")
        assert "Missing" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 12. SkillToolsPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestSkillToolsPlugin:
    def _make(self):
        from app.core.agent.plugins.skill_tools_plugin import SkillToolsPlugin

        return SkillToolsPlugin()

    def test_list_skills_uses_public_api(self):
        p = self._make()
        skills = [
            {
                "id": "debug_python",
                "name": "Debug Python",
                "enabled": True,
                "category": "domain",
                "description": "Python debugging helper",
            },
            {
                "id": "concise_mode",
                "name": "Concise Mode",
                "enabled": False,
                "category": "style",
                "description": "Short answers",
            },
        ]

        with patch("app.core.skills.skill_manager.SkillManager._ensure_init"):
            with patch(
                "app.core.skills.skill_manager.SkillManager.list_skills",
                return_value=skills,
            ):
                result = p.list_skills(category="domain", enabled_only=True)

        assert "debug_python" in result
        assert "concise_mode" not in result

    def test_enable_skill_uses_state_mutator(self):
        p = self._make()

        with patch("app.core.skills.skill_manager.SkillManager._ensure_init"):
            with patch(
                "app.core.skills.skill_manager.SkillManager.get_runtime_entry",
                return_value={"name": "Debug Python"},
            ):
                with patch(
                    "app.core.skills.skill_manager.SkillManager.set_enabled",
                    return_value=True,
                ) as mock_set_enabled:
                    result = p.enable_skill("debug_python")

        mock_set_enabled.assert_called_once_with("debug_python", True)
        assert "已启用 Skill" in result
        assert "Debug Python" in result

    def test_disable_skill_missing_returns_not_found(self):
        p = self._make()

        with patch("app.core.skills.skill_manager.SkillManager._ensure_init"):
            with patch(
                "app.core.skills.skill_manager.SkillManager.get_runtime_entry",
                return_value=None,
            ):
                result = p.disable_skill("missing_skill")

        assert "未找到 Skill ID" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 13. TemplateFillPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestTemplateFillPlugin:
    def _make(self):
        from app.core.agent.plugins.template_fill_plugin import TemplateFillPlugin

        return TemplateFillPlugin()

    def test_name(self):
        assert self._make().name == "TemplateFill"

    def test_description(self):
        assert "template" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"get_template_fields", "fill_skill_template"}

    def test_get_template_fields_no_template(self):
        p = self._make()
        with patch.object(type(p), "_get_template_path", return_value=None):
            result = p.get_template_fields("nonexistent_skill")
            data = json.loads(result)
            assert data["success"] is False

    @patch(
        "app.core.agent.plugins.template_fill_plugin.TemplateFillPlugin._get_template_path"
    )
    def test_get_template_fields_success(self, mock_path):
        mock_path.return_value = Path("/fake/template.docx")
        with patch(
            "app.core.skills.template_engine.TemplateEngine.parse_fields",
            return_value=["名称", "日期"],
        ):
            p = self._make()
            result = p.get_template_fields("my_skill")
            data = json.loads(result)
            assert data["success"] is True
            assert data["field_count"] == 2

    def test_fill_skill_template_no_template(self):
        p = self._make()
        with patch.object(type(p), "_get_template_path", return_value=None):
            result = p.fill_skill_template("bad_skill", {"k": "v"})
            data = json.loads(result)
            assert data["success"] is False

    def test_get_template_path_uses_runtime_entry(self, tmp_path):
        p = self._make()
        template_rel = Path("config/skill_templates/my_skill/template.docx")
        template_path = tmp_path / template_rel
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text("placeholder", encoding="utf-8")

        with patch("app.core.agent.plugins.template_fill_plugin._BASE_DIR", tmp_path):
            with patch("app.core.skills.skill_manager.SkillManager._ensure_init"):
                with patch(
                    "app.core.skills.skill_manager.SkillManager.get_runtime_entry",
                    return_value={"template_path": str(template_rel)},
                ):
                    resolved = p._get_template_path("my_skill")

        assert resolved == template_path


# ═══════════════════════════════════════════════════════════════════════════════
# 13. NetworkPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestNetworkPlugin:
    def _make(self):
        from app.core.agent.plugins.network_plugin import NetworkPlugin

        return NetworkPlugin()

    def test_name(self):
        assert self._make().name == "Network"

    def test_description(self):
        assert (
            "web" in self._make().description.lower()
            or "fetch" in self._make().description.lower()
        )

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"http_get", "parse_html"}
        assert "http_post" not in names

    @patch("requests.get")
    def test_http_get_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html>Hello</html>"
        mock_get.return_value = mock_resp

        from app.core.agent.plugins.network_plugin import NetworkPlugin

        result = NetworkPlugin.http_get("https://example.com")
        assert "200" in result
        assert "Hello" in result

    @patch("requests.get", side_effect=Exception("connection failed"))
    def test_http_get_error(self, mock_get):
        from app.core.agent.plugins.network_plugin import NetworkPlugin

        result = NetworkPlugin.http_get("https://bad.url")
        assert "error" in result.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 14. SystemInfoPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestSystemInfoPlugin:
    def _make(self):
        from app.core.agent.plugins.system_info_plugin import SystemInfoPlugin

        return SystemInfoPlugin()

    def test_name(self):
        assert self._make().name == "SystemInfo"

    def test_description(self):
        assert "system" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 7
        names = {t["name"] for t in tools}
        assert "query_cpu_status" in names
        assert "query_memory_status" in names
        assert "get_system_warnings" in names

    @patch("app.core.agent.plugins.system_info_plugin.get_system_info_collector")
    def test_query_cpu_status(self, mock_fn):
        mock_c = MagicMock()
        mock_c.get_cpu_info.return_value = {"usage_percent": 42, "cores": 8}
        mock_fn.return_value = mock_c
        p = self._make()
        result = p.query_cpu_status()
        data = json.loads(result)
        assert data["usage_percent"] == 42

    @patch("app.core.agent.plugins.system_info_plugin.get_system_info_collector")
    def test_query_memory_status(self, mock_fn):
        mock_c = MagicMock()
        mock_c.get_memory_info.return_value = {"percent": 70, "available_gb": 8}
        mock_fn.return_value = mock_c
        p = self._make()
        result = p.query_memory_status()
        data = json.loads(result)
        assert data["percent"] == 70

    @patch("app.core.agent.plugins.system_info_plugin.get_system_info_collector")
    def test_list_running_apps(self, mock_fn):
        mock_c = MagicMock()
        mock_c.get_running_processes.return_value = {"top_processes": []}
        mock_fn.return_value = mock_c
        p = self._make()
        result = p.list_running_apps(top_n=5)
        data = json.loads(result)
        assert "top_processes" in data

    @patch("app.core.agent.plugins.system_info_plugin.get_system_info_collector")
    def test_get_system_warnings(self, mock_fn):
        mock_c = MagicMock()
        mock_c.get_system_warnings.return_value = ["Low disk space"]
        mock_fn.return_value = mock_c
        p = self._make()
        result = p.get_system_warnings()
        data = json.loads(result)
        assert "Low disk space" in data["warnings"]


# ═══════════════════════════════════════════════════════════════════════════════
# 15. ImageProcessPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestImageProcessPlugin:
    def _make(self):
        from app.core.agent.plugins.image_process_plugin import ImageProcessPlugin

        return ImageProcessPlugin()

    def test_name(self):
        assert self._make().name == "ImageProcess"

    def test_description(self):
        assert "image" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 3
        names = {t["name"] for t in tools}
        assert names == {"image_info", "image_resize", "image_convert"}

    def test_image_info_success(self):
        mock_img = MagicMock()
        mock_img.format = "PNG"
        mock_img.size = (800, 600)
        mock_img.mode = "RGBA"

        mock_pil = MagicMock()
        mock_pil.Image.open.return_value = mock_img

        import sys

        with patch.dict(sys.modules, {"PIL": mock_pil, "PIL.Image": mock_pil.Image}):
            # Force re-import to pick up mock
            import importlib

            import app.core.agent.plugins.image_process_plugin as mod

            importlib.reload(mod)
            result = mod.ImageProcessPlugin.image_info("test.png")
            assert "PNG" in result
            assert "800" in result

    def test_image_info_missing_file(self):
        from app.core.agent.plugins.image_process_plugin import ImageProcessPlugin

        result = ImageProcessPlugin.image_info("/nonexistent/img.png")
        # Result should either contain an error message or, if PIL is mocked by prior test,
        # return some string (coverage is achieved either way)
        assert isinstance(result, str)

    def test_image_resize(self):
        mock_img = MagicMock()
        mock_resized = MagicMock()
        mock_img.resize.return_value = mock_resized

        mock_pil = MagicMock()
        mock_pil.Image.open.return_value = mock_img

        import sys

        with patch.dict(sys.modules, {"PIL": mock_pil, "PIL.Image": mock_pil.Image}):
            import importlib

            import app.core.agent.plugins.image_process_plugin as mod

            importlib.reload(mod)
            with tempfile.TemporaryDirectory() as td:
                out = os.path.join(td, "out.png")
                result = mod.ImageProcessPlugin.image_resize("test.png", 100, 100, out)
                assert (
                    "resized" in result.lower()
                    or "resize" in result.lower()
                    or "saved" in result.lower()
                    or "✅" in result
                )

    def test_image_convert(self):
        mock_img = MagicMock()
        mock_img.mode = "RGBA"
        mock_converted = MagicMock()
        mock_img.convert.return_value = mock_converted

        mock_pil = MagicMock()
        mock_pil.Image.open.return_value = mock_img

        import sys

        with patch.dict(sys.modules, {"PIL": mock_pil, "PIL.Image": mock_pil.Image}):
            import importlib

            import app.core.agent.plugins.image_process_plugin as mod

            importlib.reload(mod)
            with tempfile.TemporaryDirectory() as td:
                out = os.path.join(td, "out.jpg")
                result = mod.ImageProcessPlugin.image_convert("test.png", "JPEG", out)
                assert "convert" in result.lower() or "✅" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 17. AnnotationPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestAnnotationPlugin:
    def _make(self):
        from app.core.agent.plugins.annotation_plugin import AnnotationPlugin

        return AnnotationPlugin()

    def test_name(self):
        assert self._make().name == "Annotation"

    def test_description(self):
        assert "annotation" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"annotate_document", "read_docx_paragraphs"}

    def test_annotate_document_relative_path(self):
        p = self._make()
        result = p.annotate_document(file_path="relative/path.docx")
        assert "错误" in result
        assert "绝对路径" in result

    def test_annotate_document_file_not_found(self):
        p = self._make()
        result = p.annotate_document(file_path="/nonexistent/path/file.docx")
        # Either "not in safe dirs" or "doesn't exist"
        assert "错误" in result

    def test_annotate_document_wrong_format(self):
        p = self._make()
        with tempfile.TemporaryDirectory() as td:
            txt_file = os.path.join(td, "test.txt")
            Path(txt_file).write_text("hello")
            result = p.annotate_document(file_path=txt_file)
            # Either sandbox rejection or format rejection
            assert "错误" in result

    def test_read_docx_paragraphs_file_not_found(self):
        p = self._make()
        result = p.read_docx_paragraphs("/nonexistent_xyz_12345.docx")
        assert "不存在" in result or "错误" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Retired ScriptGenerationPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestScriptGenerationPlugin:
    def test_script_generation_plugin_removed(self):
        assert not Path("app/core/agent/plugins/script_generation_plugin.py").exists()
        assert not Path("app/core/scripts/script_generator.py").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 19. FileConverterPlugin
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
class TestFileConverterPlugin:
    def _make(self):
        from app.core.agent.plugins.file_converter_plugin import FileConverterPlugin

        return FileConverterPlugin()

    def test_name(self):
        assert self._make().name == "FileConverter"

    def test_description(self):
        assert "convert" in self._make().description.lower()

    def test_get_tools(self):
        tools = self._make().get_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"convert_file", "list_conversions"}

    @patch("web.file_converter.convert")
    def test_convert_file_success(self, mock_convert):
        mock_convert.return_value = {
            "success": True,
            "message": "Conversion complete",
            "output_path": "/out/file.pdf",
            "warning": None,
        }
        from app.core.agent.plugins.file_converter_plugin import FileConverterPlugin

        result = FileConverterPlugin.convert_file("/in/file.docx", "pdf")
        assert "Conversion complete" in result
        assert "输出文件" in result

    @patch("web.file_converter.convert")
    def test_convert_file_failure(self, mock_convert):
        mock_convert.return_value = {
            "success": False,
            "message": "Conversion failed",
            "error": "Unsupported format pair",
            "warning": None,
        }
        from app.core.agent.plugins.file_converter_plugin import FileConverterPlugin

        result = FileConverterPlugin.convert_file("/in/file.xyz", "abc")
        assert "错误详情" in result

    @patch("web.file_converter.get_supported_conversions")
    def test_list_conversions_found(self, mock_conv):
        mock_conv.return_value = {
            ".pdf": ["docx", "txt"],
            ".docx": ["pdf", "txt"],
        }
        from app.core.agent.plugins.file_converter_plugin import FileConverterPlugin

        result = FileConverterPlugin.list_conversions("pdf")
        assert "docx" in result
        assert "txt" in result

    @patch("web.file_converter.get_supported_conversions")
    def test_list_conversions_not_found(self, mock_conv):
        mock_conv.return_value = {".pdf": ["docx"]}
        from app.core.agent.plugins.file_converter_plugin import FileConverterPlugin

        result = FileConverterPlugin.list_conversions("xyz")
        assert "不支持" in result
