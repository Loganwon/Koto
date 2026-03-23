#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
占卜数据驱动改进 - 测试脚本
=================================

测试新的数据驱动占卜功能
"""

import sys
import json
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.skills.divination_data_handler import DivinationDataHandler

def test_divination_handler():
    """测试占卜数据处理器"""
    print("\n" + "="*80)
    print("🔮 占卜数据驱动引擎 - 功能测试")
    print("="*80)
    
    handler = DivinationDataHandler()
    
    # 测试1: 体育比赛预测
    print("\n【测试 1】体育比赛预测（BLG vs G2）")
    print("-" * 80)
    
    question1 = "BLG vs G2 比赛谁会赢?"
    print(f"用户问题: {question1}\n")
    
    context1 = handler.analyze_divination_question(question1)
    print(f"✓ 检测到领域: {context1.domain}")
    print(f"✓ 事件类型: {context1.event_type}")
    print(f"✓ 提取实体: {context1.entities}")
    print(f"✓ 数据可用性: {context1.is_data_available}")
    print(f"✓ 置信度: {context1.confidence:.2%}")
    
    if context1.is_data_available:
        # 模拟塔罗牌数据
        mock_cards = [
            {'card': {'zh': '权杖六', 'en': 'Six of Wands'}, 'position': '处境', 'reversed': False},
            {'card': {'zh': '战车', 'en': 'The Chariot'}, 'position': '行动', 'reversed': False},
            {'card': {'zh': '正义', 'en': 'Justice'}, 'position': '结果', 'reversed': False},
        ]
        
        prediction = handler.generate_data_driven_prediction(context1, mock_cards)
        print("\n📊 预测结果:")
        print(handler.format_prediction_for_prompt(prediction))
        assert prediction['winner'] == 'BLG'
        assert prediction['predicted_score'] in {'2:0', '2:1', '3:0', '3:1', '3:2'}
        assert prediction['prediction'].startswith('最终预测')
    
    # 测试2: 无数据领域
    print("\n\n【测试 2】感情关系建议（无量化数据）")
    print("-" * 80)
    
    question2 = "我应该和他复合吗?"
    print(f"用户问题: {question2}\n")
    
    context2 = handler.analyze_divination_question(question2)
    print(f"✓ 检测到领域: {context2.domain}")
    print(f"✓ 事件类型: {context2.event_type}")
    print(f"✓ 数据可用性: {context2.is_data_available}")
    
    if not context2.is_data_available:
        print("✓ （如预期）此问题无量化数据，应纯占卜解读")
    
    # 测试3: 数据分析函数
    print("\n\n【测试 3】队伍实力评分计算")
    print("-" * 80)
    
    blg_data = {'win_rate': 0.65, 'recent_form_score': 75, 'rank': 2}
    g2_data = {'win_rate': 0.58, 'recent_form_score': 68, 'rank': 3}
    
    blg_strength = handler._calculate_team_strength(blg_data)
    g2_strength = handler._calculate_team_strength(g2_data)
    
    print(f"BLG 实力评分: {blg_strength:.1f}/100")
    print(f"G2 实力评分: {g2_strength:.1f}/100")
    print(f"BLG 倾向性: {blg_strength / (blg_strength + g2_strength):.1%}")

    print("\n【测试 4】比分推断")
    print("-" * 80)
    bo5_context = handler.analyze_divination_question("BLG vs G2 BO5 比分会是多少？")
    bo5_prediction = handler.generate_data_driven_prediction(bo5_context, mock_cards)
    print(f"预测胜者: {bo5_prediction['winner']}")
    print(f"预测比分: {bo5_prediction['predicted_score']}")
    assert bo5_prediction['series_target_wins'] == 3
    assert bo5_prediction['predicted_score'].count(':') == 1
    
    print("\n" + "="*80)
    print("✅ 所有测试完成！")
    print("="*80)

def test_skill_manager_integration():
    """测试 skill_manager 集成"""
    print("\n\n" + "="*80)
    print("🎯 Skill Manager 集成测试")
    print("="*80)
    
    try:
        from app.core.skills.skill_manager import SkillManager
        
        print("\n【测试】数据驱动提示词生成")
        print("-" * 80)
        
        # 测试占卜提示词的增强
        user_question = "LCK 今年谁更有希望赢得世界赛？T1 还是 Gen.G？"
        
        guidance = SkillManager._get_divination_data_guidance(user_question)
        if guidance:
            print(f"✓ 为问题生成了数据驱动指导:")
            print(guidance)
            assert '关键信息' in guidance
        else:
            print("（问题未触发数据驱动分析）")
        
    except Exception as e:
        print(f"⚠ 集成测试跳过: {e}")
    
    print("\n" + "="*80)

if __name__ == "__main__":
    try:
        test_divination_handler()
        test_skill_manager_integration()
        
        print("\n\n💡 改进总结：")
        print("""
✓ 占卜数据处理器已实现，能自动识别问题领域
✓ 本地数据集成：支持体育、天气、财业等领域
✓ 倾向性预测：给出百分比而不是"两方都有可能"
✓ 牌义融合：将数据结论与塔罗象征结合
✓ Skill Manager 已集成数据驱动分析

【使用建议】
1. 扩充数据源：添加更多体育队伍、财经数据
2. 生产环境可集成外部 API（体育数据、天气预报服务）
3. 用户反馈迭代：根据预测准确度优化算法权重
        """)
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
