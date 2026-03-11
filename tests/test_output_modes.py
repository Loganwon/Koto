#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
测试新灵活输出模式 - 验证系统不再被锁定在一种行为中
"""

import asyncio
import os
import sys

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from web.intelligent_document_analyzer import IntelligentDocumentAnalyzer


async def test_flexible_output_modes():
    """测试灵活的输出模式"""

    # 创建mock LLM客户端
    class MockLLM:
        async def chat(self, prompt, **kwargs):
            return {"content": "这是生成的内容"}

        def generate_content(self, prompt):
            class Response:
                text = "这是生成的内容"

            return Response()

    analyzer = IntelligentDocumentAnalyzer(MockLLM())

    print("=" * 70)
    print("🎯 灵活输出模式测试")
    print("=" * 70)

    # 测试1: 生成摘要 (应该返回生成的文本)
    print("\n[测试1] 生成摘要请求")
    print("-" * 70)
    request1 = "写一段摘要：三段，300字左右"
    doc_structure = {
        "paragraphs": [{"text": "文章内容", "type": "paragraph"}],
        "sections": ["引言", "方法", "结果", "结论"],
        "full_text": "这是一篇论文...",
    }
    result1 = analyzer.analyze_request(request1, doc_structure)
    tasks1 = result1["tasks"]
    output_type1 = analyzer._determine_output_type(tasks1)
    print(f"用户请求: {request1}")
    print(f"识别的任务: {[t.get('type') for t in tasks1]}")
    print(f"确定的输出类型: {output_type1}")
    print(f"✅ 预期: 'generate' -> 应该返回生成的摘要文本")
    print(
        f"✅ 结果: {output_type1 == 'generate'} - {'✓ 通过' if output_type1 == 'generate' else '✗ 失败'}"
    )

    # 测试2: 改善结论 (应该返回生成的文本)
    print("\n[测试2] 改善结论请求")
    print("-" * 70)
    request2 = "重新改善结论，要求总结全文内容"
    result2 = analyzer.analyze_request(request2, doc_structure)
    tasks2 = result2["tasks"]
    output_type2 = analyzer._determine_output_type(tasks2)
    print(f"用户请求: {request2}")
    print(f"识别的任务: {[t.get('type') for t in tasks2]}")
    print(f"确定的输出类型: {output_type2}")
    print(f"✅ 预期: 'generate' -> 应该返回改进的结论文本")
    print(
        f"✅ 结果: {output_type2 == 'generate'} - {'✓ 通过' if output_type2 == 'generate' else '✗ 失败'}"
    )

    # 测试3: 分析请求 (应该返回分析结果)
    print("\n[测试3] 分析请求")
    print("-" * 70)
    request3 = "分析这篇论文的结构和逻辑"
    result3 = analyzer.analyze_request(request3, doc_structure)
    tasks3 = result3["tasks"]
    output_type3 = analyzer._determine_output_type(tasks3)
    print(f"用户请求: {request3}")
    print(f"识别的任务: {[t.get('type') for t in tasks3]}")
    print(f"确定的输出类型: {output_type3}")
    print(f"✅ 预期: 'analysis' -> 应该返回分析结果")
    print(
        f"✅ 结果: {output_type3 == 'analysis'} - {'✓ 通过' if output_type3 == 'analysis' else '✗ 失败'}"
    )

    # 测试4: 改善引言 (应该返回生成的文本)
    print("\n[测试4] 改善引言请求")
    print("-" * 70)
    request4 = "重新改善引言，使其与文章主体架构相符"
    result4 = analyzer.analyze_request(request4, doc_structure)
    tasks4 = result4["tasks"]
    output_type4 = analyzer._determine_output_type(tasks4)
    print(f"用户请求: {request4}")
    print(f"识别的任务: {[t.get('type') for t in tasks4]}")
    print(f"确定的输出类型: {output_type4}")
    print(f"✅ 预期: 'generate' -> 应该返回改进的引言文本")
    print(
        f"✅ 结果: {output_type4 == 'generate'} - {'✓ 通过' if output_type4 == 'generate' else '✗ 失败'}"
    )

    print("\n" + "=" * 70)
    print("📊 测试摘要")
    print("=" * 70)

    all_passed = (
        output_type1 == "generate"
        and output_type2 == "generate"
        and output_type3 == "analysis"
        and output_type4 == "generate"
    )

    print(f"总体结果: {'✅ 所有测试通过' if all_passed else '❌ 某些测试失败'}")
    print("\n关键改进:")
    print("✨ 系统不再被锁定在单一模式")
    print("✨ 不同的请求得到不同的输出格式")
    print("✨ '生成摘要' -> 返回摘要文本 (不是修改文档)")
    print("✨ '改善结论' -> 返回结论文本 (不是修改文档)")
    print("✨ '分析' -> 返回分析结果")

    return all_passed


if __name__ == "__main__":
    result = asyncio.run(test_flexible_output_modes())
    sys.exit(0 if result else 1)
