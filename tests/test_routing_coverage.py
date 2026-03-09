#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SmartDispatcher 全量路由覆盖测试
验证天气/实时/系统/搜索等任务不被误判为 CHAT

运行方式：
  .venv\Scripts\python tests\test_routing_coverage.py
"""

import sys, os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ── 初始化 SmartDispatcher（不启动完整 Flask app）──────────────────────────
from app.core.routing.smart_dispatcher import SmartDispatcher

# 注入最小化 WebSearcher mock，避免依赖真实 Ollama / Gemini
class _MockWebSearcher:
    WEB_KEYWORDS = [
        "天气", "气温", "下雨吗", "下雪吗", "温度多少", "天气怎么样",
        "天气预报", "weather", "temperature", "forecast",
        "股价", "汇率", "比特币价格", "黄金价格", "金价", "实时金价",
        "今日金价", "当前金价", "石油价格", "a股", "港股",
        "比分", "比赛结果", "谁赢了",
        "今天新闻", "最新新闻",
        "火车票", "高铁票", "动车票", "机票", "余票",
        "时刻表", "列车时刻", "航班查询",
    ]
    @classmethod
    def needs_web_search(cls, text):
        import re
        text_lower = text.lower()
        must_patterns = [
            r'(当前|今日|实时|最新).*?(金价|黄金)',
            r'(金价|黄金).*?(多少|报价|走势|行情)',
            r'(查|看|查询).{0,6}(火车票|高铁票|机票|余票)',
        ]
        for p in must_patterns:
            if re.search(p, text_lower): return True
        return any(kw in text_lower for kw in cls.WEB_KEYWORDS)

class _MockLocalExecutor:
    APP_ALIASES = {
        "微信": [], "qq": [], "chrome": [], "edge": [], "steam": [],
        "vscode": [], "计算器": [], "截图": [], "西瓜加速": ["西瓜加速器"],
    }
    SYSTEM_KEYWORDS = ["截图", "屏幕截图", "系统时间", "关机", "重启", "休眠", "音量", "亮度"]
    @classmethod
    def is_system_command(cls, text):
        text_lower = text.lower().strip()
        has_app = any(alias in text_lower for alias in cls.APP_ALIASES)
        is_standalone = text_lower in cls.APP_ALIASES or any(kw in text_lower for kw in cls.SYSTEM_KEYWORDS)
        _cmd_starters = ("打开", "启动", "运行", "开启", "关闭", "退出", "关掉", "杀掉")
        _exclude_metaphors = ("文件", "网页", "网站", "url", "思路", "方式", "方法", "问题", "功能")
        is_action_command = (
            len(text_lower) <= 18
            and any(text_lower.startswith(s) for s in _cmd_starters)
            and not any(k in text_lower for k in _exclude_metaphors)
        )
        return has_app or is_standalone or is_action_command

class _MockContextAnalyzer:
    @staticmethod
    def analyze_context(user_input, history): return {}

SmartDispatcher.configure(
    local_executor=_MockLocalExecutor,
    context_analyzer=_MockContextAnalyzer,
    web_searcher=_MockWebSearcher,
    model_map={"CHAT": "mock"},
    client=None   # 无 client → AIRouter 直接跳过
)

# ── 测试用例定义 ────────────────────────────────────────────────────────────

CASES = [
    # ─── 天气 ─────────────────────────────────────────────────
    ("明天南京天气",              "WEB_SEARCH", "天气-基础"),
    ("今天天气怎么样",            "WEB_SEARCH", "天气-今天"),
    ("上海明天会下雨吗",          "WEB_SEARCH", "天气-下雨"),
    ("北京今天气温多少",          "WEB_SEARCH", "天气-气温"),
    ("这周天气预报",              "WEB_SEARCH", "天气-预报"),
    ("明天适合出门吗 天气怎样",   "WEB_SEARCH", "天气-出行"),

    # ─── 金融/商品价格 ────────────────────────────────────────
    ("目前金价",                  "WEB_SEARCH", "金价-目前"),
    ("黄金今日报价",              "WEB_SEARCH", "金价-今日"),
    ("布伦特原油价格",            "WEB_SEARCH", "原油-价格"),
    ("比特币现在多少钱",          "WEB_SEARCH", "比特币-现价"),
    ("美元兑人民币汇率",          "WEB_SEARCH", "汇率"),
    ("茅台股价",                  "WEB_SEARCH", "股价"),

    # ─── 实时时效信息 ─────────────────────────────────────────
    ("目前伊朗局势如何",          "WEB_SEARCH", "时效-局势"),
    ("最新AI新闻",                "WEB_SEARCH", "时效-新闻"),
    ("近期的AI动态",              "WEB_SEARCH", "时效-动态"),

    # ─── 系统命令 ─────────────────────────────────────────────
    ("打开微信",                  "SYSTEM", "系统-打开微信"),
    ("启动Chrome",                "SYSTEM", "系统-启动Chrome"),
    ("关闭QQ",                    "SYSTEM", "系统-关闭QQ"),
    ("打开西瓜加速",              "SYSTEM", "系统-打开加速器"),
    ("截图",                      "SYSTEM", "系统-截图"),

    # ─── 代码 ─────────────────────────────────────────────────
    ("帮我写一个Python排序函数",  "CODER", "代码-写函数"),
    ("做一个折线图",              "CODER", "图表-折线图"),
    ("用matplotlib画散点图",      "CODER", "图表-matplotlib"),

    # ─── 文件操作 ─────────────────────────────────────────────
    ("帮我找一下桌面上的文件",    "FILE_SEARCH", "文件搜索"),

    # ─── CHAT 应该是 CHAT ─────────────────────────────────────
    ("你好",                      "CHAT", "闲聊-问候"),
    ("你是谁",                    "CHAT", "闲聊-身份"),
    ("什么是机器学习",            "CHAT", "知识问答"),
    ("帮我写一段自我介绍",        "CHAT", "CHAT-短文"),

    # ─── 提醒/AGENT ───────────────────────────────────────────
    ("提醒我明天下午3点开会",     "AGENT", "提醒-定时"),
    ("给张三发微信说我晚点到",    "AGENT", "AGENT-发消息"),
]

# ── 运行测试 ────────────────────────────────────────────────────────────────

def run_tests():
    print("\n" + "█" * 72)
    print("  Koto SmartDispatcher 路由覆盖测试")
    print("  （无需 Ollama / Gemini，纯规则快速通道验证）")
    print("█" * 72 + "\n")

    passed = 0
    failed = 0
    fails = []

    for user_input, expected, label in CASES:
        try:
            task_type, route_method, _ = SmartDispatcher.analyze(user_input)
        except Exception as e:
            task_type = f"ERROR:{e}"
            route_method = "exception"

        ok = (task_type == expected)
        sym = "✅" if ok else "❌"
        if ok:
            passed += 1
            print(f"  {sym} [{label}]  '{user_input}'  →  {task_type}  ({route_method})")
        else:
            failed += 1
            mark = f"  {sym} [{label}]  '{user_input}'"
            detail = f"     期望: {expected}  │  实际: {task_type}  ({route_method})"
            print(mark)
            print(detail)
            fails.append((label, user_input, expected, task_type, route_method))

    print()
    print("─" * 72)
    print(f"  结果: {passed} 通过 / {passed + failed} 总数  ({failed} 失败)")
    print("─" * 72)

    if fails:
        print("\n  ❌ 失败列表：")
        for label, inp, exp, got, method in fails:
            print(f"    [{label}] 期望 {exp}，实际 {got}  |  输入='{inp}'  路由={method}")

    print()
    if failed == 0:
        print("  🎉 全部通过！路由修复有效。\n")
    else:
        pct = failed / (passed + failed) * 100
        print(f"  ⚠️  {failed} 项失败（{pct:.0f}%），需进一步调整规则。\n")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
