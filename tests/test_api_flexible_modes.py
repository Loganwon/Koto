#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
测试新灵活输出模式的实际API行为
验证系统不再被锁定在一种模式中
"""

import json
import os
import time

import requests

# Koto API配置
API_BASE = "http://127.0.0.1:5000"
TEST_PAPER = r"c:\Users\12524\Desktop\Koto\workspace\documents\数字之眼的危机^L7算法的形式主义危机(1).docx"


def test_flexible_output_modes():
    """测试灵活输出模式"""

    print("=" * 80)
    print("🎯 Koto 灵活输出模式 - API端到端测试")
    print("=" * 80)
    print()

    # 确保文件存在
    if not os.path.exists(TEST_PAPER):
        print(f"❌ 测试文件不存在: {TEST_PAPER}")
        print("   请确保论文文件在workspace/documents目录中")
        return False

    print(f"📄 使用论文: {os.path.basename(TEST_PAPER)}")
    print()

    test_cases = [
        {
            "name": "生成摘要",
            "request": "写一段摘要：三段，300字左右",
            "expected_output": "generated_texts",
            "description": "应该返回摘要文本，不修改原文档",
        },
        {
            "name": "改善结论",
            "request": "重新改善结论，要求总结全文内容",
            "expected_output": "generated_texts",
            "description": "应该返回改进的结论文本",
        },
        {
            "name": "分析论文",
            "request": "分析这篇论文的结构",
            "expected_output": "analysis_results",
            "description": "应该返回分析结果",
        },
    ]

    results = []

    for test in test_cases:
        print(f"[测试] {test['name']}")
        print(f"  请求: {test['request'][:50]}...")
        print(f"  预期: 输出类型 = {test['expected_output']}")
        print()

        try:
            # 上传文件并进行智能分析
            with open(TEST_PAPER, "rb") as f:
                files = {
                    "file": (
                        os.path.basename(TEST_PAPER),
                        f,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                }
                data = {"message": test["request"], "session": "test_session"}

                response = requests.post(
                    f"{API_BASE}/api/chat/file",
                    files=files,
                    data=data,
                    stream=True,
                    timeout=30,
                )

            if response.status_code != 200:
                print(f"  ❌ HTTP错误: {response.status_code}")
                results.append(
                    {
                        "test": test["name"],
                        "success": False,
                        "error": f"HTTP {response.status_code}",
                    }
                )
                print()
                continue

            # 解析SSE流
            events = []
            try:
                for line in response.iter_lines():
                    if not line:
                        continue

                    line = line.decode("utf-8") if isinstance(line, bytes) else line

                    if line.startswith("data: "):
                        try:
                            data_json = json.loads(line[6:])
                            events.append(data_json)
                        except json.JSONDecodeError:
                            pass

                # 查找完成事件
                complete_event = None
                for event in events:
                    if event.get("stage") == "complete":
                        complete_event = event
                        break

                if complete_event and "result" in complete_event:
                    output_type = complete_event["result"].get("output_type")

                    if output_type == test["expected_output"]:
                        print(f"  ✅ 成功! 正确返回 {output_type}")
                        results.append(
                            {
                                "test": test["name"],
                                "success": True,
                                "output_type": output_type,
                            }
                        )
                    else:
                        print(f"  ⚠️  输出类型不符")
                        print(f"     期望: {test['expected_output']}")
                        print(f"     实际: {output_type}")
                        results.append(
                            {
                                "test": test["name"],
                                "success": False,
                                "error": f"输出类型不符: {output_type}",
                            }
                        )
                elif complete_event:
                    print(f"  ❌ 完成事件无结果字段")
                    results.append(
                        {"test": test["name"], "success": False, "error": "无结果"}
                    )
                else:
                    print(f"  ❌ 未收到完成事件")
                    print(f"     收到{len(events)}个事件")
                    results.append(
                        {"test": test["name"], "success": False, "error": "无完成事件"}
                    )

            except Exception as e:
                print(f"  ❌ 解析响应失败: {str(e)}")
                results.append(
                    {"test": test["name"], "success": False, "error": str(e)}
                )

        except Exception as e:
            print(f"  ❌ 请求失败: {str(e)}")
            results.append({"test": test["name"], "success": False, "error": str(e)})

        print()
        time.sleep(2)  # 避免连续请求太快

    # 显示总结
    print("=" * 80)
    print("📊 测试结果总结")
    print("=" * 80)

    passed = sum(1 for r in results if r["success"])
    total = len(results)

    for result in results:
        status = "✅" if result["success"] else "❌"
        print(
            f"{status} {result['test']}: {result.get('output_type', result.get('error', '未知'))}"
        )

    print()
    print(f"通过: {passed}/{total}")
    print()

    if passed == total:
        print("🎉 所有测试通过！系统成功实现灵活输出模式")
        print()
        print("关键改进:")
        print("✨ 系统不再被锁定在单一模式")
        print("✨ 不同的请求得到不同的输出格式")
        print("✨ '生成摘要' -> 返回摘要文本 (不是修改文档)")
        print("✨ '改善结论' -> 返回结论文本 (不是修改文档)")
        print("✨ '分析' -> 返回分析结果")
        return True
    else:
        print(f"⚠️  {total - passed} 个测试失败")
        return False


if __name__ == "__main__":
    success = test_flexible_output_modes()
    exit(0 if success else 1)
