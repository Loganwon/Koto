# -*- coding: utf-8 -*-
"""
占卜数据驱动引擎 (Divination Data-Driven Engine)
=================================================

功能：
1. 识别占卜问题的领域类型（体育、天气、财经、关系等）
2. 从本地配置/数据库中提取相关数据
3. 生成数据驱动的倾向性预测（百分比 + 关键因素）
4. 将牌义与数据分析结合，生成"具体"的预测

使用示例：
    from app.core.skills.divination_data_handler import DivinationDataHandler

    handler = DivinationDataHandler()
    
    # 识别问题类型并提取数据
    context = handler.analyze_divination_question("BLG vs G2 比赛谁会赢?")
    # {
    #     'domain': 'sports_esports',
    #     'event_type': 'match_prediction',
    #     'entities': {'team1': 'BLG', 'team2': 'G2'},
    #     'data': {...},
    #     'confidence': 0.7
    # }
    
    # 生成倾向性预测
    prediction = handler.generate_prediction(context, drawn_cards)
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DivinationContext:
    """占卜问题的上下文信息"""
    domain: str  # 'sports', 'weather', 'finance', 'relationship', etc.
    event_type: str  # 'match', 'prediction', 'decision', etc.
    question: str  # 原始问题
    entities: Dict[str, Any]  # 提取的实体（如队伍名、日期等）
    local_data: Dict[str, Any]  # 本地数据
    confidence: float  # 数据可信度（0-1）
    is_data_available: bool  # 是否有可用数据
    metadata: Dict[str, Any]  # 补充元信息（如系列赛局制）


class DivinationDataHandler:
    """占卜数据处理器"""

    TEAM_PATTERN = re.compile(
        r"([A-Za-z0-9_.\-]+(?:\s+[A-Za-z0-9_.\-]+)*)\s*(?:vs\.?|对阵|对|打)\s*([A-Za-z0-9_.\-]+(?:\s+[A-Za-z0-9_.\-]+)*)",
        re.IGNORECASE,
    )

    # 问题关键词到领域的映射
    DOMAIN_PATTERNS = {
        'sports_esports': {
            'keywords': ['比赛', '谁赢', '谁胜', '比分', 'vs', 'vs.', '对阵', '电竞', '战队', '队伍',
                        'BLG', 'G2', 'T1', 'FakerTeam', '输赢', '防守', '进攻', '段位', 'rank'],
            'event_types': ['match_prediction', 'team_comparison', 'player_performance'],
        },
        'weather': {
            'keywords': ['天气', '下雨', '下雪', '温度', '明天', '天晴', '天阴', '风', '湿度', '气温'],
            'event_types': ['weather_forecast', 'condition_prediction'],
        },
        'finance': {
            'keywords': ['股票', '基金', '涨', '跌', '行情', '投资', '收益', '原油', '债券', '币',
                        '买入', '卖出', '指数', '趋势'],
            'event_types': ['price_movement', 'investment_decision', 'trend_prediction'],
        },
        'relationship': {
            'keywords': ['感情', '恋爱', '分手', '复合', '关系', '他', '我', '她', '亲密', '信任'],
            'event_types': ['relationship_future', 'decision_making'],
        },
        'career': {
            'keywords': ['工作', '职业', '升职', '跳槽', '辞职', '转行', '机会', '前景', '薪资', '发展'],
            'event_types': ['career_decision', 'opportunity_evaluation'],
        },
        'health': {
            'keywords': ['身体', '健康', '恢复', '病情', '检查', '医生', '症状', '治疗', '康复'],
            'event_types': ['health_outcome', 'treatment_decision'],
        },
    }

    # 本地数据源配置
    DATA_SOURCES = {
        'sports_esports': 'config/divination_data/esports_teams.json',
        'weather': 'config/divination_data/weather_cache.json',
        'finance': 'config/divination_data/finance_quotes.json',
    }

    def __init__(self):
        self.local_data = {}
        self._load_local_data()

    def _load_local_data(self):
        """加载本地配置数据"""
        for domain, path in self.DATA_SOURCES.items():
            try:
                full_path = Path(path)
                if full_path.exists():
                    with open(full_path, 'r', encoding='utf-8') as f:
                        self.local_data[domain] = json.load(f)
                        logger.info(f"Loaded divination data for {domain}")
            except Exception as e:
                logger.warning(f"Failed to load divination data for {domain}: {e}")

    def analyze_divination_question(self, question: str) -> DivinationContext:
        """
        分析占卜问题，识别领域、提取实体、获取相关数据

        Args:
            question: 用户的占卜问题

        Returns:
            DivinationContext 对象
        """
        # 识别领域
        domain = self._detect_domain(question)
        
        # 提取实体
        entities = self._extract_entities(question, domain)
        
        # 获取本地数据
        local_data, confidence = self._fetch_local_data(domain, entities)
        
        # 确定事件类型
        event_type = self._determine_event_type(question, domain)
        
        # 判断数据可用性
        is_data_available = confidence > 0.4 and len(local_data) > 0

        return DivinationContext(
            domain=domain,
            event_type=event_type,
            question=question,
            entities=entities,
            local_data=local_data,
            confidence=confidence,
            is_data_available=is_data_available,
            metadata=self._build_metadata(question, domain, entities, local_data),
        )

    def _detect_domain(self, question: str) -> str:
        """识别问题所属领域"""
        question_lower = question.lower()
        
        for domain, patterns in self.DOMAIN_PATTERNS.items():
            for keyword in patterns['keywords']:
                if keyword.lower() in question_lower:
                    return domain
        
        # 默认返回通用领域
        return 'general'

    def _extract_entities(self, question: str, domain: str) -> Dict[str, Any]:
        """从问题中提取关键实体"""
        entities = {}

        if domain == 'sports_esports':
            teams = self.TEAM_PATTERN.search(question)
            if teams:
                entities['team1'] = teams.group(1).strip()
                entities['team2'] = teams.group(2).strip()
            
            # 查找比赛类型（LOL、CS等）
            game_types = ['LOL', 'Dota2', 'CS', 'CS2', 'Valorant', 'FPS']
            for game in game_types:
                if game.lower() in question.lower():
                    entities['game_type'] = game
                    break
        
        elif domain == 'finance':
            # 提取股票/商品代码
            stocks = re.findall(r'([A-Z]{1,6}|\d{6})', question)
            if stocks:
                entities['symbols'] = stocks
        
        elif domain == 'weather':
            # 提取城市名
            cities = re.findall(r'(北京|上海|广州|深圳|杭州|成都|西安|南京|天津|重庆|苏州|杭州)', question)
            if cities:
                entities['city'] = cities[0]

        return entities

    def _build_metadata(
        self,
        question: str,
        domain: str,
        entities: Dict[str, Any],
        local_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建用于进一步预测的附加元信息。"""
        metadata: Dict[str, Any] = {}
        if domain != 'sports_esports':
            return metadata

        metadata['series_target_wins'] = self._infer_series_target_wins(question, local_data)
        metadata['score_requested'] = any(token in question for token in ['比分', '几比几', '多少比多少', 'score'])
        metadata['winner_requested'] = any(token in question for token in ['谁赢', '谁会赢', '谁胜', '赢'])
        return metadata

    def _infer_series_target_wins(self, question: str, local_data: Dict[str, Any]) -> int:
        """推断对局是 BO1 / BO3 / BO5，并返回获胜所需小局数。"""
        normalized = question.lower()
        if any(token in normalized for token in ['bo1', '一局', '单局']):
            return 1
        if any(token in normalized for token in ['bo3', '三局两胜', 'best of 3']):
            return 2
        if any(token in normalized for token in ['bo5', '五局三胜', 'best of 5']):
            return 3

        for match in local_data.get('recent_encounters', []):
            score = match.get('score', '')
            if '3-' in score or '-3' in score:
                return 3
            if '2-' in score or '-2' in score:
                return 2

        return 2

    def _fetch_local_data(self, domain: str, entities: Dict[str, Any]) -> Tuple[Dict, float]:
        """从本地数据源获取相关数据"""
        if domain not in self.local_data:
            return {}, 0.0
        
        data_source = self.local_data[domain]
        retrieved_data = {}
        confidence = 0.0

        if domain == 'sports_esports' and 'team1' in entities and 'team2' in entities:
            team1, team2 = entities['team1'], entities['team2']
            
            # 模拟从 teams 数据中查找战队数据
            teams_db = data_source.get('teams', {})
            
            team1_data = self._find_team_data(team1, teams_db)
            team2_data = self._find_team_data(team2, teams_db)
            
            if team1_data and team2_data:
                retrieved_data = {
                    'team1': team1_data,
                    'team2': team2_data,
                    'recent_encounters': self._find_recent_matches(team1, team2, data_source),
                }
                confidence = 0.75
        
        return retrieved_data, confidence

    def _find_team_data(self, team_name: str, teams_db: Dict) -> Optional[Dict]:
        """在数据库中查找队伍数据"""
        # 精确匹配
        if team_name in teams_db:
            return teams_db[team_name]
        
        # 模糊匹配
        for key, value in teams_db.items():
            if team_name.lower() in key.lower() or key.lower() in team_name.lower():
                return value
        
        return None

    def _find_recent_matches(self, team1: str, team2: str, data_source: Dict) -> List[Dict]:
        """查找两支队伍最近的对战记录"""
        matches = data_source.get('recent_matches', [])
        relevant = []
        
        for match in matches[-20:]:  # 查看最近20场
            if (match.get('team1') in [team1, team2] and 
                match.get('team2') in [team1, team2]):
                relevant.append(match)
            
            if len(relevant) >= 5:
                break
        
        return relevant

    def _determine_event_type(self, question: str, domain: str) -> str:
        """确定问题的事件类型"""
        patterns = self.DOMAIN_PATTERNS.get(domain, {})
        return patterns.get('event_types', ['prediction'])[0]

    def generate_data_driven_prediction(
        self, 
        context: DivinationContext, 
        tarot_cards: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        基于数据和塔罗牌生成预测

        Args:
            context: 占卜上下文
            tarot_cards: 抽出的塔罗牌列表，每个元素形如 
                        {'card': {...}, 'position': '处境', 'reversed': False}

        Returns:
            {
                'prediction': '具体预测文本',
                'tendency': 0.65,  # 倾向性（0-1）
                'confidence': 0.7,  # 信心度
                'data_factors': ['因素1', '因素2'],  # 数据驱动的关键因素
                'tarot_insight': '塔罗解读部分',
                'action_suggestion': '具体建议'
            }
        """
        if context.domain == 'sports_esports' and context.is_data_available:
            return self._predict_sports_match(context, tarot_cards)
        elif context.domain == 'finance' and context.is_data_available:
            return self._predict_finance(context, tarot_cards)
        else:
            # 无数据情况：纯塔罗解读
            return self._predict_generic(context, tarot_cards)

    def _predict_sports_match(
        self, 
        context: DivinationContext, 
        tarot_cards: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """体育比赛预测（数据驱动）"""
        team1_data = context.local_data.get('team1', {})
        team2_data = context.local_data.get('team2', {})
        
        # 计算队伍实力评分（0-100）
        team1_strength = self._calculate_team_strength(team1_data)
        team2_strength = self._calculate_team_strength(team2_data)
        
        # 基于历史对战计算胜率
        historical_rate = self._calculate_historical_winrate(context)
        
        # 综合数据评估
        total_strength = team1_strength + team2_strength
        team1_tendency = (team1_strength / total_strength) if total_strength > 0 else 0.5
        
        # 融合历史数据
        if historical_rate is not None:
            team1_tendency = 0.6 * team1_tendency + 0.4 * historical_rate
        
        # 根据塔罗牌调整（牌义影响±10%）
        tarot_adjustment = self._get_tarot_adjustment(tarot_cards)
        final_tendency = max(0.1, min(0.9, team1_tendency + tarot_adjustment))
        
        team1_name = context.entities.get('team1', 'Team A')
        team2_name = context.entities.get('team2', 'Team B')
        
        winner = team1_name if final_tendency >= 0.5 else team2_name
        loser = team2_name if winner == team1_name else team1_name
        winner_probability = final_tendency if winner == team1_name else (1 - final_tendency)
        winner_probability_pct = int(round(winner_probability * 100))
        series_target_wins = context.metadata.get('series_target_wins', 2)
        predicted_score = self._predict_series_score(series_target_wins, winner_probability)
        scoreline = self._format_scoreline(winner, team1_name, team2_name, predicted_score)
        
        data_factors = []
        if team1_strength > team2_strength:
            data_factors.append(f"{team1_name} 最近状态更佳（实力评分 {team1_strength:.0f}）")
        else:
            data_factors.append(f"{team2_name} 最近状态更佳（实力评分 {team2_strength:.0f}）")
        
        if historical_rate is not None:
            data_factors.append(f"历史对战中 {team1_name} 胜率为 {historical_rate*100:.0f}%")
        data_factors.append(f"综合模型给出 {winner} 赢面约 {winner_probability_pct}%")
        data_factors.append(f"预计比分：{scoreline}")
        
        return {
            'prediction': f"最终预测 {winner} 获胜，比分 {scoreline}",
            'tendency': final_tendency,
            'confidence': 0.7 + (context.confidence * 0.2),  # 0.7 - 0.9
            'data_factors': data_factors,
            'tarot_insight': self._summarize_tarot_cards(tarot_cards),
            'action_suggestion': f"直接结论写成：{winner} 赢，比分 {scoreline}。如需展开，再补充数据依据和牌面解释。",
            'winner': winner,
            'loser': loser,
            'winner_probability': winner_probability,
            'predicted_score': scoreline,
            'series_target_wins': series_target_wins,
        }

    def _predict_finance(
        self, 
        context: DivinationContext, 
        tarot_cards: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """财经预测（数据驱动）"""
        # 简化实现
        return {
            'prediction': "市场波动中，数据与牌面建议保持观望",
            'tendency': 0.5,
            'confidence': 0.5,
            'data_factors': ["当前数据有限"],
            'tarot_insight': self._summarize_tarot_cards(tarot_cards),
            'action_suggestion': "不推荐在高风险与不确定中盲目决策",
        }

    def _predict_generic(
        self, 
        context: DivinationContext, 
        tarot_cards: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """通用预测（无数据）"""
        return {
            'prediction': "本问题无可用数据支撑，预测基于纯占卜解读",
            'tendency': 0.5,
            'confidence': 0.4,
            'data_factors': [],
            'tarot_insight': self._summarize_tarot_cards(tarot_cards),
            'action_suggestion': "依靠直觉与牌面指引做决定",
        }

    def _calculate_team_strength(self, team_data: Dict[str, Any]) -> float:
        """计算队伍实力评分（0-100）"""
        if not team_data:
            return 50.0
        
        # 模拟评分计算（可根据实际数据结构调整）
        win_rate = team_data.get('win_rate', 0.5)
        recent_form = team_data.get('recent_form_score', 50)  # 0-100
        rank = team_data.get('rank', 999)
        
        # 综合评分
        strength = (
            win_rate * 40 +  # 胜率权重 40%
            recent_form * 0.3 +  # 近期表现 30%
            (100 - min(rank, 100)) * 0.3  # 排名 30%（排名越高分数越高）
        )
        
        return min(100.0, max(0.0, strength))

    def _calculate_historical_winrate(self, context: DivinationContext) -> Optional[float]:
        """计算两队之间的历史胜率"""
        recent_matches = context.local_data.get('recent_encounters', [])
        
        if not recent_matches:
            return None
        
        team1_name = context.entities.get('team1', '')
        wins = sum(1 for m in recent_matches if m.get('winner') == team1_name)
        
        return wins / len(recent_matches) if recent_matches else None

    def _get_tarot_adjustment(self, tarot_cards: List[Dict[str, Any]]) -> float:
        """根据塔罗牌获取倾向性调整（-0.1 to +0.1）"""
        if not tarot_cards:
            return 0.0

        positive_cards = sum(1 for card in tarot_cards if not card.get('reversed', False))
        negative_cards = len(tarot_cards) - positive_cards
        
        adjustment = (positive_cards - negative_cards) * 0.03
        return max(-0.1, min(0.1, adjustment))

    def _predict_series_score(self, series_target_wins: int, winner_probability: float) -> Tuple[int, int]:
        """根据胜者赢面预测系列赛比分，返回胜者在前的比分。"""
        if series_target_wins <= 1:
            return (1, 0)
        if series_target_wins == 2:
            if winner_probability >= 0.7:
                return (2, 0)
            return (2, 1)

        if winner_probability >= 0.78:
            return (3, 0)
        if winner_probability >= 0.64:
            return (3, 1)
        return (3, 2)

    def _format_scoreline(
        self,
        winner: str,
        team1_name: str,
        team2_name: str,
        predicted_score: Tuple[int, int],
    ) -> str:
        """按 team1:team2 顺序输出比分。"""
        win_score, lose_score = predicted_score
        if winner == team1_name:
            return f"{win_score}:{lose_score}"
        return f"{lose_score}:{win_score}"

    def _summarize_tarot_cards(self, tarot_cards: List[Dict[str, Any]]) -> str:
        """生成塔罗牌总结"""
        if not tarot_cards:
            return "无牌面"
        
        card_names = []
        for card in tarot_cards:
            card_obj = card.get('card', {})
            name = card_obj.get('zh', '未知')
            is_reversed = card.get('reversed', False)
            position = card.get('position', '')
            orientation = '逆位' if is_reversed else '正位'
            label = f"『{name}』{orientation}"
            if position:
                label += f"（{position}）"
            card_names.append(label)
        
        return " → ".join(card_names)

    def format_prediction_for_prompt(
        self, 
        prediction: Dict[str, Any]
    ) -> str:
        """将预测结果格式化为提示词友好的字符串"""
        lines = []
        
        if prediction.get('data_factors'):
            lines.append("【数据驱动因素】")
            for factor in prediction['data_factors']:
                lines.append(f"  • {factor}")
            lines.append("")
        
        if prediction.get('tarot_insight'):
            lines.append("【塔罗牌面】")
            lines.append(f"  {prediction['tarot_insight']}")
            lines.append("")
        
        lines.append("【倾向性预测】")
        lines.append(f"  {prediction.get('prediction', '暂无预测')}")
        lines.append(f"  （置信度：{int(prediction.get('confidence', 0.5) * 100)}%）")
        if prediction.get('winner_probability') is not None:
            lines.append(f"  胜者赢面：{int(round(prediction['winner_probability'] * 100))}%")
        if prediction.get('predicted_score'):
            lines.append(f"  预计比分：{prediction['predicted_score']}")
        lines.append("")
        
        if prediction.get('action_suggestion'):
            lines.append("【建议】")
            lines.append(f"  {prediction['action_suggestion']}")
        
        return "\n".join(lines)
