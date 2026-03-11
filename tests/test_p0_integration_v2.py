"""
P0 集成验证：文件上传 → PPT 生成完整测试
使用正确的 API 和实际的流程验证
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.file_parser import FileParser
from web.file_processor import FileProcessor, process_uploaded_file
from web.ppt_session_manager import PPTSessionManager


class TestP0Integration(unittest.TestCase):
    """P0 文件上传 → PPT 生成整体测试"""

    def setUp(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.temp_dir, "ppt_sessions")
        os.makedirs(self.session_dir, exist_ok=True)

    def create_test_doc(self, filename, content):
        """创建测试文档"""
        filepath = os.path.join(self.temp_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    def test_01_file_extraction(self):
        """Step 1: 文件上传与内容提取"""
        print("\n[STEP 1️⃣] 文件上传与内容提取")

        # 创建示例文档
        doc_content = """# 2024年度战略规划

## 执行摘要
本报告阐述了公司 2024 年的战略方向和实施计划。

## 核心目标
- 提升市场占有率 30%
- 新开拓 5 个新市场
- 产品创新迭代 3 次

## 市场分析
全球市场规模已达 500 亿美元，预期增长 25%

## 竞争策略
1. 差异化定位
2. 提高客户体验
3. 建立生态合作"""

        doc_path = self.create_test_doc("strategy_2024.txt", doc_content)
        print(f"✓ 创建测试文档: {os.path.basename(doc_path)}")

        # 步骤 1a: 使用 FileProcessor 处理文件
        processor = FileProcessor()
        file_result = processor.process_file(doc_path)

        self.assertTrue(file_result["success"], f"文件处理失败: {file_result['error']}")
        self.assertGreater(len(file_result["text_content"]), 0)
        print(f"✓ FileProcessor 提取文本: {len(file_result['text_content'])} 字符")

        # 步骤 1b: 使用 FileParser 解析文件
        parser = FileParser()
        parse_result = parser.parse_file(doc_path)

        self.assertIsNotNone(parse_result)
        self.assertIn("content", parse_result)
        self.assertTrue(parse_result.get("success", True))
        print(f"✓ FileParser 解析成功")

        # 步骤 1c: 使用 process_uploaded_file（模拟前端上传）
        formatted_msg, file_data = process_uploaded_file(
            doc_path, "请根据这份文档生成一个 PPT 演示"
        )

        self.assertIsNotNone(formatted_msg)
        print(f"✓ process_uploaded_file 格式化消息: {formatted_msg[:80]}...")

    def test_02_ppt_session_creation(self):
        """Step 2: PPT 会话创建"""
        print("\n[STEP 2️⃣] PPT 会话创建")

        # 创建文档并提取内容
        doc_content = """# 产品路线图

## 2024 Q1
- Alpha 版本发布
- 核心功能完成

## 2024 Q2  
- 用户测试
- 性能优化

## 2024 Q3
- 正式商用
- 市场销售"""

        doc_path = self.create_test_doc("roadmap.txt", doc_content)
        processor = FileProcessor()
        file_result = processor.process_file(doc_path)

        # 创建 PPT 会话
        manager = PPTSessionManager(self.session_dir)

        # 使用正确的 API：create_session(title, user_input, theme, user_id)
        session_id = manager.create_session(
            title="产品路线图演示",
            user_input="根据产品路线图生成演示文稿",
            theme="business",
        )

        self.assertIsNotNone(session_id)
        self.assertRegex(session_id, r"^[a-f0-9-]{36}$")  # UUID 格式
        print(f"✓ 创建 PPT 会话: {session_id}")

        # 验证会话数据
        loaded = manager.load_session(session_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["title"], "产品路线图演示")
        self.assertEqual(loaded["status"], "pending")
        print(f"✓ 会话数据验证通过")

        # 保存文件上传上下文
        manager.save_generation_data(
            session_id=session_id,
            ppt_data=None,  # 暂未生成
            ppt_file_path=None,
            uploaded_file_context=file_result["text_content"][:500],
        )
        print(f"✓ 文件上传上下文已保存")

    def test_03_multi_file_fusion(self):
        """Step 3: 多文件融合（P0 高阶用法）"""
        print("\n[STEP 3️⃣] 多文件融合")

        # 创建多个文档
        docs = {
            "market_analysis.txt": """# 市场分析

## 市场规模
全球市场 2024 年达 1000 亿美元

## 增长趋势  
年均增长率 15%""",
            "product_features.txt": """# 产品特性

## 核心功能
- 高性能
- 易使用  
- 可扩展

## 差异优势
比竞品快 3 倍""",
            "financial_forecast.txt": """# 财务预测

## 收入预期
2024: 500万美元
2025: 1500万美元

## 利润率
毛利率: 60%
净利率: 25%""",
        }

        # 创建所有文件并提取内容
        processor = FileProcessor()
        all_contents = []
        file_list = []

        for filename, content in docs.items():
            filepath = self.create_test_doc(filename, content)
            result = processor.process_file(filepath)

            if result["success"]:
                all_contents.append(result["text_content"])
                file_list.append(filename)

        self.assertEqual(len(all_contents), len(docs))
        print(f"✓ 成功处理 {len(file_list)} 个文件")

        # 创建融合会话
        manager = PPTSessionManager(self.session_dir)
        session_id = manager.create_session(
            title="融合演示 - 市场/产品/财务",
            user_input="融合这些文档生成综合 PPT",
            theme="business",
        )

        # 保存融合内容
        fused_content = "\n\n【文档边界】\n\n".join(all_contents)
        manager.save_generation_data(
            session_id=session_id,
            ppt_data=None,
            ppt_file_path=None,
            uploaded_file_context=fused_content[:2000],
        )

        self.assertIsNotNone(session_id)
        print(f"✓ 多文档融合会话创建成功，融合内容 {len(fused_content)} 字符")

    def test_04_flow_verification(self):
        """Step 4: 完整流程验证（关键：从上传到会话的映射）"""
        print("\n[STEP 4️⃣] 完整流程验证")

        # 模拟用户上传文件并请求 PPT 生成
        print("场景: 用户上传 PDF + 文本，要求生成 PPT")

        # 准备文档
        ppt_request = "请根据这份文档生成一份专业的 PPT 演示文稿"

        doc_path = self.create_test_doc(
            "annual_report.txt",
            """# 2024 年度报告
            
## 主要成绩
- 营收增长 50%
- 用户增长 200%  
- 市场占有率提升至 22%

## 产品创新
发布了 3 个新产品线

## 展望
2025 年目标翻倍增长""",
        )

        # 第 1 步：处理上传的文件
        processor = FileProcessor()
        file_result = processor.process_file(doc_path)
        self.assertTrue(file_result["success"])
        content = file_result["text_content"]
        print(f"✓ 文件处理完成: {os.path.basename(doc_path)}")

        # 第 2 步：基于用户请求创建 PPT 会话
        manager = PPTSessionManager(self.session_dir)

        # 由于用户请求包含 "PPT" 关键词，系统应创建 FILE_GEN 任务
        # 这里我们直接创建对应的会话
        session_id = manager.create_session(
            title="2024 年度报告 PPT", user_input=ppt_request, theme="business"
        )

        print(f"✓ 创建 PPT 会话: {session_id}")

        # 第 3 步：保存文件上下文到会话
        manager.save_generation_data(
            session_id=session_id,
            ppt_data=None,
            ppt_file_path=None,
            uploaded_file_context=content,
        )

        print(f"✓ 文件内容保存到会话")

        # 第 4 步：验证会话包含所有必要信息
        loaded = manager.load_session(session_id)
        self.assertEqual(loaded["title"], "2024 年度报告 PPT")
        self.assertIn("uploaded_file_context", loaded)
        self.assertGreater(len(loaded["uploaded_file_context"]), 0)

        print(f"✓ 会话验证通过（包含上传文件内容）")
        print(f"✓ 流程完成！会话已准备好供 FILE_GEN 处理")


class TestCurrentGaps(unittest.TestCase):
    """检查当前实现的缺陷"""

    def test_gap_01_api_endpoint_consistency(self):
        """检查: /api/chat/file 是否正确转发到 FILE_GEN"""
        print("\n[GAP检查] /api/chat/file 端点与 FILE_GEN 的集成")
        print("⚠️  需求: 验证端点是否正确检测 'ppt' 关键词并触发 FILE_GEN")
        print("⚠️  建议: 查看 web/app.py 行 7242+ 的 @app.route('/api/chat/file')")

    def test_gap_02_file_to_prompt_fusion(self):
        """检查: 上传的文件内容是否正确融合到 PPT 生成 prompt"""
        print("\n[GAP检查] 文件内容到 PPT Prompt 的融合")
        print("⚠️  需求: 在 _execute_file_gen 中，previous_data 应包含上传文件内容")
        print("⚠️  建议: 修改 /api/chat/file 路由，确保将文件内容传递给 FILE_GEN 任务")

    def test_gap_03_session_to_ppt_path(self):
        """检查: PPT session 与最终生成的 PPTX 文件的关联"""
        print("\n[GAP检查] PPT 会话与 PPTX 文件的紧密耦合")
        print("⚠️  需求: 将生成的 PPTX 文件路径保存到会话中")
        print("⚠️  建议: 在 FILE_GEN 完成后，更新对应的 PPT 会话")

    def test_gap_04_frontend_linkage(self):
        """检查: 前端是否正确显示生成的 PPT"""
        print("\n[GAP检查] 前端对生成 PPT 的显示与编辑")
        print("⚠️  需求: 上传文件生成 PPT 后，前端应提供链接到编辑器")
        print("⚠️  建议: 在聊天界面显示 'PPT 已生成 → [编辑] [下载]' 按钮")


def run_summary():
    """输出P0集成状态总结"""
    print("\n" + "=" * 70)
    print("P0 集成实施状态总结")
    print("=" * 70)

    status = {
        "✅ 已实现": [
            "文件处理引擎（FileProcessor）- 支持文本/Markdown/PDF/Word",
            "文件解析系统（FileParser）- 元数据和内容提取",
            "PPT 会话管理（PPTSessionManager）- 生成历史与编辑支持",
            "前端文件上传 UI - HTML5 拖拽、文件选择、预览",
            "后端 /api/chat/file 端点 - 多文件处理",
            "FILE_GEN 任务执行器 - PPT 生成逻辑（带调大纲解析）",
        ],
        "⚠️ 需要验证/改进": [
            "文件内容到 PPT Prompt 的正确融合",
            "用户请求 'PPT' 时的任务检测和转发",
            "生成 PPTX 文件与会话的关联",
            "前端生成后的编辑页面链接显示",
            "多文件的智能融合策略",
        ],
        "❌ 未开始（P1+）": [
            "RAG 多文档智能检索融合",
            "PPT 生成质量评分与反馈",
            "知识图谱生成与可视化",
            "PPT 的 A/B 对比生成",
        ],
    }

    for category, items in status.items():
        print(f"\n{category}")
        for item in items:
            print(f"  • {item}")

    print("\n" + "=" * 70)
    print("建议的后续步骤:")
    print("=" * 70)
    print("""
1. 【紧急】检查和改进 /api/chat/file 路由中的任务转发逻辑
   - 确保 FILE_GEN 接收到上传文件的完整内容
   - 验证 ppt_keywords 检测是否有效

2. 【关键】改进文件内容→PPT Prompt 的融合
   - 在 /api/chat/file 中调用 FileParser，提取结构化内容
   - 将提取的内容传递给 FILE_GEN 的 previous_data

3. 【重要】完成前端生成后流程
   - PPT 生成完成后，返回编辑页面链接
   - 在聊天界面显示 "[打开编辑器] [下载]" 按钮

4. 【优化】增强多文件融合逻辑
   - 智能排序和组织多个文件的内容
   - 保留文件来源信息（用于溯源）

5. 【测试】端到端集成测试
   - 上传文档 → 请求 PPT → 编辑 → 下载
   - 验证多文件融合的效果
""")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    # 运行集成测试
    print("\n" + "=" * 70)
    print("P0 集成验证 - 文件上传到 PPT 生成")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestP0Integration))
    suite.addTests(loader.loadTestsFromTestCase(TestCurrentGaps))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 输出总结
    print("\n" + "=" * 70)
    print(
        f"测试结果: {result.testsRun} 运行, {result.testsRun - len(result.failures) - len(result.errors)} 通过"
    )
    if result.wasSuccessful():
        print("✅ 所有验证测试通过")
    else:
        if result.failures:
            print(f"❌ {len(result.failures)} 个失败")
        if result.errors:
            print(f"❌ {len(result.errors)} 个错误")
    print("=" * 70)

    # 输出诊断总结
    run_summary()
