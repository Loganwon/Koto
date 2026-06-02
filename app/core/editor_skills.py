# ══════════════════════════════════════════════════════════════
# editor_skills.py — 文件助手 Skill 注册表 & 阶段定义
#
# 每个 Skill 定义:
#   - id/name/slash_cmd: 标识与触发
#   - phases[]: 执行阶段列表（驱动前端 PhaseTracker）
#   - file_types[]: 支持的文件类型（空 = 全部）
#   - needs_selection: 是否需要选区
#   - multi_step: 是否为多步骤 Skill（需要多轮 LLM）
#
# 阶段 status 枚举:
#   running / done / skipped / waiting_approval
# ══════════════════════════════════════════════════════════════

# ── Phase 定义 ────────────────────────────────────────────────
# 简单动作（润色/翻译/总结等）使用 PHASES_SIMPLE（2 阶段，无延迟感）
# 复杂 Skill（格式统一/审查/术语翻译等）使用自定义阶段

PHASES_SIMPLE = [
    {"id": "understand", "label": "理解需求"},
    {"id": "generate", "label": "生成回复"},
]

PHASES_ANALYZE = [
    {"id": "understand", "label": "理解需求"},
    {"id": "analyze", "label": "分析文档"},
    {"id": "generate", "label": "生成结果"},
    {"id": "verify", "label": "检查质量"},
]

PHASES_FORMAT_NORMALIZE = [
    {"id": "scan", "label": "扫描文档结构"},
    {"id": "identify", "label": "识别格式问题"},
    {"id": "preview", "label": "生成修改方案"},
    {"id": "apply", "label": "应用修改"},
]

PHASES_REVIEW = [
    {"id": "identify", "label": "识别文档类型"},
    {"id": "checklist", "label": "生成检查项"},
    {"id": "check", "label": "逐项审查"},
    {"id": "report", "label": "总结报告"},
]

PHASES_GLOSSARY_TRANSLATE = [
    {"id": "extract", "label": "提取术语"},
    {"id": "confirm", "label": "确认术语表"},
    {"id": "translate", "label": "逐段翻译"},
    {"id": "verify", "label": "一致性检查"},
]

PHASES_MEETING_NOTES = [
    {"id": "parse", "label": "识别议题"},
    {"id": "structure", "label": "结构化整理"},
    {"id": "actions", "label": "提取行动项"},
]

PHASES_DATA_CLEAN = [
    {"id": "analyze", "label": "分析数据质量"},
    {"id": "plan", "label": "生成清洗方案"},
    {"id": "execute", "label": "执行清洗"},
    {"id": "preview", "label": "预览结果"},
]

PHASES_SLIDE_EXPAND = [
    {"id": "outline", "label": "解析大纲"},
    {"id": "generate", "label": "逐页生成"},
    {"id": "preview", "label": "预览确认"},
]

# ── Skill 注册表 ──────────────────────────────────────────────

EDITOR_SKILLS = {
    # ── 简单动作（保持现有快速响应） ──
    "polish": {
        "id": "polish",
        "name": "润色",
        "slash_cmd": "/润色",
        "icon": "✨",
        "description": "润色选中文本",
        "phases": PHASES_SIMPLE,
        "file_types": [],
        "needs_selection": True,
        "multi_step": False,
    },
    "translate": {
        "id": "translate",
        "name": "翻译",
        "slash_cmd": "/翻译",
        "icon": "🌐",
        "description": "翻译选中文本",
        "phases": PHASES_SIMPLE,
        "file_types": [],
        "needs_selection": True,
        "multi_step": False,
    },
    "summarize": {
        "id": "summarize",
        "name": "总结",
        "slash_cmd": "/总结",
        "icon": "📋",
        "description": "总结全文要点",
        "phases": PHASES_SIMPLE,
        "file_types": [],
        "needs_selection": False,
        "multi_step": False,
    },
    "check": {
        "id": "check",
        "name": "检查",
        "slash_cmd": "/检查",
        "icon": "🔍",
        "description": "检查语法错别字",
        "phases": PHASES_ANALYZE,
        "file_types": [],
        "needs_selection": False,
        "multi_step": False,
    },
    "continue_writing": {
        "id": "continue_writing",
        "name": "续写",
        "slash_cmd": "/续写",
        "icon": "✍️",
        "description": "继续写作",
        "phases": PHASES_SIMPLE,
        "file_types": [],
        "needs_selection": False,
        "multi_step": False,
    },
    "rewrite": {
        "id": "rewrite",
        "name": "改写",
        "slash_cmd": "/改写",
        "icon": "✏️",
        "description": "改写表达方式",
        "phases": PHASES_SIMPLE,
        "file_types": [],
        "needs_selection": True,
        "multi_step": False,
    },
    # ── 复杂多阶段 Skill ──
    "format_normalize": {
        "id": "format_normalize",
        "name": "格式统一",
        "slash_cmd": "/格式统一",
        "icon": "🎨",
        "description": "统一文档格式（字号/字体/标题层级）",
        "phases": PHASES_FORMAT_NORMALIZE,
        "file_types": ["docx", "pdf"],
        "needs_selection": False,
        "multi_step": True,
    },
    "review_checklist": {
        "id": "review_checklist",
        "name": "审查",
        "slash_cmd": "/审查",
        "icon": "📋",
        "description": "文档审查清单（逐项检查）",
        "phases": PHASES_REVIEW,
        "file_types": [],
        "needs_selection": False,
        "multi_step": True,
    },
    "glossary_translate": {
        "id": "glossary_translate",
        "name": "术语翻译",
        "slash_cmd": "/术语翻译",
        "icon": "📖",
        "description": "提取术语表→一致性翻译全文",
        "phases": PHASES_GLOSSARY_TRANSLATE,
        "file_types": [],
        "needs_selection": False,
        "multi_step": True,
    },
    "glossary_translate_exec": {
        "id": "glossary_translate_exec",
        "name": "执行翻译",
        "slash_cmd": None,  # triggered programmatically from approval card
        "icon": "🌐",
        "description": "用确认的术语表翻译全文（第二阶段）",
        "phases": [
            {"id": "translate", "label": "逐段翻译"},
            {"id": "verify", "label": "一致性检查"},
        ],
        "file_types": [],
        "needs_selection": False,
        "multi_step": False,
    },
    "meeting_notes": {
        "id": "meeting_notes",
        "name": "会议纪要",
        "slash_cmd": "/会议纪要",
        "icon": "📝",
        "description": "散乱笔记→结构化纪要+行动项",
        "phases": PHASES_MEETING_NOTES,
        "file_types": [],
        "needs_selection": False,
        "multi_step": True,
    },
    "data_clean": {
        "id": "data_clean",
        "name": "清洗数据",
        "slash_cmd": "/清洗数据",
        "icon": "🧹",
        "description": "表格数据清洗（空值/重复/格式统一）",
        "phases": PHASES_DATA_CLEAN,
        "file_types": ["xlsx", "csv"],
        "needs_selection": False,
        "multi_step": True,
    },
    "slide_expand": {
        "id": "slide_expand",
        "name": "填充幻灯片",
        "slash_cmd": "/填充幻灯片",
        "icon": "📑",
        "description": "PPT大纲→逐页内容填充",
        "phases": PHASES_SLIDE_EXPAND,
        "file_types": ["pptx"],
        "needs_selection": False,
        "multi_step": True,
    },
}


def get_skill(action_id):
    """Get skill definition by action ID. Returns None for unknown actions."""
    return EDITOR_SKILLS.get(action_id)


def get_phases(action_id):
    """Get phase list for an action. Falls back to PHASES_SIMPLE for unknown actions."""
    skill = EDITOR_SKILLS.get(action_id)
    if skill:
        return skill["phases"]
    return PHASES_SIMPLE


def get_all_slash_commands():
    """Return list of {cmd, action, icon, hint} for all registered skills."""
    return [
        {
            "cmd": s["slash_cmd"],
            "action": s["id"],
            "icon": s["icon"],
            "hint": s["description"],
        }
        for s in EDITOR_SKILLS.values()
    ]


def get_multi_step_skills():
    """Return IDs of skills that have multi_step=True."""
    return [s["id"] for s in EDITOR_SKILLS.values() if s["multi_step"]]
