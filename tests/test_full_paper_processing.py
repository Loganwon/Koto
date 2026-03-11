#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
完整集成测试 - 使用真实LLM处理论文
Full Integration Test - Process Academic Paper with Real LLM
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Dict

# 添加web路径
web_dir = Path(__file__).parent / "web"
sys.path.insert(0, str(web_dir))

from web.document_reader import DocumentReader
from web.intelligent_document_analyzer import IntelligentDocumentAnalyzer


class RealLLMClient:
    """真实LLM客户端包装器"""

    def __init__(self, api_key=None):
        """
        初始化真实LLM客户端

        Args:
            api_key: Gemini API密钥（可选）
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.use_mock = False

        try:
            import google.generativeai as genai

            if self.api_key:
                genai.configure(api_key=self.api_key)
                self.client = genai.GenerativeModel("gemini-1.5-flash-preview")
                print(f"✅ Gemini API已连接")
                self.use_mock = False
            else:
                print("⚠️  未配置API密钥，将使用Mock LLM")
                self.use_mock = True
        except Exception as e:
            print(f"⚠️  Gemini初始化失败: {str(e)}，将使用Mock LLM")
            self.use_mock = True

    async def chat(self, prompt: str, model_name: str = None, stream: bool = False):
        """
        调用LLM生成内容

        Args:
            prompt: 提示词
            model_name: 模型名称（可选，此处忽略）
            stream: 是否流式输出（此处忽略）

        Returns:
            {'content': 生成的文本}
        """
        if self.use_mock:
            return await self._mock_response(prompt)

        try:
            import google.generativeai as genai

            response = self.client.generate_content(prompt)
            if response and response.text:
                return {"content": response.text}
            else:
                return {"content": "[无响应]"}
        except Exception as e:
            print(f"LLM调用失败: {str(e)}")
            return {"content": f"[错误: {str(e)}]"}

    async def _mock_response(self, prompt: str) -> Dict:
        """生成Mock响应"""
        if "摘要" in prompt or "abstract" in prompt.lower():
            return {
                "content": """本研究系统探讨了人工智能算法在现代社会中的形式主义危机。

研究背景与目的：随着人工智能技术的快速发展，算法已经深度嵌入到社会的各个领域，包括信息推荐、司法判决、和就业筛选等。然而，当前存在一种广泛的"算法形式主义"现象——对算法的盲目崇拜和过度依赖，将其视为客观、中立的工具，而忽视了其背后的价值预设和社会影响。这种现象引发了本研究对"数字之眼的危机"的深入思考。

研究方法：本研究采用文献分析、案例研究和理论批判相结合的方法，从技术哲学、社会学和传播学的多维视角，系统分析算法形式主义的根源、表现和影响。

研究结果与创新点：研究发现，算法形式主义的本质是对技术理性的绝对化，它导致了人类价值判断的被动化和社会权力关系的隐形化。通过"数字之眼的危机"这一核心概念，本研究揭示了算法设计和应用中存在的根本性矛盾——看似精确的计算反而可能造成更深层的偏见和不公正。

研究结论与局限：本研究的贡献在于从批判视角全面阐释了算法形式主义的危害，为算法规制和技术伦理提供了理论基础。同时，研究也存在一定局限，如对技术解决方案的深入讨论不足，这将是未来研究的重点。"""
            }

        elif "引言" in prompt or "introduction" in prompt.lower():
            return {
                "content": """一、核心问题与研究背景
当代社会已进入"算法时代"。从搜索引擎决定我们看到什么信息，到推荐系统塑造我们的消费选择，再到AI系统参与司法判决、入学评估等重大决策，算法已经成为社会运行的重要基础设施。然而，与这种广泛应用相伴随的是一种普遍的"算法迷思"：人们往往将算法视为客观、中立、科学的工具，相信数据和程序能够消除人类的偏见。这种信念构成了"算法形式主义"——一种对算法形式化方法的绝对化信仰，认为任何问题都可以通过算法化解决。本研究正是对这一现象的深入批判。

二、文章的论证架构
本文通过五章内容，逐步揭示算法形式主义的危机本质。

第二章（技术哲学视角）从认识论出发，分析算法作为一种认识工具的局限性。我们深入讨论了算法的形式化过程如何导致了对社会现实复杂性的简化和误读，揭示了其背后的还原主义假设。

第三章（社会实践维度）通过具体案例分析，展示了算法形式主义在司法系统、人力资源、城市治理等领域的具体表现及其社会后果。这些案例充分证明，算法的应用往往强化而非消解历史的不平等。

第四章（理论综合）在前两章分析的基础上，提出"数字之眼的危机"这一核心概念，揭示了算法形式主义的本质在于技术理性对人文价值的侵蚀。我们论证，这一危机不仅是技术问题，更是关乎现代性反思的哲学问题。

第五章（实践路向）在批判的基础上，提出克服算法形式主义的三条可能路径：在技术设计中引入情境理性，在社会应用中保持人文关怀，在制度建设中强化算法问责。

三、研究的理论与实践意义
本研究的意义体现在两个层面。理论层面，我们为当代信息社会的算法危机提供了系统的哲学批判和社会学分析，丰富了技术伦理的理论资源。实践层面，本研究为政策制定者、技术设计者和社会公众提供了认识算法、规制算法、驾驭算法的理论基础。当算法已然成为社会的关键基础设施时，对其形式主义倾向的深入反思，不仅是学术问题，更是涉及社会未来走向的重大现实问题。"""
            }

        elif "结论" in prompt or "conclusion" in prompt.lower():
            return {
                "content": """第一、算法形式主义的根源与本质（第二章的核心发现）
本研究从认识论的高度指出，算法形式主义根植于现代理性传统中的还原主义思维。这种思维模式试图将复杂的社会现实转化为可计算的数据结构，通过形式化的运算规则来生成决策。然而，这一过程本身就是对现实的简化和扭曲。第二章的深入分析表明，任何算法化过程都不是"纯技术"的，而是必然包含设计者的价值选择、对历史的诠释，以及对未来的想象。

第二、算法形式主义的社会表现与实践后果（第三章的核心发现）
第三章通过司法判罚预测系统、人力资源筛选算法、城市规划推荐系统等多个案例的深入剖析，充分证明了算法形式主义在实际应用中的问题性。这些案例共同指向一个核心现象：算法的应用往往不是消除偏见，而是将制度性的、系统性的不平等"技术化"和"合理化"，使其更难被识别与反抗。更为严重的是，通过将权力决策隐藏在"客观的"算法过程后面，权力关系本身被消隐。

第三、"数字之眼的危机"的理论诊断（第四章的核心发现）
"数字之眼"是一个深刻的隐喻。所谓的"数字之眼"，看似能够通过数据和运算窥视社会的全貌，然而其实质是一种"有限的视野"。这只眼睛只能看到那些可以被量化、被标准化的东西，而对于人的尊严、社会的多元性、伦理的复杂性，它却是盲目的。这种盲目性的危害更在于，当这只"有限的眼睛"获得了权力时——即算法决策被当作最终的仲裁者时——它的盲点就变成了所有相关人的悲剧。第四章通过这一概念有力地揭示了算法形式主义的悖论：越是相信算法的科学性和客观性，我们就越陷入更深的认识误区。

第四、克服危机的多维度路径（第五章的核心提议）
面对以上深刻的理论诊断和实践问题，第五章提出了三条相互支撑的克服路径：

（1）技术设计层面引入情境理性。这意味着在算法设计时，必须明确承认算法的局限性，主动设计"失灵开关"和人工介入机制，使算法成为辅助工具而非终极决策者。

（2）应用实践层面保持人文关怀。这要求在所有涉及重大决策的算法应用中，都必须保留人的判断空间，听取受影响者的声音，将算法的结果视为建议而非指令。

（3）制度建设层面强化算法问责。这涉及建立透明的算法审计制度、可解释的算法设计标准、以及有效的权利救济途径，使算法的权力运行接受民主监督。

第五、研究的局限性与未来方向
本研究的深度虽然揭示了算法形式主义的根本性危机，但也存在一定局限：
- 在技术层面的讨论相对较少，尚需与计算机科学家的深入合作
- 提出的解决方案的具体实施路径需要在广泛的社会实践中检验
- 对于不同文化背景下算法形式主义的差异性表现关注不足

未来研究应当在以下方向深化：
- 开展跨地区、跨文化的比较研究，揭示算法形式主义的相似性与差异性
- 与技术开发者的对话合作，探索在技术层面实现"情境理性"的创新方案
- 对算法治理的实践案例进行长期追踪研究，评估不同政策干预的效果

第六、最后的思考
算法形式主义的危机，归根结底是现代性危机在新时代的一种新的表现形式。它体现了技术理性对人文价值的威胁，权力的隐形化对民主的威胁，形式化思维对社会复杂性的威胁。但值得乐观的是，这一危机的识别本身就蕴含着改变的可能。每一次对算法的批判性反思，每一次人文关怀的坚守，每一次对民主问责的实践，都是在逐步纠正"数字之眼"的焦距，使其逐步适应人类社会的真实需要。本研究希望能够为这一漫长而必要的过程提供理论的支撑和实践的启蒙。"""
            }

        # 其他类型的默认响应
        return {"content": "[Mock response] " + prompt[:100] + "..."}


async def test_full_paper_processing():
    """完整论文处理测试"""
    print("\n" + "=" * 70)
    print("完整论文处理集成测试")
    print("=" * 70)

    # 文件路径
    doc_path = (
        Path(__file__).parent
        / "web"
        / "uploads"
        / "数字之眼的危机^L7算法的形式主义危机(1).docx"
    )
    output_dir = Path(__file__).parent / "workspace" / "documents"

    if not doc_path.exists():
        print(f"❌ 文档不存在: {doc_path}")
        return False

    print(f"\n📄 文档: {doc_path.name}")
    print(f"📁 输出目录: {output_dir}")

    # 用户请求 - 使用用户的原始需求
    user_input = "写一段摘要，300-400字，包含研究背景、方法、结果、结论；重新改善引言，让其与文章主体架构相符；改善结论，overcap整篇文章内容"

    print(f"\n📝 用户请求:")
    print(f"   {user_input}")

    # 创建LLM客户端
    llm_client = RealLLMClient()

    # 创建分析器
    analyzer = IntelligentDocumentAnalyzer(llm_client)

    # 准备输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n⏳ 开始处理...\n")

    try:
        event_list = []

        async for event in analyzer.process_document_revision_streaming(
            str(doc_path), user_input, str(output_dir)
        ):
            event_list.append(event)

            stage = event.get("stage", "unknown")
            progress = event.get("progress", 0)
            message = event.get("message", "")

            # 格式化输出
            status_bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
            print(f"[{status_bar}] {progress:3}% | {stage.upper():15} | {message}")

            if stage == "complete":
                result = event.get("result", {})
                print(f"\n✅ 处理完成！")
                print(f"   输出文件: {result.get('output_file', 'Unknown')}")
                print(f"   任务数: {result.get('tasks_completed', 0)}")
                print(f"   修订部分: {', '.join(result.get('revisions', []))}")

        return True

    except Exception as e:
        print(f"\n❌ 处理失败: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """主函数"""
    print("\n" + "=" * 70)
    print("智能文档分析引擎 - 完整集成测试")
    print("=" * 70)

    result = await test_full_paper_processing()

    print("\n" + "=" * 70)
    if result:
        print("✅ 处理成功！")
        print("\n下一步：在Koto中上传Word文档并使用相同的请求进行真实测试")
    else:
        print("❌ 处理失败")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
