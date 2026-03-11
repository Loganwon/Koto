"""
P0 前端集成测试：文件上传 → PPT 生成完整流程
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.file_parser import FileParser
from web.file_processor import FileProcessor, process_uploaded_file
from web.ppt_session_manager import PPTSessionManager


class TestFileProcessing(unittest.TestCase):
    """测试文件处理流程"""

    def setUp(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()

    def create_test_file(self, filename, content):
        """创建测试文件"""
        filepath = os.path.join(self.temp_dir, filename)

        if filename.endswith(".txt"):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        elif filename.endswith(".md"):
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        return filepath

    def test_01_file_processor_text_file(self):
        """测试 FileProcessor 处理文本文件"""
        print("\n[TEST] FileProcessor 处理文本文件...")

        filepath = self.create_test_file(
            "test_doc.txt", "这是一份测试文档\n包含多行内容\n用于验证文件处理功能"
        )

        processor = FileProcessor()
        result = processor.process_file(filepath)

        self.assertTrue(result["success"], f"文件处理失败：{result['error']}")
        self.assertEqual(result["filename"], "test_doc.txt")
        self.assertIn("测试文档", result["text_content"])
        print(f"✅ 成功处理文本文件，提取 {len(result['text_content'])} 字符")

    def test_02_file_processor_markdown_file(self):
        """测试 FileProcessor 处理 Markdown 文件"""
        print("\n[TEST] FileProcessor 处理 Markdown 文件...")

        md_content = """# 项目概览
        
## 项目简介
这是一个示例项目

## 主要功能
- 功能 1
- 功能 2
- 功能 3

## 技术栈
- Python 3.10
- Flask
- SQLite
"""

        filepath = self.create_test_file("test_project.md", md_content)

        processor = FileProcessor()
        result = processor.process_file(filepath)

        self.assertTrue(result["success"])
        self.assertIn("项目概览", result["text_content"])
        print(
            f"✅ 成功处理 Markdown 文件，包含 {result['text_content'].count('#')} 个标题"
        )

    def test_03_process_uploaded_file(self):
        """测试 process_uploaded_file 函数"""
        print("\n[TEST] process_uploaded_file 整合测试...")

        filepath = self.create_test_file(
            "integration_test.txt", "这是一份整合测试文档\n用于验证完整的处理流程"
        )

        user_message = "请帮我分析这个文档"
        formatted_msg, file_data = process_uploaded_file(filepath, user_message)

        self.assertIsNotNone(formatted_msg)
        print(f"✅ Formatted message: {formatted_msg[:100]}...")
        print(f"✅ File data keys: {list(file_data.keys()) if file_data else 'None'}")


class TestFileParser(unittest.TestCase):
    """测试 FileParser 模块"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def create_test_file(self, filename, content):
        filepath = os.path.join(self.temp_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    def test_01_parse_file_basic(self):
        """测试 FileParser.parse_file 基础功能"""
        print("\n[TEST] FileParser.parse_file 基础功能...")

        content = "# 测试报告\n## 概览\n这是一个测试摘要。"
        filepath = self.create_test_file("report.md", content)

        result = FileParser.parse_file(filepath)

        self.assertIsNotNone(result)
        self.assertIn("content", result)
        print(f"✅ FileParser 成功解析，内容长度: {len(result.get('content', ''))}")

    def test_02_parse_file_metadata(self):
        """测试 FileParser 元数据提取"""
        print("\n[TEST] FileParser 元数据提取...")

        content = "# 产品特性\n- 高性能\n- 易使用\n- 可扩展"
        filepath = self.create_test_file("features.txt", content)

        result = FileParser.parse_file(filepath)

        self.assertIsNotNone(result)
        self.assertIn("filename", result)
        self.assertIn("size", result)
        print(f"✅ 元数据: {result.get('filename')} ({result.get('size')} bytes)")


class TestPPTSessionManager(unittest.TestCase):
    """测试 PPT 会话管理"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.temp_dir, "sessions")
        os.makedirs(self.session_dir, exist_ok=True)

    def test_01_create_session(self):
        """测试创建 PPT 会话"""
        print("\n[TEST] 创建 PPT 会话...")

        manager = PPTSessionManager(self.session_dir)

        session_data = {
            "files": ["test.pdf"],
            "content": "这是一份测试内容",
            "outline": {"title": "测试演示", "slides": []},
        }

        session_id = manager.create_session(
            name="test_ppt", description="测试 PPT 会话", data=session_data
        )

        self.assertIsNotNone(session_id)
        print(f"✅ 创建会话: {session_id}")

    def test_02_load_session(self):
        """测试加载 PPT 会话"""
        print("\n[TEST] 加载 PPT 会话...")

        manager = PPTSessionManager(self.session_dir)

        # 创建会话
        session_data = {"files": ["test.pdf"], "content": "这是一份测试内容"}

        session_id = manager.create_session(name="load_test", data=session_data)

        # 加载会话
        loaded = manager.load_session(session_id)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["name"], "load_test")
        self.assertIn("files", loaded)
        print(f"✅ 成功加载会话: {loaded['name']}")


class TestIntegrationFlow(unittest.TestCase):
    """测试完整的文件上传 → PPT 生成流程"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def create_sample_document(self, filename, doc_type="report"):
        """创建示例文档"""
        content_map = {
            "report": """# 年度业绩报告

## 执行摘要
2024 年度完整业绩分析

## 关键指标
- 收入增长：35%
- 用户增长：150%
- 市场占有率：22%

## 产品线分析
### 产品 A
- 销量：5000 套
- 增长：45%

### 产品 B  
- 销量：3000 套
- 增长：25%

## 市场前景
预期 2025 年继续强劲增长""",
            "proposal": """# 项目建议书

## 项目名称
AI 辅助开发平台

## 项目目标
- 降低开发成本 40%
- 加快上市时间 50%
- 提高代码质量

## 技术方案
采用最新的 AI 模型和 API 集成

## 预算
初期投入 500 万元

## ROI
预期 18 个月内收回投资""",
            "analysis": """# 竞争分析报告

## 市场概况
全球 SaaS 市场规模 2000 亿美元

## 主要竞争对手
1. Competitor A - 市场占有率 35%
2. Competitor B - 市场占有率 28%
3. Competitor C - 市场占有率 18%

## 我们的优势
- 价格低 30%
- 功能更全面
- 本地化支持

## 市场机会
新兴市场有 500% 增长空间""",
        }

        filepath = os.path.join(self.temp_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content_map.get(doc_type, content_map["report"]))

        return filepath

    def test_01_full_flow_text_to_ppt_structure(self):
        """测试完整流程：文本 → 文件处理 → PPT 大纲"""
        print("\n[TEST] 完整流程：文本 → PPT 大纲...")

        # 第 1 步：创建示例文档
        doc_path = self.create_sample_document("report.txt", "report")
        print(f"✅ 创建示例文档: {doc_path}")

        # 第 2 步：处理文件
        processor = FileProcessor()
        file_result = processor.process_file(doc_path)

        self.assertTrue(file_result["success"])
        print(f"✅ 文件处理成功，内容长度: {len(file_result['text_content'])}")

        # 第 3 步：提取内容（模拟 FileParser）
        parser = FileParser()
        parse_result = parser.parse_file(doc_path)

        self.assertIsNotNone(parse_result)
        self.assertIn("content", parse_result)
        print(f"✅ 文件解析成功")

        # 第 4 步：创建 PPT 会话
        session_dir = os.path.join(self.temp_dir, "ppt_sessions")
        os.makedirs(session_dir, exist_ok=True)

        manager = PPTSessionManager(session_dir)
        session_id = manager.create_session(
            name="report_ppt",
            description="从报告文档生成的 PPT",
            data={
                "files": ["report.txt"],
                "file_content": file_result["text_content"][:2000],  # 截断
                "user_request": "生成一个 PPT 演示文稿",
            },
        )

        self.assertIsNotNone(session_id)
        print(f"✅ PPT 会话创建成功: {session_id}")

        # 第 5 步：验证会话内容
        loaded_session = manager.load_session(session_id)
        self.assertIsNotNone(loaded_session)
        self.assertIn("file_content", loaded_session["data"])
        print(f"✅ 会话数据完整性验证通过")

    def test_02_multiple_file_handling(self):
        """测试多文件处理"""
        print("\n[TEST] 多文件处理...")

        # 创建多个文档
        files = [
            self.create_sample_document("report.txt", "report"),
            self.create_sample_document("proposal.txt", "proposal"),
            self.create_sample_document("analysis.txt", "analysis"),
        ]

        print(f"✅ 创建 {len(files)} 个测试文档")

        # 处理每个文件
        processor = FileProcessor()
        contents = []

        for fpath in files:
            result = processor.process_file(fpath)
            if result["success"]:
                contents.append(result["text_content"][:500])

        self.assertEqual(len(contents), len(files))
        print(f"✅ 成功处理 {len(contents)} 个文件")

        # 创建融合会话
        session_dir = os.path.join(self.temp_dir, "multi_ppt")
        os.makedirs(session_dir, exist_ok=True)

        manager = PPTSessionManager(session_dir)
        session_id = manager.create_session(
            name="multi_doc_ppt",
            description="从多个文档融合生成的 PPT",
            data={
                "files": [os.path.basename(f) for f in files],
                "combined_content": "\n\n---\n\n".join(contents),
                "file_count": len(files),
            },
        )

        self.assertIsNotNone(session_id)
        print(f"✅ 多文档融合会话创建成功")


def run_diagnostics():
    """运行诊断，检查关键组件是否存在"""
    print("\n" + "=" * 60)
    print("P0 前端集成诊断")
    print("=" * 60)

    checks = [
        ("FileProcessor", "web/file_processor.py", FileProcessor),
        ("FileParser", "web/file_parser.py", FileParser),
        ("PPTSessionManager", "web/ppt_session_manager.py", PPTSessionManager),
    ]

    passed = 0
    failed = 0

    for name, path, module in checks:
        try:
            print(f"\n✓ {name} 模块已加载")
            print(f"  - 路径: {path}")

            # 检查关键方法
            if name == "FileProcessor":
                if hasattr(FileProcessor, "process_file"):
                    print(f"  - 方法: process_file ✓")
                    passed += 1
                else:
                    print(f"  - 方法: process_file ✗")
                    failed += 1

            elif name == "FileParser":
                if hasattr(FileParser, "parse_file"):
                    print(f"  - 方法: parse_file ✓")
                    passed += 1
                else:
                    print(f"  - 方法: parse_file ✗")
                    failed += 1

            elif name == "PPTSessionManager":
                if hasattr(PPTSessionManager, "create_session"):
                    print(f"  - 方法: create_session ✓")
                    if hasattr(PPTSessionManager, "load_session"):
                        print(f"  - 方法: load_session ✓")
                        passed += 1
                    else:
                        print(f"  - 方法: load_session ✗")
                        failed += 1
                else:
                    print(f"  - 方法: create_session ✗")
                    failed += 1

        except Exception as e:
            print(f"\n✗ {name} 模块加载失败: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"诊断结果: {passed} 通过, {failed} 失败")
    print(f"{'='*60}\n")

    return failed == 0


if __name__ == "__main__":
    # 运行诊断
    diag_ok = run_diagnostics()

    # 运行测试
    print("\n开始运行集成测试...\n")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestFileProcessing))
    suite.addTests(loader.loadTestsFromTestCase(TestFileParser))
    suite.addTests(loader.loadTestsFromTestCase(TestPPTSessionManager))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegrationFlow))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 输出总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"运行: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")

    if result.wasSuccessful():
        print("\n✅ 所有测试通过！P0 集成基础完整。")
    else:
        print("\n⚠️ 部分测试失败，需要进一步调查。")
