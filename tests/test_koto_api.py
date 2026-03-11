#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试Koto智能文档分析引擎的API调用
Test Koto Intelligent Document Analyzer via API
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

# Koto服务URL
KOTO_URL = "http://localhost:5000"
API_UPLOAD = f"{KOTO_URL}/api/chat/file"

# 论文文件路径
PAPER_PATH = (
    Path(__file__).parent
    / "web"
    / "uploads"
    / "数字之眼的危机^L7算法的形式主义危机(1).docx"
)

# 用户请求
USER_REQUEST = """写一段摘要：论文摘要通常遵循一定的结构，常见的模板如下（控制在300-400字左右。）：
1.研究背景与目的：简要介绍研究领域的背景，阐述研究的目的和意义。
2.研究方法：描述研究采用的方法论，分析方法等。
3.研究结果：概括研究的主要发现，突出创新点。
4.研究结论：总结研究的主要贡献，指出研究的局限性和未来研究方向。

重新改善引言，因为目前的引言和文章主体架构不符合了。

目前的结论我也不是特别满意，因为没有overcap整篇文章的内容。改善一下。"""


def test_koto_intelligent_analyzer():
    """测试Koto智能文档分析引擎"""
    print("=" * 70)
    print("Koto 智能文档分析引擎 - API测试")
    print("=" * 70)

    # 检查文件
    if not PAPER_PATH.exists():
        print(f"❌ 论文文件不存在: {PAPER_PATH}")
        return False

    print(f"\n📄 论文文件: {PAPER_PATH.name}")
    print(f"📝 用户请求:\n{USER_REQUEST}\n")

    # 检查Koto服务
    print("⏳ 检查Koto服务状态...")
    try:
        response = requests.get(f"{KOTO_URL}/api/chat", timeout=5)
        print(f"✅ Koto服务在线")
    except Exception as e:
        print(f"❌ Koto服务离线: {str(e)}")
        print("   请确保Koto已启动: python koto_app.py")
        return False

    # 上传文件并执行请求
    print("\n📤 上传文件并执行请求...\n")

    try:
        with open(PAPER_PATH, "rb") as f:
            files = {
                "file": (
                    PAPER_PATH.name,
                    f,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            }
            data = {
                "message": USER_REQUEST,  # 使用 'message' 而不是 'user_input'
                "session": "test_intelligent_analyzer",  # 使用 'session' 而不是 'session_name'
            }

            # 发送请求
            print(f"📡 请求URL: {API_UPLOAD}")
            print(f"   session: {data['session']}")
            print(f"   message: {data['message'][:50]}...")
            print(f"   file: {PAPER_PATH.name}")
            print()

            response = requests.post(
                API_UPLOAD,
                files=files,
                data=data,
                stream=True,  # 流式响应
                timeout=300,  # 5分钟超时
            )

            print(f"📡 服务器响应状态: {response.status_code}\n")

            if response.status_code != 200:
                print(f"❌ 请求失败: {response.text}")
                return False

            # 处理流式响应
            print("🔄 处理中...\n")
            event_count = 0

            for line in response.iter_lines():
                if not line:
                    continue

                line_str = line.decode("utf-8") if isinstance(line, bytes) else line

                # 处理SSE事件
                if line_str.startswith("data: "):
                    try:
                        event_json = line_str[6:]  # 删除 "data: " 前缀
                        event = json.loads(event_json)
                        event_count += 1

                        stage = event.get("stage", "unknown")
                        progress = event.get("progress", 0)
                        message = event.get("message", "")

                        # 显示进度
                        bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
                        print(f"[{bar}] {progress:3}% | {stage.upper():15} | {message}")

                        # 处理完成事件
                        if stage == "complete":
                            result = event.get("result", {})
                            print(f"\n✅ 处理完成！")
                            print(
                                f"   输出文件: {result.get('output_file', 'Unknown')}"
                            )
                            print(f"   任务数: {result.get('tasks_completed', 0)}")
                            print(
                                f"   修订部分: {', '.join(result.get('revisions', []))}"
                            )
                            return True

                        # 处理错误事件
                        if stage == "error":
                            print(f"\n❌ 处理错误: {message}")
                            return False

                    except json.JSONDecodeError:
                        print(f"⚠️  无法解析JSON: {event_json[:100]}")
                        continue

            print(f"\n✅ 流式处理完成，共 {event_count} 个事件")
            return True

    except requests.exceptions.Timeout:
        print("❌ 请求超时（>5分钟），可能文档过大或LLM响应慢")
        return False
    except Exception as e:
        print(f"❌ 请求异常: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """主函数"""
    print("\n")
    success = test_koto_intelligent_analyzer()

    print("\n" + "=" * 70)
    if success:
        print("🎉 测试成功！智能文档分析引擎工作正常。")
        print("\n下一步：检查输出文件")
        print("位置: workspace/documents/")
    else:
        print("❌ 测试失败，请检查上方错误信息")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
