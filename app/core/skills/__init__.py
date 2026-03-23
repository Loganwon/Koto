# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Skills System v2
可插拔的 Prompt 技能模块。
现在每个 Skill 由原子化 SkillDefinition Schema 描述，支持 MCP 导出、IO 变量、输出验收。
"""

from .skill_manager import SkillManager
from .skill_recorder import SkillRecorder
from .skill_schema import (
    InputVariable,
    OutputFormat,
    OutputSpec,
    SkillCategory,
    SkillDefinition,
    VariableType,
    make_simple_skill,
)

__all__ = [
    "SkillManager",
    "SkillDefinition",
    "SkillCategory",
    "InputVariable",
    "VariableType",
    "OutputSpec",
    "OutputFormat",
    "make_simple_skill",
    "SkillRecorder",
]
