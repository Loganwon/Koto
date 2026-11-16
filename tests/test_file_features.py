#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
文件编辑与搜索功能测试
"""

import os
import sys

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from web.files.file_editor import FileEditor


def test_file_editor():
    """测试文件编辑器"""
    print("=" * 60)
    print("📝 文件编辑器测试")
    print("=" * 60)

    editor = FileEditor()
    test_file = os.path.join(editor.workspace_dir, "test_edit_demo.txt")

    # 1. 创建测试文件
    print("\n1️⃣ 创建测试文件...")
    content = """# 配置文件
version = 1.0
debug = True
timeout = 30
server_url = http://localhost:8080
"""
    editor.write_file(test_file, content, create_backup=False)
    print(f"✅ 已创建: {test_file}")
    print(f"内容:\n{content}")

    # 2. 测试替换
    print("\n2️⃣ 测试文本替换: 把 'True' 改成 'False'")
    result = editor.replace_text(test_file, "True", "False")
    print(f"✅ 替换 {result.get('replacements')} 处")
    print(f"预览: {result.get('preview')}")

    # 3. 测试插入
    print("\n3️⃣ 测试插入行: 在第 3 行之后插入 'port = 9000'")
    result = editor.insert_line(test_file, 3, "port = 9000", mode="after")
    print(f"✅ {result.get('message')}")

    # 4. 测试智能编辑
    print("\n4️⃣ 测试智能编辑: '把 timeout 改成 60'")
    result = editor.smart_edit(test_file, "把 'timeout = 30' 改成 'timeout = 60'")
    if result.get("success"):
        op_result = result.get("result", {})
        print(
            f"✅ 操作: {result.get('operation')}, 替换 {op_result.get('replacements')} 处"
        )
    else:
        print(f"❌ {result.get('error')}")

    # 5. 显示最终内容
    print("\n5️⃣ 最终文件内容:")
    result = editor.read_file(test_file)
    if result["success"]:
        print(f"```\n{result['content']}\n```")

    # 6. 显示备份文件
    backups = list(editor.backup_dir.glob("*.bak"))
    if backups:
        print(f"\n💾 备份文件数: {len(backups)}")
        for b in backups[:3]:
            print(f"   - {b.name}")

    print()


def main():
    """主函数"""
    print("\n" + "🚀" * 30)
    print("Koto 文件编辑与搜索功能测试")
    print("🚀" * 30 + "\n")

    try:
        # 测试文件编辑
        test_file_editor()

        print("\n" + "✅" * 30)
        print("所有测试完成！")
        print("✅" * 30 + "\n")

        print("💡 使用方法:")
        print("   1. 修改文件: \"修改 文件路径 把'旧文本'改成'新文本'\"")
        print("   2. 文件搜索与问答由统一 RAG 索引提供")
        print()

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
