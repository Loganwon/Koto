# Test Template - Start with these boilerplate tests

## FileOperator Tests Example

\\\python
import pytest
from unittest.mock import Mock, patch, MagicMock
from web.app import FileOperator

class TestFileOperator:
    \"\"\"Tests for FileOperator class\"\"\"
    
    def test_is_file_operation_with_file_keywords(self):
        \"\"\"Test detection of file operation keywords\"\"\"
        assert FileOperator.is_file_operation("读取文件test.txt") == True
        assert FileOperator.is_file_operation("open file data.csv") == True
        assert FileOperator.is_file_operation("delete file config.json") == True
    
    def test_is_file_operation_without_keywords(self):
        \"\"\"Test non-file operations return False\"\"\"
        assert FileOperator.is_file_operation("你好吗") == False
        assert FileOperator.is_file_operation("今天天气怎么样") == False
    
    def test_is_folder_organize_intent_true(self):
        \"\"\"Test folder organize intent detection\"\"\"
        assert FileOperator._is_folder_organize_intent("整理文件夹") == True
        assert FileOperator._is_folder_organize_intent("归纳目录") == True
    
    def test_is_folder_organize_intent_false(self):
        \"\"\"Test non-organize intents\"\"\"
        assert FileOperator._is_folder_organize_intent("删除文件") == False
    
    def test_extract_path_quoted(self):
        \"\"\"Test path extraction from quoted strings\"\"\"
        result = FileOperator._extract_path_from_text('Organize "/home/user/downloads"')
        assert result == "/home/user/downloads"
    
    def test_extract_path_windows(self):
        \"\"\"Test Windows path extraction\"\"\"
        result = FileOperator._extract_path_from_text('"C:\\\\Users\\\\Documents"')
        assert result == "C:\\\\Users\\\\Documents"
    
    def test_extract_path_not_found(self):
        \"\"\"Test empty string when no path found\"\"\"
        result = FileOperator._extract_path_from_text("no path here")
        assert result == ""
    
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=MagicMock)
    def test_execute_read_file(self, mock_open, mock_exists):
        \"\"\"Test file reading operation\"\"\"
        mock_exists.return_value = True
        mock_open.return_value.__enter__.return_value.read.return_value = "file content"
        
        # Test implementation
        pass
    
    @patch('os.stat')
    @patch('os.path.exists')
    def test_get_file_metadata_success(self, mock_exists, mock_stat):
        \"\"\"Test successful file metadata retrieval\"\"\"
        mock_exists.return_value = True
        mock_stat.return_value = Mock(st_size=1024, st_ctime=0, st_mtime=0)
        
        # Test implementation
        pass

# Similar templates for WebSearcher, ContextAnalyzer, Utils, SessionManager
\\\

---

## WebSearcher Tests Example

\\\python
class TestWebSearcher:
    \"\"\"Tests for WebSearcher class\"\"\"
    
    def test_needs_web_search_weather_keyword(self):
        \"\"\"Test weather keyword detection\"\"\"
        assert WebSearcher.needs_web_search("今天天气怎么样") == True
        assert WebSearcher.needs_web_search("温度多少") == True
    
    def test_needs_web_search_travel_pattern(self):
        \"\"\"Test travel pattern matching\"\"\"
        assert WebSearcher.needs_web_search("明天从北京到上海的高铁票") == True
    
    def test_needs_web_search_no_match(self):
        \"\"\"Test non-web-search queries\"\"\"
        assert WebSearcher.needs_web_search("你好") == False
    
    def test_detect_query_type_travel(self):
        \"\"\"Test travel type detection\"\"\"
        assert WebSearcher._detect_query_type("高铁票查询") == "travel"
        assert WebSearcher._detect_query_type("机票信息") == "travel"
    
    def test_detect_query_type_weather(self):
        \"\"\"Test weather type detection\"\"\"
        assert WebSearcher._detect_query_type("明天天气") == "weather"
    
    def test_detect_query_type_finance(self):
        \"\"\"Test finance type detection\"\"\"
        assert WebSearcher._detect_query_type("股票行情") == "finance"
    
    def test_build_search_context_travel(self):
        \"\"\"Test travel context building\"\"\"
        query, instruction = WebSearcher._build_search_context("高铁票", "travel")
        assert query == "高铁票"
        assert "Markdown 表格" in instruction
        assert "班次" in instruction
    
    def test_build_search_context_weather(self):
        \"\"\"Test weather context building\"\"\"
        query, instruction = WebSearcher._build_search_context("天气", "weather")
        assert query == "天气"
        assert "气温" in instruction
\\\

---

## ContextAnalyzer Tests Example

\\\python
class TestContextAnalyzer:
    \"\"\"Tests for ContextAnalyzer class\"\"\"
    
    def test_extract_entities_color(self):
        \"\"\"Test color entity extraction\"\"\"
        entities = ContextAnalyzer.extract_entities("红色的图片")
        colors = [e for e in entities if e['type'] == 'color']
        assert len(colors) > 0
        assert colors[0]['value'] == '红色'
    
    def test_extract_entities_multiple(self):
        \"\"\"Test multiple entity extraction\"\"\"
        entities = ContextAnalyzer.extract_entities("红色卡通的猫")
        # Should find color, style, subject
        assert len(entities) >= 3
    
    def test_build_context_summary_empty_history(self):
        \"\"\"Test context summary with empty history\"\"\"
        summary = ContextAnalyzer.build_context_summary([])
        assert summary['is_continuation'] == False
    
    def test_build_context_summary_with_history(self):
        \"\"\"Test context summary extraction from history\"\"\"
        history = [
            {"role": "user", "parts": ["生成一个红色的猫"], "timestamp": "2024-01-01"},
            {"role": "model", "parts": ["已生成"], "timestamp": "2024-01-01"}
        ]
        summary = ContextAnalyzer.build_context_summary(history)
        assert summary['last_user_intent'] == "生成一个红色的猫"
        assert summary['last_model_output'] == "已生成"
    
    def test_analyze_context_not_continuation_short_history(self):
        \"\"\"Test continuation detection with short history\"\"\"
        history = [{"role": "user", "parts": ["hello"]}]
        result = ContextAnalyzer.analyze_context("再来一个", history)
        assert result['is_continuation'] == False  # History too short
    
    def test_analyze_context_continuation_modify(self):
        \"\"\"Test modification pattern detection\"\"\"
        history = [
            {"role": "user", "parts": ["生成图片"]},
            {"role": "model", "parts": ["已生成"]},
            {"role": "user", "parts": ["再来一张"]}
        ]
        result = ContextAnalyzer.analyze_context("更大一点", history)
        if len(history) >= 2:
            assert result['continuation_type'] in [None, 'modify']
\\\

---

## Utils Tests Example

\\\python
class TestUtils:
    \"\"\"Tests for Utils class\"\"\"
    
    def test_sanitize_string_valid_utf8(self):
        \"\"\"Test UTF-8 sanitization\"\"\"
        result = Utils.sanitize_string("你好")
        assert result == "你好"
    
    def test_sanitize_string_non_string(self):
        \"\"\"Test non-string input\"\"\"
        assert Utils.sanitize_string(123) == 123
    
    def test_is_failure_output_empty(self):
        \"\"\"Test failure detection for empty string\"\"\"
        assert Utils.is_failure_output("") == True
    
    def test_is_failure_output_with_failure_emoji(self):
        \"\"\"Test failure emoji detection\"\"\"
        assert Utils.is_failure_output("❌ 操作失败") == True
    
    def test_is_failure_output_with_failure_keywords(self):
        \"\"\"Test failure keyword detection\"\"\"
        assert Utils.is_failure_output("无法联网") == True
        assert Utils.is_failure_output("没有实时数据") == True
        assert Utils.is_failure_output("i don't have access to the internet") == True
    
    def test_is_failure_output_success(self):
        \"\"\"Test success detection\"\"\"
        assert Utils.is_failure_output("✅ 成功") == False
    
    def test_detect_required_packages(self):
        \"\"\"Test package detection from imports\"\"\"
        code = "import numpy\\nfrom PIL import Image"
        packages = Utils.detect_required_packages(code)
        assert "numpy" in packages
        assert "Pillow" in packages
    
    def test_detect_required_packages_not_in_allowlist(self):
        \"\"\"Test that non-allowlist packages are filtered\"\"\"
        code = "import os\\nimport sys"
        packages = Utils.detect_required_packages(code)
        assert len(packages) == 0  # os and sys not in allowlist
\\\

---

## SessionManager Tests Example

\\\python
import tempfile
import os
import json
from pathlib import Path

class TestSessionManager:
    \"\"\"Tests for SessionManager class\"\"\"
    
    @pytest.fixture
    def temp_chat_dir(self):
        \"\"\"Create temporary chat directory\"\"\"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('app.CHAT_DIR', tmpdir):
                yield tmpdir
    
    def test_create_session(self, temp_chat_dir):
        \"\"\"Test session creation\"\"\"
        manager = SessionManager()
        filename = manager.create("test_session")
        
        assert filename.endswith(".json")
        assert os.path.exists(os.path.join(temp_chat_dir, filename))
    
    def test_create_session_collision_handling(self, temp_chat_dir):
        \"\"\"Test timestamp appending for duplicate names\"\"\"
        manager = SessionManager()
        filename1 = manager.create("test_session")
        filename2 = manager.create("test_session")
        
        assert filename1 != filename2
        assert "test_session" in filename1
        assert "test_session" in filename2
    
    def test_save_and_load(self, temp_chat_dir):
        \"\"\"Test save and load roundtrip\"\"\"
        manager = SessionManager()
        filename = manager.create("test")
        
        history = [
            {"role": "user", "parts": ["hello"]},
            {"role": "model", "parts": ["hi"]}
        ]
        manager.save(filename, history)
        
        loaded = manager.load(filename)
        assert len(loaded) == 2
    
    def test_delete_session(self, temp_chat_dir):
        \"\"\"Test session deletion\"\"\"
        manager = SessionManager()
        filename = manager.create("test")
        
        assert manager.delete(filename) == True
        assert manager.delete("nonexistent.json") == False
    
    def test_list_sessions_sorting(self, temp_chat_dir):
        \"\"\"Test sessions sorted by modification time\"\"\"
        manager = SessionManager()
        f1 = manager.create("first")
        f2 = manager.create("second")
        
        sessions = manager.list_sessions()
        assert f2 in sessions  # Most recent
\\\

---

Use these templates as starting points for your comprehensive test suite!
