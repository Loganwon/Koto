#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Koto PPT 功能快速测试脚本
用于验证 P0（文件上传）+ P1（编辑）功能是否正常工作

运行方式：
python tests/test_ppt_features.py
"""

import json
import os
import sys
import tempfile

# 确保 web 模块可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_file_parser():
    """测试文件解析器"""
    print("\n" + "=" * 60)
    print("测试 1: 文件解析器 (FileParser)")
    print("=" * 60)

    try:
        from web.file_parser import FileParser

        print("✅ FileParser 导入成功")

        # 测试 TXT 文件（使用临时目录）
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("这是一个测试文件\n包含多行内容\n")
            test_txt = f.name

        try:
            result = FileParser.parse_file(test_txt)
            assert result["success"], "TXT 解析失败"
            assert "测试文件" in result["content"], "内容提取失败"
            print("✅ TXT 文件解析成功")
        finally:
            os.remove(test_txt)

    except Exception as e:
        print(f"❌ FileParser 测试失败: {e}")
        return False

    return True


def test_ppt_session_manager():
    """测试 PPT 会话管理器"""
    print("\n" + "=" * 60)
    print("测试 2: PPT 会话管理器 (PPTSessionManager)")
    print("=" * 60)

    try:
        from web.ppt_session_manager import get_ppt_session_manager

        print("✅ PPTSessionManager 导入成功")

        mgr = get_ppt_session_manager()

        # 创建会话
        session_id = mgr.create_session(
            title="测试 PPT", user_input="生成关于人工智能的 PPT", theme="business"
        )
        print(f"✅ 创建会话成功: {session_id}")

        # 加载会话
        session = mgr.load_session(session_id)
        assert session is not None, "会话加载失败"
        assert session["title"] == "测试 PPT", "会话标题不匹配"
        print("✅ 会话加载成功")

        # 保存 PPT 数据
        test_ppt_data = {
            "title": "AI 基础",
            "subtitle": "",
            "slides": [
                {
                    "title": "什么是人工智能",
                    "type": "detail",
                    "points": ["机器学习", "深度学习"],
                    "content": ["机器学习", "深度学习"],
                },
                {
                    "title": "AI 应用",
                    "type": "overview",
                    "subsections": [
                        {"subtitle": "医疗", "points": ["诊断", "治疗"]},
                        {"subtitle": "交通", "points": ["自动驾驶"]},
                    ],
                },
            ],
        }

        success = mgr.save_generation_data(
            session_id=session_id,
            ppt_data=test_ppt_data,
            ppt_file_path="/tmp/test.pptx",
            search_context="搜索结果...",
            research_context="研究内容...",
        )
        assert success, "数据保存失败"
        print("✅ PPT 数据保存成功")

        # 加载并验证
        session = mgr.load_session(session_id)
        assert session["ppt_file_path"] == "/tmp/test.pptx", "文件路径不匹配"
        print("✅ 数据验证成功")

        # 更新幻灯片
        success = mgr.update_slide(
            session_id,
            0,
            {
                "title": "什么是现代 AI",
                "points": ["深度学习", "大语言模型", "多模态 AI"],
            },
        )
        assert success, "幻灯片更新失败"
        print("✅ 幻灯片更新成功")

        # 列表会话
        sessions = mgr.list_sessions(limit=5)
        assert len(sessions) > 0, "会话列表为空"
        print(f"✅ 会话列表获取成功（共 {len(sessions)} 个）")

    except Exception as e:
        print(f"❌ PPTSessionManager 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False

    return True


def test_ppt_api_routes():
    """测试 PPT API 路由"""
    print("\n" + "=" * 60)
    print("测试 3: PPT API 路由 (ppt_api_routes)")
    print("=" * 60)

    try:
        from flask import Blueprint

        from web.ppt_api_routes import ppt_api_bp

        print("✅ ppt_api_bp 蓝图导入成功")

        # 验证是 Flask Blueprint 对象
        assert isinstance(ppt_api_bp, Blueprint), "ppt_api_bp 不是 Flask Blueprint"
        assert ppt_api_bp.name == "ppt_api", "蓝图名称不正确"
        assert ppt_api_bp.url_prefix == "/api/ppt", "蓝图路由前缀不正确"
        print(f"✅ 蓝图配置正确（path: {ppt_api_bp.url_prefix}）")

    except Exception as e:
        print(f"❌ PPT API 路由测试失败: {e}")
        return False

    return True


def test_html_template():
    """测试 HTML 编辑模板"""
    print("\n" + "=" * 60)
    print("测试 4: HTML 编辑模板")
    print("=" * 60)

    try:
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "web", "templates", "edit_ppt.html"
        )

        assert os.path.exists(template_path), f"模板文件不存在: {template_path}"
        print(f"✅ 模板文件存在: {template_path}")

        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "edit-ppt" in content, "模板内容异常"
            assert "api/ppt" in content, "API 路由集成异常"

        print("✅ 模板内容验证成功")

    except Exception as e:
        print(f"❌ HTML 模板测试失败: {e}")
        return False

    return True


def test_integration():
    """集成测试"""
    print("\n" + "=" * 60)
    print("测试 5: 集成测试（模拟完整流程）")
    print("=" * 60)

    test_file = None
    try:
        from web.file_parser import FileParser
        from web.ppt_session_manager import get_ppt_session_manager

        # 步骤 1: 创建临时文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("这是一份关于 AI 的研究报告\n内容包括深度学习和自然语言处理\n")
            test_file = f.name

        # 步骤 2: 解析文件
        parse_result = FileParser.parse_file(test_file)
        assert parse_result["success"], "文件解析失败"
        file_content = parse_result["content"]
        print(f"✅ 步骤 1: 文件解析成功 ({len(file_content)} 字符)")

        # 步骤 3: 创建会话
        mgr = get_ppt_session_manager()
        session_id = mgr.create_session(
            title="集成测试 PPT", user_input="基于上传文件生成 PPT", theme="tech"
        )
        print(f"✅ 步骤 2: 会话创建成功 ({session_id})")

        # 步骤 4: 保存包含文件内容的 PPT 数据
        ppt_data = {
            "title": "AI 研究综述",
            "slides": [
                {
                    "title": "简介",
                    "type": "detail",
                    "points": ["基于上传文件: 深度学习和自然语言处理"],
                    "content": ["基于上传文件: 深度学习和自然语言处理"],
                }
            ],
        }

        mgr.save_generation_data(
            session_id=session_id,
            ppt_data=ppt_data,
            ppt_file_path="/tmp/test_integrated.pptx",
            uploaded_file_context=file_content,
        )
        print(f"✅ 步骤 3: 数据保存成功（含文件内容）")

        # 步骤 5: 验证数据完整性
        session = mgr.load_session(session_id)
        assert session["uploaded_file_context"] == file_content, "文件内容丢失"
        assert len(session["ppt_data"]["slides"]) > 0, "幻灯片数据缺失"
        print(f"✅ 步骤 4: 数据完整性验证成功")

        print("\n✅ 集成测试通过！文件上传 + 会话管理 + 编辑流程正常")

    except Exception as e:
        print(f"❌ 集成测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        # 清理
        if test_file and os.path.exists(test_file):
            os.remove(test_file)

    return True


def main():
    """运行所有测试"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 15 + "Koto PPT 功能测试套件" + " " * 22 + "║")
    print("╠" + "=" * 58 + "╣")
    print("║  测试项目：P0（文件上传）+ P1（编辑）核心功能" + " " * 17 + "║")
    print("╚" + "=" * 58 + "╝")

    results = {
        "文件解析器": test_file_parser(),
        "会话管理": test_ppt_session_manager(),
        "API 路由": test_ppt_api_routes(),
        "HTML 模板": test_html_template(),
        "集成测试": test_integration(),
    }

    print("\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)

    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}  {name}")

    total = len(results)
    passed = sum(1 for r in results.values() if r)

    print("=" * 60)
    print(f"总体: {passed}/{total} 项测试通过")

    if passed == total:
        print("\n🎉 所有测试通过！P0 + P1 功能已就绪")
        print("\n下一步:")
        print("1. 在聊天界面中上传文件生成 PPT")
        print("2. 点击生成的 PPT 下方的编辑链接")
        print("3. 在编辑器中修改内容、删除/添加幻灯片、AI 重新生成")
        print("4. 保存并下载最终 PPT")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项测试失败，请检查上面的错误信息")
        return 1


if __name__ == "__main__":
    sys.exit(main())
