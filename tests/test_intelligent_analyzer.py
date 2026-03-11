#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试智能文档分析引擎
Test Intelligent Document Analyzer
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加web路径到系统路径
web_dir = Path(__file__).parent / "web"
sys.path.insert(0, str(web_dir))

from web.document_reader import DocumentReader
from web.intelligent_document_analyzer import IntelligentDocumentAnalyzer


class MockLLMClient:
    """模拟LLM客户端用于测试"""

    def __init__(self):
        self.call_count = 0

    async def chat(self, prompt: str, model_name: str = None, stream: bool = False):
        """模拟chat接口"""
        self.call_count += 1

        # 根据prompt类型返回不同的mock内容
        if "摘要" in prompt or "abstract" in prompt.lower():
            return {
                "content": """本研究探讨了算法形式主义在当代社会的危机。
                
研究背景：随着人工智能和大数据技术的快速发展，算法已经成为现代社会决策的核心工具。然而，过度依赖算法形式化方法导致了对复杂社会现实的简化和误读。

研究方法：本文采用理论分析和案例研究相结合的方法，从技术哲学和社会学双重视角审视算法形式主义的本质、表现及其社会影响。

研究结果：研究发现，算法形式主义主要表现在三个层面：技术层面的抽象化倾向、认识论层面的还原主义思维、以及实践层面的决策自动化。这种形式主义导致了"数字之眼"的危机——算法看似精确却无法捕捉人类社会的复杂性和价值多元性。

研究结论：要克服算法形式主义危机，需要在技术设计中引入情境理性、在算法应用中保持人文关怀、在制度建设中强化算法问责。本研究为理解和应对算法社会的挑战提供了理论框架和实践路径。"""
            }

        elif "引言" in prompt or "introduction" in prompt.lower():
            return {
                "content": """一、问题的提出

算法技术的快速发展深刻改变了当代社会的运行逻辑。从搜索引擎的信息排序，到社交媒体的内容推荐，再到司法系统的量刑建议，算法已经渗透到社会生活的方方面面。然而，在算法应用日益广泛的同时，一种"算法形式主义"的倾向也日益明显——即过度相信算法的形式化方法能够解决一切问题，忽视了社会现实的复杂性和价值判断的必要性。这种倾向引发了本文所关注的核心问题：算法形式主义的本质是什么？它如何影响我们的认知和实践？我们应当如何应对？

二、研究的层次展开

本文采用层层递进的论证结构来回答上述问题。第二章将从技术哲学的角度，分析算法形式主义的认识论根源，揭示其背后的还原主义思维模式及其局限性。第三章转向实践层面，通过具体案例剖析算法形式主义在不同领域的表现形式，特别是在决策自动化过程中产生的价值冲突和伦理困境。第四章在理论和实践分析的基础上，提出"数字之眼的危机"这一核心概念，指出算法形式主义导致了技术理性与人文价值之间的深刻张力。第五章则探讨克服算法形式主义的可能路径，提出情境理性、人文关怀和算法问责三个维度的解决框架。

三、研究的意义

本研究的理论意义在于，它将算法问题置于技术哲学和社会理论的双重视野中，揭示了算法形式主义作为一种认识论和方法论危机的深层本质。实践意义在于，它为算法治理和技术伦理建设提供了批判性反思的基础和建设性的改革方向。在算法深度嵌入社会的今天，这种反思和改革具有紧迫的现实价值。"""
            }

        elif "结论" in prompt or "conclusion" in prompt.lower():
            return {
                "content": """本文系统探讨了算法形式主义危机的多个层面，现总结如下：

一、算法形式主义的认识论根源（第二章）

第二章从技术哲学的角度出发，揭示了算法形式主义的认识论根源在于还原主义思维模式。这种思维模式试图将复杂的社会现实简化为可计算的形式化结构，忽视了人类社会的情境依赖性、价值多元性和历史动态性。研究表明，算法的抽象化过程虽然提高了计算效率，但也导致了对社会复杂性的系统性误读。

二、算法形式主义的实践表征（第三章）

第三章通过案例分析展示了算法形式主义在司法、教育、就业等领域的具体表现。研究发现，过度依赖算法决策导致了三个突出问题：一是决策过程的"黑箱化"，削弱了人类的主体性；二是价值判断的"技术化"，回避了伦理责任；三是社会治理的"去政治化"，掩盖了权力关系。这些问题共同指向了算法形式主义在实践层面的严重后果。

三、"数字之眼"的危机诊断（第四章）

第四章提出了"数字之眼的危机"这一核心概念，指出算法形式主义的本质是技术理性的僭越——它试图用形式化的计算逻辑取代人类的价值判断和情境理解。这种危机的深层根源在于现代性的工具理性传统，而其当代表现则是算法权力的扩张。"数字之眼"看似精确却盲目，看似客观却偏颇，这正是算法形式主义最深刻的悖论。

四、克服危机的可能路径（第五章）

第五章探讨了克服算法形式主义危机的三条路径：技术层面引入情境理性，承认算法的局限性和情境依赖性；应用层面保持人文关怀，在算法决策中保留人类的价值判断空间；制度层面强化算法问责，建立透明、可解释、可问责的算法治理机制。这三条路径相互支撑，共同构成了应对算法形式主义危机的综合框架。

五、研究贡献与局限

本研究的主要贡献在于：第一，从技术哲学角度系统阐释了算法形式主义的认识论本质；第二，通过实证案例揭示了算法形式主义的实践后果；第三，提出了"数字之眼的危机"这一理论框架；第四，构建了克服危机的多维度解决方案。

同时，本研究也存在一定局限性。主要体现在：第一，案例分析主要集中于特定领域，未能涵盖算法应用的全部场景；第二，对算法内部技术细节的讨论相对有限，更多聚焦于其社会和哲学层面；第三，提出的解决路径需要在更广泛的实践中检验其有效性。

六、未来研究方向

未来研究可以在以下几个方向深化：第一，开展跨文化比较研究，探讨不同社会文化背景下算法形式主义的差异性表现；第二，与计算机科学家合作，探索在技术层面实现情境理性的具体方法；第三，开展追踪研究，评估算法治理政策的长期效果；第四，扩展到新兴领域如生成式AI，分析其带来的新型形式主义挑战。

总之，算法形式主义危机是当代技术社会面临的根本性挑战之一。克服这一危机不仅需要技术创新，更需要哲学反思、伦理自觉和制度保障。只有在技术理性与人文价值之间找到平衡，我们才能真正驾驭算法技术，而不是被其所驾驭。"""
            }

        return {
            "content": f"[Mock LLM Response for call #{self.call_count}]\n{prompt[:200]}..."
        }


async def test_document_structure_analysis():
    """测试文档结构分析"""
    print("\n" + "=" * 60)
    print("测试1: 文档结构分析")
    print("=" * 60)

    # 使用实际的论文文件
    doc_path = (
        Path(__file__).parent
        / "web"
        / "uploads"
        / "数字之眼的危机^L7算法的形式主义危机(1).docx"
    )

    if not doc_path.exists():
        print(f"❌ 文档不存在: {doc_path}")
        return False

    print(f"📄 读取文档: {doc_path.name}")

    try:
        doc_structure = DocumentReader.read_word(str(doc_path))

        if not doc_structure.get("success"):
            print(f"❌ 读取失败: {doc_structure.get('error')}")
            return False

        paragraphs = doc_structure.get("paragraphs", [])
        print(f"✅ 成功读取 {len(paragraphs)} 个段落")

        # 显示文档结构
        print("\n文档结构概览:")
        headings = [
            (idx, p["text"][:50], p.get("level", 1))
            for idx, p in enumerate(paragraphs)
            if p.get("type") == "heading"
        ]

        for idx, text, level in headings[:10]:  # 显示前10个标题
            indent = "  " * (level - 1)
            print(f"  {indent}[{idx}] {text}")

        return True

    except Exception as e:
        print(f"❌ 异常: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


async def test_request_analysis():
    """测试请求意图分析"""
    print("\n" + "=" * 60)
    print("测试2: 请求意图分析")
    print("=" * 60)

    mock_client = MockLLMClient()
    analyzer = IntelligentDocumentAnalyzer(mock_client)

    # 测试用例
    test_cases = [
        {
            "input": "写一段摘要，300-400字，包含研究背景、方法、结果、结论",
            "expected_tasks": ["write_abstract"],
        },
        {
            "input": "改进引言部分，使其与文章架构相符",
            "expected_tasks": ["revise_intro"],
        },
        {
            "input": "重新改善引言，并改善结论",
            "expected_tasks": ["revise_intro", "revise_conclusion"],
        },
        {
            "input": "写一段摘要，300-400字；重新改善引言，让其与文章主体架构相符；改善结论，overcap整篇文章内容",
            "expected_tasks": ["write_abstract", "revise_intro", "revise_conclusion"],
        },
    ]

    doc_path = (
        Path(__file__).parent
        / "web"
        / "uploads"
        / "数字之眼的危机^L7算法的形式主义危机(1).docx"
    )
    doc_structure = DocumentReader.read_word(str(doc_path))

    all_pass = True
    for idx, test in enumerate(test_cases, 1):
        print(f"\n测试用例 {idx}:")
        print(f"  输入: {test['input']}")

        result = analyzer.analyze_request(test["input"], doc_structure)

        detected_task_types = [t["type"] for t in result["tasks"]]
        print(f"  检测到的任务: {detected_task_types}")
        print(f"  文档类型: {result['document_type']}")
        print(f"  是否多任务: {result['is_multi_task']}")
        print(f"  置信度: {result['confidence']:.2f}")

        # 验证是否包含预期任务
        expected_found = all(
            exp in detected_task_types for exp in test["expected_tasks"]
        )
        if expected_found:
            print(f"  ✅ 通过")
        else:
            print(f"  ❌ 失败 - 预期任务: {test['expected_tasks']}")
            all_pass = False

    return all_pass


async def test_prompt_generation():
    """测试专用提示词生成"""
    print("\n" + "=" * 60)
    print("测试3: 专用提示词生成")
    print("=" * 60)

    mock_client = MockLLMClient()
    analyzer = IntelligentDocumentAnalyzer(mock_client)

    doc_path = (
        Path(__file__).parent
        / "web"
        / "uploads"
        / "数字之眼的危机^L7算法的形式主义危机(1).docx"
    )
    doc_structure = DocumentReader.read_word(str(doc_path))

    # 测试摘要任务提示词
    task = {
        "type": "write_abstract",
        "description": "生成论文摘要",
        "target_sections": ["paragraph_0"],
    }

    user_input = "写一段摘要，300-400字"

    prompt = analyzer.generate_specialized_prompt(task, doc_structure, user_input)

    print(f"任务类型: {task['type']}")
    print(f"生成的提示词长度: {len(prompt)} 字符")
    print(f"\n提示词前300字:")
    print(prompt[:300])

    # 检查提示词是否包含关键要素
    required_elements = ["研究背景", "研究方法", "研究结果", "研究结论", "300-400"]
    found_elements = [elem for elem in required_elements if elem in prompt]

    print(f"\n✅ 包含的关键要素: {found_elements}")

    if len(found_elements) >= 4:
        print("✅ 提示词质量合格")
        return True
    else:
        print("❌ 提示词缺少必要元素")
        return False


async def test_full_streaming_process():
    """测试完整的流式处理流程"""
    print("\n" + "=" * 60)
    print("测试4: 完整流式处理流程（使用Mock LLM）")
    print("=" * 60)

    mock_client = MockLLMClient()
    analyzer = IntelligentDocumentAnalyzer(mock_client)

    doc_path = (
        Path(__file__).parent
        / "web"
        / "uploads"
        / "数字之眼的危机^L7算法的形式主义危机(1).docx"
    )
    output_dir = Path(__file__).parent / "workspace" / "test_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    user_input = "写一段摘要，300-400字；重新改善引言；改善结论"

    print(f"📄 文档: {doc_path.name}")
    print(f"📝 请求: {user_input}")
    print(f"📁 输出目录: {output_dir}")
    print("\n开始流式处理...\n")

    try:
        event_count = 0
        async for event in analyzer.process_document_revision_streaming(
            str(doc_path), user_input, str(output_dir)
        ):
            event_count += 1
            stage = event.get("stage", "unknown")
            progress = event.get("progress", 0)
            message = event.get("message", "")

            print(f"[{event_count}] {stage.upper():15} | {progress:3}% | {message}")

            if "detail" in event:
                detail = event["detail"]
                if len(detail) > 100:
                    print(f"      详情: {detail[:100]}...")
                else:
                    print(f"      详情: {detail}")

        print(f"\n✅ 流式处理完成，共 {event_count} 个事件")
        print(f"✅ LLM调用次数: {mock_client.call_count}")

        return True

    except Exception as e:
        print(f"\n❌ 流式处理失败: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("=" * 60)
    print("智能文档分析引擎 - 综合测试")
    print("=" * 60)

    results = []

    # 测试1: 文档结构分析
    result1 = await test_document_structure_analysis()
    results.append(("文档结构分析", result1))

    # 测试2: 请求意图分析
    result2 = await test_request_analysis()
    results.append(("请求意图分析", result2))

    # 测试3: 提示词生成
    result3 = await test_prompt_generation()
    results.append(("专用提示词生成", result3))

    # 测试4: 完整流式处理
    result4 = await test_full_streaming_process()
    results.append(("完整流式处理", result4))

    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    for test_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{test_name:20} : {status}")

    total_pass = sum(1 for _, passed in results if passed)
    total_tests = len(results)

    print(f"\n总计: {total_pass}/{total_tests} 个测试通过")

    if total_pass == total_tests:
        print("\n🎉 所有测试通过！智能文档分析引擎工作正常。")
    else:
        print(f"\n⚠️  有 {total_tests - total_pass} 个测试失败，需要修复。")


if __name__ == "__main__":
    asyncio.run(main())
