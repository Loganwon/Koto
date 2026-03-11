#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试触发器参数编辑功能"""

import json
import sys
from pathlib import Path

# 添加到路径
sys.path.insert(0, str(Path(__file__).parent))

from web.proactive_trigger import ProactiveTriggerSystem


def test_trigger_params():
    """测试触发器参数管理"""
    print("=" * 60)
    print("测试触发器参数编辑功能")
    print("=" * 60)

    # 初始化系统
    system = ProactiveTriggerSystem()

    # 1. 列出所有触发器及其参数
    print("\n1️⃣  初始触发器列表:")
    triggers = system.list_triggers()
    for trigger in triggers[:3]:  # 只显示前3个
        print(f"\n  触发器: {trigger['trigger_id']}")
        print(f"  类型: {trigger['trigger_type']}")
        print(f"  启用: {trigger['enabled']}")
        print(f"  优先级: {trigger['priority']}")
        print(f"  冷却: {trigger['cooldown_minutes']} 分钟")
        print(
            f"  参数: {json.dumps(trigger['parameters'], ensure_ascii=False, indent=4)}"
        )

    # 2. 获取特定触发器参数
    print("\n2️⃣  获取工作时长触发器参数:")
    work_params = system.get_trigger_params("threshold_work_too_long")
    print(f"  当前参数:\n{json.dumps(work_params, ensure_ascii=False, indent=4)}")

    # 3. 更新触发器参数
    print("\n3️⃣  更新工作时长触发器参数:")
    new_params = {
        "work_duration_hours": 3,  # 改为3小时
        "urgency_per_hour": 0.15,  # 增加紧急度递增率
        "max_urgency": 0.95,
    }
    ok = system.update_trigger_params("threshold_work_too_long", new_params)
    print(f"  更新结果: {'✅ 成功' if ok else '❌ 失败'}")

    if ok:
        updated_params = system.get_trigger_params("threshold_work_too_long")
        print(
            f"  更新后参数:\n{json.dumps(updated_params, ensure_ascii=False, indent=4)}"
        )

    # 4. 更新编辑次数阈值
    print("\n4️⃣  更新编辑次数触发器参数:")
    edit_params = {"edit_count_threshold": 15, "check_recent_events": 150}  # 改为15次
    ok = system.update_trigger_params("threshold_edit_count", edit_params)
    print(f"  更新结果: {'✅ 成功' if ok else '❌ 失败'}")

    # 5. 更新搜索阈值
    print("\n5️⃣  更新搜索模式触发器参数:")
    search_params = {
        "search_threshold": 5,  # 改为5次搜索才触发
        "check_recent_searches": 100,
    }
    ok = system.update_trigger_params("pattern_repeated_search", search_params)
    print(f"  更新结果: {'✅ 成功' if ok else '❌ 失败'}")

    # 6. 更新时间参数
    print("\n6️⃣  更新早晨问候触发器参数:")
    morning_params = {
        "morning_start_hour": 7,  # 改为7点
        "morning_end_hour": 9,  # 改为9点
    }
    ok = system.update_trigger_params("periodic_morning_greeting", morning_params)
    print(f"  更新结果: {'✅ 成功' if ok else '❌ 失败'}")

    # 7. 验证所有参数是否持久化
    print("\n7️⃣  重新加载触发器配置验证持久化:")
    system2 = ProactiveTriggerSystem()
    work_params2 = system2.get_trigger_params("threshold_work_too_long")
    morning_params2 = system2.get_trigger_params("periodic_morning_greeting")

    print(f"  工作时长参数一致: {work_params == work_params2}")
    print(f"  早晨问候参数一致: {morning_params == morning_params2}")

    if work_params != work_params2:
        print(f"    预期: {work_params}")
        print(f"    实际: {work_params2}")

    print("\n✅ 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    test_trigger_params()
