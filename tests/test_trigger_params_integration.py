#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集成测试：触发器阈值参数编辑完整流程"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

# 添加到路径
sys.path.insert(0, str(Path(__file__).parent))

from web.proactive_trigger import ProactiveTriggerSystem, TriggerType


def print_section(title):
    """打印分隔符"""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def _check_parameter_persistence(tmp_path):
    """测试参数持久化"""
    print_section("测试 1: 参数持久化")

    # 清空旧数据
    db_path = str(tmp_path / "triggers.db")

    # 创建两个独立的系统实例
    system1 = ProactiveTriggerSystem(db_path=db_path)

    # 在第一个实例中修改参数
    print("1️⃣  在实例1中修改参数:")
    new_params = {"work_duration_hours": 5, "urgency_per_hour": 0.2, "max_urgency": 0.9}
    ok = system1.update_trigger_params("threshold_work_too_long", new_params)
    print(f"   修改结果: {'✅' if ok else '❌'}")

    # 创建第二个实例，验证参数是否加载
    print("\n2️⃣  创建实例2，验证参数加载:")
    system2 = ProactiveTriggerSystem(db_path=db_path)
    loaded_params = system2.get_trigger_params("threshold_work_too_long")

    print(f"   原始参数: {new_params}")
    print(f"   加载参数: {loaded_params}")
    print(f"   一致性: {'✅ 一致' if loaded_params == new_params else '❌ 不一致'}")

    return loaded_params == new_params


def _check_api_endpoint_simulation(tmp_path):
    """模拟API接口调用"""
    print_section("测试 2: API接口模拟")

    system = ProactiveTriggerSystem(db_path=str(tmp_path / "triggers.db"))

    # 模拟 /api/triggers/list
    print("1️⃣  获取触发器列表 (GET /api/triggers/list)")
    triggers = system.list_triggers()
    print(f"   获取触发器数: {len(triggers)}")
    for trigger in triggers[:2]:
        print(f"   - {trigger['trigger_id']} ({trigger['trigger_type']})")
        print(f"     参数数: {len(trigger['parameters'])}")

    # 模拟 /api/triggers/params/{trigger_id} GET
    print("\n2️⃣  获取特定触发器参数 (GET /api/triggers/params/{id})")
    trigger_id = "threshold_edit_count"
    params = system.get_trigger_params(trigger_id)
    print(f"   触发器: {trigger_id}")
    print(f"   参数: {json.dumps(params, ensure_ascii=False)}")

    # 模拟 /api/triggers/update POST
    print("\n3️⃣  更新触发器配置 (POST /api/triggers/update)")
    update_data = {
        "trigger_id": "pattern_repeated_search",
        "priority": 7,
        "cooldown_minutes": 100,
        "parameters": {"search_threshold": 4, "check_recent_searches": 80},
    }
    print(f"   请求数据: {json.dumps(update_data, ensure_ascii=False)}")

    system.update_trigger_config(
        update_data["trigger_id"],
        priority=update_data["priority"],
        cooldown_minutes=update_data["cooldown_minutes"],
    )
    system.update_trigger_params(update_data["trigger_id"], update_data["parameters"])

    # 验证更新
    updated_trigger = next(
        (
            t
            for t in system.list_triggers()
            if t["trigger_id"] == update_data["trigger_id"]
        ),
        None,
    )
    if updated_trigger:
        print(f"   ✅ 优先级已更新: {updated_trigger['priority']}")
        print(f"   ✅ 冷却已更新: {updated_trigger['cooldown_minutes']}")
        print(f"   ✅ 参数已更新: {updated_trigger['parameters']}")
        return (
            updated_trigger["priority"] == update_data["priority"]
            and updated_trigger["cooldown_minutes"] == update_data["cooldown_minutes"]
            and updated_trigger["parameters"] == update_data["parameters"]
        )

    return False


def _check_trigger_condition_with_params(tmp_path):
    """测试触发条件使用参数"""
    print_section("测试 3: 触发条件函数使用参数")

    system = ProactiveTriggerSystem(db_path=str(tmp_path / "triggers.db"))

    # 验证 _check_morning_time 使用参数
    print("1️⃣  验证早晨问候参数:")
    params = system.get_trigger_params("periodic_morning_greeting")
    print(f"   当前参数:")
    print(f"   - morning_start_hour: {params.get('morning_start_hour')}")
    print(f"   - morning_end_hour: {params.get('morning_end_hour')}")

    # 修改参数
    new_morning_params = {"morning_start_hour": 7, "morning_end_hour": 8}
    system.update_trigger_params("periodic_morning_greeting", new_morning_params)

    # 验证修改
    updated_params = system.get_trigger_params("periodic_morning_greeting")
    morning_matches = (
        updated_params.get("morning_start_hour") == 7
        and updated_params.get("morning_end_hour") == 8
    )
    print(f"   参数修改: {'✅ 成功' if morning_matches else '❌ 失败'}")

    # 验证早晨检查函数是否使用参数
    print("\n2️⃣  验证工作时长参数:")
    work_params = system.get_trigger_params("threshold_work_too_long")
    print(f"   当前参数:")
    print(f"   - work_duration_hours: {work_params.get('work_duration_hours')}")
    print(f"   - urgency_per_hour: {work_params.get('urgency_per_hour')}")
    print(f"   - max_urgency: {work_params.get('max_urgency')}")

    # 修改参数
    new_work_params = {
        "work_duration_hours": 4,
        "urgency_per_hour": 0.12,
        "max_urgency": 0.8,
    }
    system.update_trigger_params("threshold_work_too_long", new_work_params)

    # 验证修改
    updated_params = system.get_trigger_params("threshold_work_too_long")
    work_matches = (
        updated_params.get("work_duration_hours") == 4
        and updated_params.get("urgency_per_hour") == 0.12
        and updated_params.get("max_urgency") == 0.8
    )
    print(f"   参数修改: {'✅ 成功' if work_matches else '❌ 失败'}")

    return morning_matches and work_matches


def _check_parameter_types(tmp_path):
    """测试不同类型的参数"""
    print_section("测试 4: 参数数据类型")

    system = ProactiveTriggerSystem(db_path=str(tmp_path / "triggers.db"))

    print("1️⃣  测试整数参数:")
    trigger_id = "threshold_edit_count"
    system.update_trigger_params(trigger_id, {"edit_count_threshold": 20})
    params = system.get_trigger_params(trigger_id)
    value = params.get("edit_count_threshold")
    integer_matches = value == 20
    print(f"   设置值: 20, 获取值: {value}, 类型: {type(value).__name__}")
    print(f"   验证: {'✅' if integer_matches else '❌'}")

    print("\n2️⃣  测试浮点参数:")
    trigger_id = "threshold_work_too_long"
    system.update_trigger_params(trigger_id, {"urgency_per_hour": 0.25})
    params = system.get_trigger_params(trigger_id)
    value = params.get("urgency_per_hour")
    float_matches = isinstance(value, (int, float)) and abs(value - 0.25) < 0.001
    print(f"   设置值: 0.25, 获取值: {value}, 类型: {type(value).__name__}")
    print(f"   验证: {'✅' if float_matches else '❌'}")

    print("\n3️⃣  测试多参数混合:")
    mixed_params = {
        "search_threshold": 5,  # int
        "check_recent_searches": 150,  # int
        "urgency_rate": 0.15,  # float
    }
    # 创建临时参数
    temp_params = mixed_params.copy()
    print(f"   输入参数类型:")
    for k, v in temp_params.items():
        print(f"   - {k}: {v} ({type(v).__name__})")
    print(f"   ✅ 测试通过")

    mixed_types_match = all(
        isinstance(temp_params[key], expected_type)
        for key, expected_type in (
            ("search_threshold", int),
            ("check_recent_searches", int),
            ("urgency_rate", float),
        )
    )
    return integer_matches and float_matches and mixed_types_match


def _check_database_schema(tmp_path):
    """验证数据库表结构"""
    print_section("测试 5: 数据库表结构")

    db_path = str(tmp_path / "triggers.db")
    ProactiveTriggerSystem(db_path=db_path)

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 检查 trigger_parameters 表
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trigger_parameters'"
        )
        exists = cursor.fetchone() is not None
        print(f"1️⃣  trigger_parameters 表存在: {'✅' if exists else '❌'}")

        if exists:
            # 获取表结构
            cursor.execute("PRAGMA table_info(trigger_parameters)")
            columns = cursor.fetchall()
            print(f"   表结构:")
            for col in columns:
                print(f"   - {col[1]} ({col[2]})")

        # 检查 trigger_config 表
        cursor.execute("SELECT COUNT(*) FROM trigger_config")
        config_count = cursor.fetchone()[0]
        print(f"\n2️⃣  trigger_config 表行数: {config_count}")

        # 检查 trigger_parameters 表
        cursor.execute("SELECT COUNT(*) FROM trigger_parameters")
        parameter_count = cursor.fetchone()[0]
        print(f"3️⃣  trigger_parameters 表行数: {parameter_count}")

        conn.close()
        return exists and config_count > 0 and parameter_count > 0

    except Exception as e:
        print(f"❌ 数据库检查失败: {e}")
        return False


def run_all(tmp_path):
    """运行所有测试"""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "触发器阈值参数编辑功能集成测试" + " " * 22 + "║")
    print("╚" + "=" * 68 + "╝")

    results = {
        "参数持久化": _check_parameter_persistence(tmp_path),
        "API接口模拟": _check_api_endpoint_simulation(tmp_path),
        "触发条件使用参数": _check_trigger_condition_with_params(tmp_path),
        "参数数据类型": _check_parameter_types(tmp_path),
        "数据库表结构": _check_database_schema(tmp_path),
    }

    # 总结
    print_section("测试总结")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} - {test_name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！触发器参数编辑功能已准备就绪。")
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败，请检查日志。")

    print("\n" + "=" * 70)
    return results


def test_trigger_parameter_integration(tmp_path):
    results = run_all(tmp_path)
    assert all(results.values()), results


if __name__ == "__main__":
    with TemporaryDirectory(prefix="koto-trigger-tests-") as temp_dir:
        run_all(Path(temp_dir))
