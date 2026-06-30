# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Tests for DocAgent document processing
========================================================

Tests cover:
- DocTask and FileHandle data classes
- DocAgent plan creation
- Step execution with tool calls
- File change tracking
- Task verification
- WebSocket event emission
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import test subjects
from app.core.agent.doc_agent import (
    DocAgent,
    DocEvent,
    DocEventType,
    DocTask,
    FileChange,
    FileHandle,
    create_doc_agent,
)
from app.core.agent.doc_event_emitter import (
    DocEventEmitter,
    create_emitter,
)
from app.core.file.multi_file_coordinator import (
    CompareResult,
    FileSnapshot,
    MultiFileCoordinator,
    get_file_coordinator,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_file_handle():
    """Create a sample FileHandle for testing."""
    return FileHandle(
        path="/workspace/test.docx",
        file_type="docx",
        content_snapshot="This is test content.",
        selection="test",
    )


@pytest.fixture
def sample_doc_task(sample_file_handle):
    """Create a sample DocTask for testing."""
    return DocTask(
        id="test-task-123",
        prompt="请总结这个文档的要点",
        files=[sample_file_handle],
        permissions={"read", "write"},
        session_id="test-session",
    )


@pytest.fixture
def mock_socketio():
    """Create a mock SocketIO instance."""
    socketio = MagicMock()
    socketio.emit = MagicMock()
    return socketio


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some test files
        test_doc = Path(tmpdir) / "test.txt"
        test_doc.write_text(
            "This is a test document.\nLine 2.\nLine 3.", encoding="utf-8"
        )

        test_xlsx = Path(tmpdir) / "data.xlsx"
        # Create a minimal xlsx file would require openpyxl
        # For now, we'll skip xlsx creation in basic tests

        yield tmpdir


# ============================================================================
# DocTask and FileHandle Tests
# ============================================================================


class TestFileHandle:
    """Tests for FileHandle data class."""

    def test_file_handle_creation(self):
        """Test basic FileHandle creation."""
        fh = FileHandle(path="/path/to/file.docx")
        assert fh.path == "/path/to/file.docx"
        assert fh.file_type == "docx"  # Auto-detected from extension

    def test_file_handle_auto_type_detection(self):
        """Test automatic file type detection."""
        assert FileHandle(path="test.xlsx").file_type == "xlsx"
        assert FileHandle(path="test.pdf").file_type == "pdf"
        assert FileHandle(path="test.pptx").file_type == "pptx"
        assert FileHandle(path="test.txt").file_type == "txt"

    def test_file_handle_to_dict(self):
        """Test FileHandle serialization."""
        fh = FileHandle(
            path="/path/to/file.docx",
            content_snapshot="test content",
            selection="selected text",
        )
        d = fh.to_dict()
        assert d["path"] == "/path/to/file.docx"
        assert d["file_type"] == "docx"
        assert d["content_snapshot"] == "test content"
        assert d["selection"] == "selected text"


class TestDocTask:
    """Tests for DocTask data class."""

    def test_doc_task_creation(self):
        """Test DocTask creation with auto-generated ID."""
        task = DocTask(
            id="",  # Empty, should auto-generate
            prompt="Test prompt",
        )
        assert task.id  # Should have auto-generated ID
        assert len(task.id) == 8

    def test_doc_task_with_files(self, sample_file_handle):
        """Test DocTask with file handles."""
        task = DocTask(
            id="test",
            prompt="Process these files",
            files=[sample_file_handle],
        )
        assert len(task.files) == 1
        assert task.files[0].path == "/workspace/test.docx"

    def test_doc_task_to_dict(self, sample_doc_task):
        """Test DocTask serialization."""
        d = sample_doc_task.to_dict()
        assert d["id"] == "test-task-123"
        assert d["prompt"] == "请总结这个文档的要点"
        assert len(d["files"]) == 1
        assert "read" in d["permissions"]


class TestFileChange:
    """Tests for FileChange data class."""

    def test_file_change_creation(self):
        """Test FileChange creation."""
        change = FileChange(
            file_path="/path/to/file.txt",
            change_type="modify",
            range_start=10,
            range_end=50,
            original="old text",
            modified="new text",
        )
        assert change.file_path == "/path/to/file.txt"
        assert change.change_type == "modify"
        assert change.timestamp > 0

    def test_file_change_to_dict(self):
        """Test FileChange serialization with truncation."""
        long_text = "x" * 1000
        change = FileChange(
            file_path="/path/to/file.txt",
            change_type="add",
            range_start=0,
            range_end=0,
            original="",
            modified=long_text,
        )
        d = change.to_dict()
        assert len(d["modified"]) == 500  # Truncated


# ============================================================================
# DocEvent Tests
# ============================================================================


class TestDocEvent:
    """Tests for DocEvent data class."""

    def test_event_creation(self):
        """Test DocEvent creation."""
        event = DocEvent(
            event_type=DocEventType.PLAN_CREATED,
            task_id="test-123",
            data={"steps": []},
        )
        assert event.event_type == DocEventType.PLAN_CREATED
        assert event.task_id == "test-123"

    def test_event_to_dict(self):
        """Test DocEvent serialization."""
        event = DocEvent(
            event_type=DocEventType.STEP_START,
            task_id="test",
            step_id="step-1",
            data={"name": "extract", "description": "Extracting data"},
        )
        d = event.to_dict()
        assert d["type"] == "step_start"
        assert d["step_id"] == "step-1"
        assert d["data"]["name"] == "extract"


# ============================================================================
# DocAgent Tests
# ============================================================================


class TestDocAgent:
    """Tests for DocAgent."""

    def test_agent_creation(self):
        """Test DocAgent creation."""
        agent = create_doc_agent()
        assert agent is not None
        assert isinstance(agent, DocAgent)

    def test_agent_cancellation(self):
        """Test agent cancellation flag."""
        agent = DocAgent()
        assert agent._cancelled is False
        agent.cancel()
        assert agent._cancelled is True

    @patch("app.core.llm.ollama_llm_provider.OllamaLLMProvider")
    def test_get_provider_uses_ollama_for_local_mode(self, mock_ollama_provider):
        """Local DocAgent requests should initialize Ollama instead of Gemini."""
        agent = DocAgent(model_id="")

        provider = agent._get_provider({"model_mode": "local"})

        mock_ollama_provider.assert_called_once_with(model=None)
        assert provider is mock_ollama_provider.return_value
        assert agent._provider_mode == "local"

    @patch("app.core.llm.gemini.GeminiProvider")
    def test_get_provider_cloud_uses_gemini_provider_env_loading(
        self, mock_gemini_provider
    ):
        """Cloud DocAgent requests should reuse GeminiProvider config-file loading."""
        provider_instance = MagicMock()
        provider_instance.api_key = "AIzaSyCZ_test"
        mock_gemini_provider.return_value = provider_instance
        agent = DocAgent(model_id="gemini-2.5-flash")

        provider = agent._get_provider({"model_mode": "cloud"})

        mock_gemini_provider.assert_called_once_with(api_key=None)
        assert provider is provider_instance
        assert agent._provider_mode == "cloud"

    def test_call_llm_local_bypasses_cloud_fallback(self):
        """Local DocAgent execution should not inject Gemini fallback model IDs."""
        agent = DocAgent(model_id="")
        agent._provider_mode = "local"
        provider = MagicMock()
        provider.generate_content.return_value = {"content": "OK", "tool_calls": []}

        with patch(
            "app.core.llm.model_fallback.get_fallback_executor"
        ) as mock_get_fallback:
            result = agent._call_llm(
                provider=provider,
                messages=[{"role": "user", "content": "请只回复 OK"}],
                system="sys",
                tool_defs=[],
            )

        mock_get_fallback.assert_not_called()
        provider.generate_content.assert_called_once()
        assert provider.generate_content.call_args.kwargs["model"] is None
        assert result["content"] == "OK"

    def test_verify_completion_local_uses_local_model(self, sample_doc_task):
        """Local verification should reuse the local provider without forcing a Gemini model id."""
        agent = DocAgent(model_id="")
        agent._provider_mode = "local"
        provider = MagicMock()
        provider.generate_content.return_value = {
            "content": '{"status": "completed", "summary": "OK"}'
        }

        result = agent._verify_completion(sample_doc_task, provider)

        provider.generate_content.assert_called_once()
        assert provider.generate_content.call_args.kwargs["model"] is None
        assert result["status"] == "completed"

    @patch("app.core.agent.doc_agent.DocAgent._get_provider")
    def test_agent_run_without_provider(self, mock_get_provider, sample_doc_task):
        """Test agent run fails gracefully without LLM provider."""
        mock_get_provider.return_value = None

        agent = DocAgent()
        events = list(agent.run(sample_doc_task))

        # Should emit error event
        error_events = [e for e in events if e.event_type == DocEventType.ERROR]
        assert len(error_events) >= 1

    @patch("app.core.agent.doc_agent.DocAgent._get_provider")
    @patch("app.core.agent.doc_agent.DocAgent._build_registry")
    def test_agent_plan_creation(self, mock_registry, mock_provider, sample_doc_task):
        """Test that agent creates a plan."""
        # Mock provider
        provider = MagicMock()
        provider.generate_content.return_value = {
            "content": json.dumps(
                [{"name": "step1", "description": "First step", "step_type": "llm"}]
            )
        }
        mock_provider.return_value = provider

        # Mock registry
        registry = MagicMock()
        registry.get_definitions.return_value = []
        mock_registry.return_value = registry

        agent = DocAgent()
        events = list(agent.run(sample_doc_task))

        # Should have plan_created event
        plan_events = [e for e in events if e.event_type == DocEventType.PLAN_CREATED]
        assert len(plan_events) >= 1

    def test_build_file_context(self, sample_file_handle):
        """Test file context building."""
        agent = DocAgent()
        context = agent._build_file_context([sample_file_handle])

        assert "test.docx" in context
        assert "docx" in context
        assert "test" in context  # selection

    def test_build_history_context(self):
        """Test history context building."""
        agent = DocAgent()
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "model", "content": "Hi there!"},
            {"role": "function", "content": "tool result"},  # Should be filtered
        ]
        context = agent._build_history_context(history)

        assert "[user] Hello" in context
        assert "[model] Hi" in context
        assert "tool result" not in context


# ============================================================================
# DocEventEmitter Tests
# ============================================================================


class TestDocEventEmitter:
    """Tests for DocEventEmitter."""

    def test_emitter_creation(self, mock_socketio):
        """Test emitter creation."""
        emitter = create_emitter(mock_socketio, "test-sid")
        assert emitter is not None

    def test_emitter_set_task_id(self, mock_socketio):
        """Test setting task ID."""
        emitter = DocEventEmitter(mock_socketio, "test-sid")
        emitter.set_task_id("task-123")
        assert emitter._task_id == "task-123"

    def test_emitter_emit_plan(self, mock_socketio):
        """Test emitting plan event."""
        emitter = DocEventEmitter(mock_socketio, "test-sid")
        emitter.set_task_id("task-123")

        # Create mock plan
        mock_plan = MagicMock()
        mock_plan.task_id = "task-123"
        mock_plan.original_request = "Test request"
        mock_step = MagicMock()
        mock_step.step_id = "step-1"
        mock_step.name = "test_step"
        mock_step.description = "Test step"
        mock_step.step_type = "llm"
        mock_step.require_approval = False
        mock_step.timeout_seconds = 60
        mock_plan.steps = [mock_step]

        emitter.emit_plan(mock_plan)

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "doc_plan_created"

    def test_emitter_emit_step_progress(self, mock_socketio):
        """Test emitting step progress."""
        emitter = DocEventEmitter(mock_socketio, "test-sid")
        emitter.set_task_id("task-123")
        emitter.emit_step_progress("step-1", 50, "Half done")

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "doc_step_progress"
        assert call_args[0][1]["progress"] == 50

    def test_emitter_emit_file_change(self, mock_socketio):
        """Test emitting file change event."""
        emitter = DocEventEmitter(mock_socketio, "test-sid")
        emitter.set_task_id("task-123")

        change = FileChange(
            file_path="/path/to/file.txt",
            change_type="add",
            range_start=0,
            range_end=10,
            original="",
            modified="new content",
        )
        emitter.emit_file_change(change)

        mock_socketio.emit.assert_called_once()
        call_args = mock_socketio.emit.call_args
        assert call_args[0][0] == "doc_file_change"
        assert call_args[0][1]["highlight_color"] == "green"


# ============================================================================
# MultiFileCoordinator Tests
# ============================================================================


class TestMultiFileCoordinator:
    """Tests for MultiFileCoordinator."""

    def test_coordinator_singleton(self):
        """Test getting singleton coordinator."""
        coord1 = get_file_coordinator()
        coord2 = get_file_coordinator()
        assert coord1 is coord2

    def test_track_change(self, temp_workspace):
        """Test change tracking."""
        coord = MultiFileCoordinator(workspace_root=temp_workspace)
        change = coord.track_change(
            path=str(Path(temp_workspace) / "test.txt"),
            original="old",
            modified="new",
            change_type="modify",
        )

        assert change.file_path.endswith("test.txt")
        assert change.original == "old"
        assert change.modified == "new"

        # Verify it's in the log
        changes = coord.get_changes()
        assert len(changes) == 1

    def test_take_snapshot(self, temp_workspace):
        """Test taking file snapshot."""
        coord = MultiFileCoordinator(workspace_root=temp_workspace)
        test_file = str(Path(temp_workspace) / "test.txt")

        snapshot = coord.take_snapshot(test_file)

        assert snapshot.path == test_file
        assert "This is a test document" in snapshot.content
        assert snapshot.content_hash

    def test_has_changed_detection(self, temp_workspace):
        """Test file change detection."""
        coord = MultiFileCoordinator(workspace_root=temp_workspace)
        test_file = Path(temp_workspace) / "test.txt"

        # Take initial snapshot
        coord.take_snapshot(str(test_file))

        # Should not have changed
        assert not coord.has_changed(str(test_file))

        # Modify the file
        test_file.write_text("Modified content", encoding="utf-8")

        # Should now be changed
        assert coord.has_changed(str(test_file))

    def test_calculate_similarity(self):
        """Test text similarity calculation."""
        coord = MultiFileCoordinator()

        # Identical texts
        sim = coord._calculate_similarity("hello world", "hello world")
        assert sim == 1.0

        # Completely different
        sim = coord._calculate_similarity("aaa", "bbb")
        assert sim < 0.5

        # Partially similar
        sim = coord._calculate_similarity("hello world", "hello there")
        assert 0.4 < sim < 0.8

    def test_find_differences(self):
        """Test finding differences between texts."""
        coord = MultiFileCoordinator()

        text1 = "line1\nline2\nline3"
        text2 = "line1\nmodified\nline3"

        diffs = coord._find_differences(text1, text2, "file1.txt", "file2.txt")

        assert len(diffs) > 0
        # Should have found the line2 -> modified difference


# ============================================================================
# Integration Tests
# ============================================================================


class TestDocAgentIntegration:
    """Integration tests for the full DocAgent pipeline."""

    @pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"), reason="Requires GEMINI_API_KEY"
    )
    def test_full_pipeline_with_real_llm(self, temp_workspace):
        """Test full pipeline with real LLM (requires API key)."""
        # Create a test file
        test_file = Path(temp_workspace) / "test_doc.txt"
        test_file.write_text("This is a test document about AI.", encoding="utf-8")

        task = DocTask(
            id="integration-test",
            prompt="总结这个文档的内容",
            files=[
                FileHandle(
                    path=str(test_file),
                    content_snapshot=test_file.read_text(),
                )
            ],
        )

        agent = DocAgent()
        events = list(agent.run(task))

        # Should have multiple event types
        event_types = {e.event_type for e in events}

        assert DocEventType.PLAN_START in event_types
        assert DocEventType.TASK_COMPLETE in event_types


# ============================================================================
# Run tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
