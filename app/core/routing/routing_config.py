"""
Routing constants for SmartDispatcher.

All hard-coded task-corpus entries, trivial-input sets, and model-mapping
defaults live here so smart_dispatcher.py stays focused on orchestration.
"""

from __future__ import annotations

# ── Task corpus ───────────────────────────────────────────────────────────────
# Used for n-gram similarity scoring (fallback when ML classifiers don't fire).
TASK_CORPUS: dict[str, list[str]] = {
    "PAINTER": ["画一张图", "帮我画", "生成图片", "draw me", "generate image"],
    "CODER": [
        "写代码",
        "帮我写个函数",
        "python实现",
        "write code",
        "implement function",
        "帮我作图",
        "作一个折线图",
        "画柱状图",
        "画饼图",
        "生成图表",
        "数据可视化",
        "用matplotlib画",
        "画散点图",
        "plot数据",
        "chart数据",
        "统计图",
    ],
    "FILE_GEN": [
        "生成word文档",
        "做ppt",
        "做一个word",
        "帮我做一份",
        "创建pdf",
        "写一个文档",
        "export excel",
        "生成报告模板",
        "做一个介绍文档",
        "制作幻灯片",
    ],
    "RESEARCH": [
        "深入分析",
        "全面调研",
        "technical principle",
        "in-depth study",
        "对比分析",
    ],
    "WEB_SEARCH": [
        "今天天气",
        "股价多少",
        "最新新闻",
        "current price",
        "比赛结果",
        "目前价格",
        "现在价格",
        "价格多少",
        "原油价格",
        "黄金价格",
        "布伦特原油",
        "WTI原油",
        "白银价格",
        "铜价",
        "期货价格",
        "汇率",
        "今日价",
        "实时价格",
        "加密货币",
        "比特币价格",
        "以太坊价格",
        "黄金行情",
        "原油行情",
        "外汇行情",
        "股市行情",
        "基金净值",
        "债券收益率",
    ],
    "FILE_OP": ["读取文件", "文件列表", "批量重命名", "list files", "整理文件夹"],
    "FILE_EDIT": [
        "修改文件",
        "替换内容",
        "删除第几行",
        "edit file",
        "replace in file",
    ],
    "FILE_SEARCH": ["找文件", "哪个文件", "文件在哪", "find file", "search for"],
    "CHAT": ["你好", "是什么", "介绍一下", "tell me about", "help me understand"],
    "SYSTEM": [
        "系统时间",
        "当前时间",
        "今天日期",
        "系统状态",
        "系统信息",
        "cpu状态",
        "内存状态",
        "磁盘状态",
    ],
    "AGENT": [
        "发微信",
        "给他发消息",
        "设提醒",
        "设闹钟",
        "帮我买票",
        "订票",
        "提醒我",
        "日历安排",
        "浏览器打开",
        "自动发邮件",
    ],
    "MEETING_EXTRACT": [
        "会议纪要",
        "会议记录",
        "提取会议",
        "整理会议",
        "总结会议",
        "会议要点",
        "提炼会议",
        "会议行动项",
        "会议决策",
        "meeting minutes",
        "extract action items",
    ],
}

# ── Trivial-input sets ────────────────────────────────────────────────────────

TRIVIAL_GREETINGS: frozenset[str] = frozenset({
    "你好", "你好呀", "你好啊",
    "hi", "hello", "哈喽", "嗨", "hey",
    "早上好", "早安", "中午好", "下午好", "晚上好", "晚安",
    "谢谢", "谢谢你", "谢了", "感谢", "多谢", "thanks", "thank you",
    "再见", "拜拜", "bye", "goodbye", "下次见",
    "好的", "好", "嗯", "嗯嗯", "明白了", "知道了", "收到",
    "ok", "okay",
})

TRIVIAL_IDENTITY: tuple[str, ...] = (
    "你是谁", "你叫什么", "你叫啥", "你是什么", "介绍一下你自己",
    "你是koto", "koto是什么",
)

# If any of these appear, the input cannot take the trivial fast-path
# even if it's very short.
TRIVIAL_EXCLUDE: tuple[str, ...] = (
    "画", "图片", "照片", "图", "代码", "程序", "脚本", "文件", "文档", "报告",
    "pdf", "word", "excel", "ppt", "天气", "股价", "新闻", "汇率",
    "搜索", "微信", "发送",
    "发消息", "发邮件", "购票", "研究", "分析", "深入", "全面",
    # Chart/dataviz
    "作图", "图表", "折线图", "柱状图", "饼图", "散点图", "直方图",
    "可视化", "统计图", "数据图", "chart", "plot", "matplotlib",
    "seaborn", "plotly",
    # Finance/commodity
    "原油", "布伦特", "黄金", "白银", "铜价", "期货", "汇率",
    "比特币", "以太坊", "价格", "行情", "走势", "现价", "涨跌",
    "金价", "油价", "银价", "气价",
    # Weather variants
    "下雨", "下雪", "气温", "天气",
    # Low-risk system info
    "系统状态", "系统信息", "系统时间", "当前时间", "日期", "cpu", "内存", "硬盘",
    # Programming
    "python", "javascript", "java", "golang", "rust", "c++", "sql",
    "函数", "算法", "脚本", "接口", "api",
    # Timeliness signals
    "目前", "近期", "局势", "战况", "动态", "进展", "现状", "近况",
)
