#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键测试脚本 - 验证触发器参数编辑功能
运行此脚本以验证所有功能是否正常工作
"""

import subprocess
import sys
from pathlib import Path


def print_header(title):
    """打印标题"""
    print("\n")
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)
    print()


def run_test(script_name, description):
    """运行测试脚本"""
    print(f"\n🧪 运行: {description}")
    print(f"   脚本: {script_name}")
    print("-" * 80)

    try:
        result = subprocess.run(
            [sys.executable, script_name],
            capture_output=False,
            cwd=Path(__file__).parent,
        )

        if result.returncode == 0:
            print(f"\n✅ {description} - 成功\n")
            return True
        else:
            print(f"\n❌ {description} - 失败 (错误码: {result.returncode})\n")
            return False

    except Exception as e:
        print(f"\n❌ 无法运行 {description}: {e}\n")
        return False


def main():
    """主程序"""
    print_header("Koto 触发器参数编辑功能 - 完整验证套件")

    print("""
本脚本将运行以下测试:

    1. 基础功能测试 (test_trigger_params.py)
       ⏱️  耗时: ~5 秒
       📝 内容: 参数 CRUD、持久化、类型识别
    
    2. 集成测试 (test_trigger_params_integration.py)
       ⏱️  耗时: ~10 秒
       📝 内容: 跨模块数据流、API、数据库
    
    3. 最终报告生成 (TRIGGER_IMPLEMENTATION_FINAL_REPORT.py)
       ⏱️  耗时: ~2 秒
       📝 内容: 完整的功能总结报告

总耗时: 约 20-30 秒

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """)

    results = {}

    # 1. 基础功能测试
    results["basic"] = run_test("test_trigger_params.py", "基础功能测试")

    # 2. 集成测试
    results["integration"] = run_test("test_trigger_params_integration.py", "集成测试")

    # 3. 最终报告
    print_header("最终实现报告")
    print("生成完整的实现总结报告...\n")
    run_test("TRIGGER_IMPLEMENTATION_FINAL_REPORT.py", "最终报告")

    # 总结结果
    print_header("测试总结")

    print("测试结果:")
    print(f"  {'基础功能测试':<30} {'✅ 通过' if results['basic'] else '❌ 失败'}")
    print(f"  {'集成测试':<30} {'✅ 通过' if results['integration'] else '❌ 失败'}")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"\n{'总计':<30} {passed}/{total} 测试通过")

    if passed == total:
        print("""
        ╔════════════════════════════════════════════════════════════╗
        ║                                                            ║
        ║   🎉 所有测试通过！功能已准备好。                        ║
        ║                                                            ║
        ║   ✅ 参数编辑功能正常运行                                 ║
        ║   ✅ 数据库持久化测试通过                                 ║
        ║   ✅ API 接口调用正常                                     ║
        ║   ✅ 触发条件函数参数绑定正确                             ║
        ║                                                            ║
        ║   现在可以在 Koto 应用中使用此功能了！                    ║
        ║   点击"🧭 触发器"开始编辑你的触发器参数吧！             ║
        ║                                                            ║
        ╚════════════════════════════════════════════════════════════╝
        """)
    else:
        print(f"""
        ⚠️  有 {total - passed} 个测试失败
        
        请检查:
        1. Python 版本 (需要 3.7+)
        2. 数据库连接
        3. 所有必要的文件是否存在
        4. 查看详细错误日志
        
        需要帮助? 参考 TRIGGER_DOCUMENTATION_INDEX.md
        """)
        sys.exit(1)

    print("\n" + "=" * 80)
    print("后续步骤:")
    print("=" * 80)
    print("""
    1. 查看文档
       📖 用户指南: docs/TRIGGER_USER_GUIDE.md
       📖 快速参考: docs/TRIGGER_QUICK_REFERENCE.md
       📖 技术文档: docs/TRIGGER_PARAMETERS_GUIDE.md
    
    2. 打开应用并测试
       🚀 启动 Koto 应用
       🎯 点击"🧭 触发器"打开面板
       ⚙️  修改一个参数，点击保存测试
    
    3. 阅读部署信息
       📋 部署清单: DEPLOYMENT_CHECKLIST.py
       🔄 变更日志: TRIGGER_CHANGELOG.md
       ✅ 完成总结: TRIGGER_COMPLETION_SUMMARY.md
    
    4. 联系支持
       如有问题，查看文档或参考相关文件中的联系方式
    """)
    print("=" * 80)
    print("\n✨ 测试完成！祝你使用愉快！\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}\n")
        import traceback

        traceback.print_exc()
        sys.exit(1)
