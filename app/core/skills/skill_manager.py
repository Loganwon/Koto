# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
🎯 Koto Skills Manager（v2 — 原子化 Schema 升级）

可插拔的 Prompt 技能系统。
每个 Skill 现在由 SkillDefinition（原子化标准 Schema）描述，
支持 MCP Tool 导出、IO 变量约束、输出验收规格。

向后兼容：dict 格式的 BUILTIN_SKILLS 会自动升级为 SkillDefinition，
原有的 inject_into_prompt / list_skills / set_enabled 等 API 不变。

新增 API:
    SkillManager.get_definition(skill_id)   → SkillDefinition
    SkillManager.list_mcp_tools()           → List[MCP Tool dict]
    SkillManager.register_custom(skill_def) → 注册自定义 Skill
    SkillManager.load_custom_skills_dir()   → 从 config/skills/ 目录加载 JSON Skill 文件

用法:
    from app.core.skills.skill_manager import SkillManager

    enhanced = SkillManager.inject_into_prompt(base_instruction, task_type="CHAT")
    skills   = SkillManager.list_skills()
    SkillManager.set_enabled("concise_mode", True)

    # 新：导出 MCP 工具列表
    mcp_tools = SkillManager.list_mcp_tools()
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from app.core.skills.skill_schema import SkillDefinition

logger = logging.getLogger(__name__)

from app.core.skills.builtin_skills import BUILTIN_SKILLS  # noqa: E402 — data import

_SKILL_STATE_UNSET = object()


class SkillManager:
    """
    Skills 管理器 v2
    - 单例模式加载，首次访问时初始化
    - 启用/禁用状态持久化到 config/user_settings.json
    - 新增：_def_registry 存储原子化 SkillDefinition 对象（MCP 兼容）
    - 新增：register_custom / list_mcp_tools / load_custom_skills_dir
    """

    _registry: Dict[str, Dict] = {}  # id → runtime skill dict view
    _def_registry: Dict[str, SkillDefinition] = {}  # id → 新版 SkillDefinition（v2）
    _builtin_prompt_index: Dict[str, str] = (
        {}
    )  # id → original built-in prompt (O(1) lookup)
    _initialized: bool = False
    # 单轮注入的用户启用 Skill 数上限（系统 Skill 不计入），防止 token 膨胀
    _MAX_ACTIVE_INJECT: int = 20

    @classmethod
    def instance(cls):
        """Compatibility helper for call sites that expect a singleton accessor."""
        cls._ensure_init()
        return cls

    @classmethod
    def _skill_enabled(
        cls, skill_id: str, skill_def: Optional[SkillDefinition] = None
    ) -> bool:
        runtime_entry = cls._registry.get(skill_id)
        if runtime_entry is not None and "enabled" in runtime_entry:
            return bool(runtime_entry.get("enabled", False))
        if skill_def is None:
            skill_def = cls._def_registry.get(skill_id)
        return bool(getattr(skill_def, "enabled", False))

    @classmethod
    def _skill_prompt(
        cls, skill_id: str, skill_def: Optional[SkillDefinition] = None
    ) -> str:
        runtime_entry = cls._registry.get(skill_id)
        if runtime_entry is not None and "prompt" in runtime_entry:
            return runtime_entry.get("prompt", "") or ""
        if skill_def is None:
            skill_def = cls._def_registry.get(skill_id)
        return str(getattr(skill_def, "prompt", "") or "")

    @classmethod
    def _runtime_entry_from_definition(
        cls,
        skill_def: SkillDefinition,
        existing: Optional[Dict] = None,
        *,
        enabled: object = _SKILL_STATE_UNSET,
        prompt: object = _SKILL_STATE_UNSET,
    ) -> Dict:
        """Build the runtime registry view from the canonical SkillDefinition."""
        entry = dict(existing or {})
        entry.update(
            {
                "id": skill_def.id,
                "name": skill_def.name,
                "icon": skill_def.icon,
                "category": (
                    skill_def.category.value
                    if hasattr(skill_def.category, "value")
                    else skill_def.category
                ),
                "skill_nature": (
                    skill_def.skill_nature.value
                    if hasattr(skill_def.skill_nature, "value")
                    else skill_def.skill_nature
                ),
                "description": skill_def.description,
                "task_types": list(skill_def.task_types or []),
                "author": getattr(skill_def, "author", entry.get("author", "")),
            }
        )

        prompt_value = entry.get("prompt", getattr(skill_def, "prompt", "") or "")
        if prompt is not _SKILL_STATE_UNSET:
            prompt_value = str(prompt or "")
        entry["prompt"] = prompt_value

        enabled_value = entry.get("enabled", getattr(skill_def, "enabled", False))
        if enabled is not _SKILL_STATE_UNSET:
            enabled_value = bool(enabled)
        entry["enabled"] = bool(enabled_value)

        optional_list_fields = (
            "tags",
            "executor_tools",
            "plan_template",
            "permissions",
            "bound_tools",
            "trigger_keywords",
        )
        for field in optional_list_fields:
            value = getattr(skill_def, field, None)
            if value:
                entry[field] = list(value)

        optional_passthrough_fields = (
            "priority",
            "ui_config",
            "ui_extensions",
            "template_path",
            "entry_point",
        )
        for field in optional_passthrough_fields:
            value = getattr(skill_def, field, None)
            if value not in (None, "", {}, []):
                entry[field] = value

        return entry

    @classmethod
    def _apply_skill_state(
        cls,
        skill_id: str,
        *,
        enabled: object = _SKILL_STATE_UNSET,
        prompt: object = _SKILL_STATE_UNSET,
    ) -> bool:
        """Apply state change to _def_registry (canonical) and sync to the runtime view."""
        skill_def = cls._def_registry.get(skill_id)
        if skill_def is None:
            runtime_entry = cls._registry.get(skill_id)
            if runtime_entry is None:
                return False
            if enabled is not _SKILL_STATE_UNSET:
                runtime_entry["enabled"] = bool(enabled)
            if prompt is not _SKILL_STATE_UNSET:
                runtime_entry["prompt"] = str(prompt or "")
            return True

        if enabled is not _SKILL_STATE_UNSET:
            skill_def.enabled = bool(enabled)
        if prompt is not _SKILL_STATE_UNSET:
            skill_def.prompt = str(prompt or "")
        cls._registry[skill_id] = cls._runtime_entry_from_definition(
            skill_def,
            existing=cls._registry.get(skill_id),
            enabled=enabled,
            prompt=prompt,
        )
        return True

    # ── 初始化 ─────────────────────────────────────────────────────────────────
    @classmethod
    def _ensure_init(cls):
        if cls._initialized:
            return
        cls._registry = {}
        cls._def_registry = {}
        cls._builtin_prompt_index = {s["id"]: s["prompt"] for s in BUILTIN_SKILLS}
        for skill in BUILTIN_SKILLS:
            s = dict(skill)  # shallow copy
            cls._registry[s["id"]] = s
            # 同步升级到 SkillDefinition
            cls._def_registry[s["id"]] = SkillDefinition.from_legacy_dict(s)
        cls._load_states_from_settings()
        # 从 config/skills/ 目录加载用户自定义 Skill（如果存在）
        cls._load_custom_skills_dir()
        # 自定义 Skill 加载后再次应用持久化状态（因自定义 Skill 在第一次 _load_states 时尚未注册）
        cls._load_states_from_settings()
        cls._initialized = True

    @classmethod
    def _settings_path(cls) -> Path:
        """返回 config/user_settings.json 的绝对路径"""
        import sys

        if getattr(sys, "frozen", False):
            # 打包模式：config/ 紧邻 Koto.exe，不在 _internal/ 里
            project_root = Path(sys.executable).parent
        else:
            here = Path(__file__).resolve()
            # app/core/skills/skill_manager.py → project_root/config/user_settings.json
            project_root = here.parents[3]
        return project_root / "config" / "user_settings.json"

    @classmethod
    def _load_states_from_settings(cls):
        """从 user_settings.json 读取持久化的启用状态"""
        try:
            p = cls._settings_path()
            if not p.exists():
                return
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            skills_state = data.get("skills", {})
            for skill_id, state in skills_state.items():
                if not isinstance(state, dict):
                    continue
                enabled = state["enabled"] if "enabled" in state else _SKILL_STATE_UNSET
                prompt = (
                    state["prompt_override"]
                    if state.get("prompt_override")
                    else _SKILL_STATE_UNSET
                )
                cls._apply_skill_state(skill_id, enabled=enabled, prompt=prompt)
        except Exception as e:
            print(f"[SkillManager] 加载设置失败: {e}")

    @classmethod
    def _save_states_to_settings(cls):
        """将当前启用状态写回 user_settings.json"""
        try:
            p = cls._settings_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            skills_state = {}
            all_skill_ids = set(cls._registry) | set(cls._def_registry)
            for skill_id in all_skill_ids:
                skill_def = cls._def_registry.get(skill_id)
                prompt = cls._skill_prompt(skill_id, skill_def)
                state: Dict = {"enabled": cls._skill_enabled(skill_id, skill_def)}
                # 如果有自定义 prompt，也保存
                builtin_prompt = cls._builtin_prompt_index.get(skill_id)
                if prompt != builtin_prompt:
                    state["prompt_override"] = prompt
                skills_state[skill_id] = state
            data["skills"] = skills_state
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[SkillManager] 保存设置失败: {e}")

    # ── 公开 API ───────────────────────────────────────────────────────────────
    @classmethod
    def list_skills(cls) -> List[Dict]:
        """
        返回所有技能的完整信息列表（内置 + 自定义）
        """
        cls._ensure_init()
        result = []
        seen_ids: set = set()

        # 内置 Skill（保持原有顺序）
        for skill in BUILTIN_SKILLS:
            sid = skill["id"]
            seen_ids.add(sid)
            skill_def = cls._def_registry.get(sid)
            s = cls._registry.get(sid, skill)
            builtin_prompt = skill["prompt"]
            prompt = cls._skill_prompt(sid, skill_def)
            result.append(
                {
                    "id": sid,
                    "name": getattr(skill_def, "name", s["name"]),
                    "icon": getattr(skill_def, "icon", s["icon"]),
                    "category": getattr(
                        getattr(skill_def, "category", None), "value", s["category"]
                    ),
                    "skill_nature": getattr(
                        getattr(skill_def, "skill_nature", None),
                        "value",
                        s.get("skill_nature", "domain_skill"),
                    ),
                    "description": getattr(skill_def, "description", s["description"]),
                    "task_types": list(
                        getattr(skill_def, "task_types", s["task_types"])
                    ),
                    "enabled": cls._skill_enabled(sid, skill_def),
                    "has_custom_prompt": prompt != builtin_prompt,
                    "prompt": prompt,
                    "is_builtin": True,
                }
            )

        # 自定义 Skill（不在内置列表中的）
        for skill_id, skill_def in cls._def_registry.items():
            if skill_id in seen_ids:
                continue
            s = cls._registry.get(skill_id, {})
            result.append(
                {
                    "id": skill_id,
                    "name": skill_def.name,
                    "icon": skill_def.icon,
                    "category": getattr(
                        skill_def.category, "value", skill_def.category
                    ),
                    "description": skill_def.description,
                    "task_types": list(skill_def.task_types or []),
                    "enabled": cls._skill_enabled(skill_id, skill_def),
                    "skill_nature": getattr(
                        skill_def.skill_nature,
                        "value",
                        s.get("skill_nature", "domain_skill"),
                    ),
                    "has_custom_prompt": False,
                    "prompt": cls._skill_prompt(skill_id, skill_def),
                    "is_builtin": False,
                }
            )

        return result

    @classmethod
    def get_active_ui_config(cls) -> dict:
        """
        收集所有已启用且含有 ui_config 或 ui_extensions 的 Skill，
        按优先级从低到高合并，高优先级 Skill 的值覆盖低优先级的同名键；
        css_vars 字典相互合并；ui_extensions 中的列表字段相互追加。

        返回格式:
          {
            "has_ui": bool,
            "config": { ...合并后的 ui_config dict... },
            "extensions": { ...合并后的 ui_extensions dict... },
            "sources": ["skill_id", ...]
          }
        """
        cls._ensure_init()

        # 检查权限：只有已授权 ui_interactive 的 skill 才返回其 ui_extensions
        try:
            from app.core.skills.skill_permissions import SkillPermissionManager

            _perm_mgr = SkillPermissionManager
        except Exception:
            _perm_mgr = None

        enabled_with_ui = []
        for sid, skill_def in cls._def_registry.items():
            runtime_entry = cls._registry.get(sid, {})
            if not cls._skill_enabled(sid, skill_def):
                continue
            cfg = runtime_entry.get("ui_config") or getattr(
                skill_def, "ui_config", None
            )
            ext = runtime_entry.get("ui_extensions") or getattr(
                skill_def, "ui_extensions", None
            )
            if cfg or ext:
                enabled_with_ui.append(
                    (sid, skill_def, runtime_entry, cfg or {}, ext or {})
                )

        if not enabled_with_ui:
            return {"has_ui": False, "config": {}, "extensions": {}, "sources": []}

        # 低优先级先合并，高优先级后覆盖
        enabled_with_ui.sort(
            key=lambda x: x[2].get("priority", getattr(x[1], "priority", 50))
        )

        merged: dict = {}
        merged_ext: dict = {}
        sources: list = []
        for sid, skill_def, runtime_entry, cfg, ext in enabled_with_ui:
            if isinstance(cfg, dict) and cfg:
                css = cfg.get("css_vars")
                if css and isinstance(css, dict):
                    merged.setdefault("css_vars", {}).update(css)
                for k, v in cfg.items():
                    if k != "css_vars" and v not in (None, "", False, {}, []):
                        merged[k] = v

            # ui_extensions 合并（需要 ui_interactive 权限已授权，或 skill 未声明该权限要求）
            if ext and isinstance(ext, dict):
                required_perms = list(
                    getattr(skill_def, "permissions", None)
                    or runtime_entry.get("permissions", [])
                )
                needs_interactive = "ui_interactive" in required_perms
                interactive_granted = (
                    _perm_mgr is None
                    or not needs_interactive
                    or _perm_mgr.is_granted(sid, "ui_interactive")
                )
                if interactive_granted:
                    # action_buttons: 追加
                    if ext.get("action_buttons"):
                        merged_ext.setdefault("action_buttons", []).extend(
                            ext["action_buttons"]
                        )
                    # quick_replies: 追加
                    if ext.get("quick_replies"):
                        merged_ext.setdefault("quick_replies", []).extend(
                            ext["quick_replies"]
                        )
                    # floating_widget: 高优先级覆盖
                    if ext.get("floating_widget"):
                        merged_ext["floating_widget"] = ext["floating_widget"]

            sources.append(sid)

        has_ui = bool(merged) or bool(merged_ext)
        return {
            "has_ui": has_ui,
            "config": merged,
            "extensions": merged_ext,
            "sources": sources,
        }

    @classmethod
    def set_enabled(cls, skill_id: str, enabled: bool) -> bool:
        """启用或禁用一个技能，立即持久化"""
        cls._ensure_init()
        if not cls._apply_skill_state(skill_id, enabled=enabled):
            return False
        cls._save_states_to_settings()
        print(f"[SkillManager] {'✅ 启用' if enabled else '⏸️ 禁用'} skill: {skill_id}")
        return True

    @classmethod
    def update_prompt(cls, skill_id: str, prompt: str) -> bool:
        """更新某个技能的自定义 Prompt 内容（用户可自定义后保存）"""
        cls._ensure_init()
        if not cls._apply_skill_state(skill_id, prompt=prompt):
            return False
        cls._save_states_to_settings()
        return True

    @classmethod
    def reset_prompt(cls, skill_id: str) -> bool:
        """将某个技能的 Prompt 恢复为内置默认值"""
        cls._ensure_init()
        if skill_id not in cls._registry and skill_id not in cls._def_registry:
            return False
        builtin_prompt = cls._builtin_prompt_index.get(skill_id)
        if builtin_prompt is not None:
            cls._apply_skill_state(skill_id, prompt=builtin_prompt)
            cls._save_states_to_settings()
        return True

    @classmethod
    def check_conflicts(cls, task_type: Optional[str] = None) -> List[Dict]:
        """
        检测当前所有已启用 Skills 之间的冲突关系。

        返回冲突列表，每项格式：
          {
            "winner_id":   "concise_mode",
            "winner_name": "精简模式",
            "loser_id":    "research_depth",
            "loser_name":  "深度研究",
            "reason":      "concise_mode 优先级(90) > research_depth 优先级(55)"
          }
        """
        cls._ensure_init()
        conflicts: List[Dict] = []
        seen_pairs: set = set()

        enabled_skills: Dict[str, SkillDefinition] = {}
        for sid, sdef in cls._def_registry.items():
            if not cls._skill_enabled(sid, sdef):
                continue
            if (
                not task_type
                or not sdef.task_types
                or task_type.upper() in sdef.task_types
            ):
                enabled_skills[sid] = sdef

        for skill_id, sdef in enabled_skills.items():
            conflict_ids = getattr(sdef, "conflict_with", None) or []
            for conflict_id in conflict_ids:
                if conflict_id not in enabled_skills:
                    continue
                pair = tuple(sorted([skill_id, conflict_id]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                other = enabled_skills[conflict_id]
                pri_a = getattr(sdef, "priority", 50)
                pri_b = getattr(other, "priority", 50)

                if pri_a >= pri_b:
                    winner, loser = sdef, other
                    winner_id, loser_id = skill_id, conflict_id
                else:
                    winner, loser = other, sdef
                    winner_id, loser_id = conflict_id, skill_id

                conflicts.append(
                    {
                        "winner_id": winner_id,
                        "winner_name": getattr(winner, "name", winner_id),
                        "winner_priority": pri_a,
                        "loser_id": loser_id,
                        "loser_name": getattr(loser, "name", loser_id),
                        "loser_priority": pri_b,
                        "reason": (
                            f"「{getattr(winner, 'name', winner_id)}」优先级({pri_a}) "
                            f"≥「{getattr(loser, 'name', loser_id)}」优先级({pri_b})，"
                            f"后者 prompt 在本次请求中被抑制"
                        ),
                    }
                )
        return conflicts

    @classmethod
    def _normalize_divination_prompt(
        cls, prompt: str, user_input: Optional[str] = None
    ) -> str:
        """统一占卜提示词风格：弱化“神谕”措辞，并默认按问题起牌。"""
        if not prompt:
            return prompt

        normalized = prompt
        replacements = {
            "神谕占卜模式": "塔罗占卜模式",
            "你现在是「神谕」——一位洞悉宇宙之语的存在。": "你现在是一位塔罗解读师，风格神秘但表达清晰、可执行。",
            "神谕寄语（必须有）": "结论总结（必须有）",
            "神谕的话": "结论",
            "神谕为你揭示牌面": "牌面为你揭示",
            "神谕静听宇宙之声": "牌面正在回应你的问题",
            "向神谕倾诉": "说出你的问题",
        }
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)

        default_draw_rule = (
            "\n\n**默认起牌规则（高优先级）**\n"
            "- 占卜技能开启后，只要用户提出占卜相关问题，即默认按问题起牌并解读。\n"
            "- 不需要先追问“要不要抽牌”；直接进入抽牌与解读。\n"
            "- 若用户未指定牌阵，默认使用「三张牌阵·处境·行动·结果」。"
        )
        if "默认起牌规则" not in normalized:
            normalized += default_draw_rule

        # 数据驱动分析指导：对于体育、财经、天气等领域给出明确的倾向性预测指导
        data_driven_guidance = cls._get_divination_data_guidance(user_input)
        if data_driven_guidance:
            normalized += "\n\n" + data_driven_guidance

        return normalized

    @classmethod
    def _get_divination_data_guidance(cls, user_input: Optional[str]) -> str:
        """根据用户输入检测是否应该提供数据驱动的占卜分析指导"""
        if not user_input:
            return ""

        try:
            from app.core.skills.divination_data_handler import DivinationDataHandler

            handler = DivinationDataHandler()
            context = handler.analyze_divination_question(user_input)

            # 仅对有数据可用的问题提供指导
            if context.is_data_available and context.domain != "general":
                prediction = handler.generate_data_driven_prediction(context, [])
                guidance = f"""
**【数据驱动分析提示】**
检测到该问题涉及 {context.domain} 领域，且本地有相关数据可用。

关键信息：
{handler.format_prediction_for_prompt(prediction)}

请在解读中融合这些信息，给出明确的倾向性判断。
"""
                return guidance
        except Exception as e:
            logger.debug(f"[SkillManager] 数据驱动分析失败（非致命）: {e}")

        return ""

    # FILE_ASSISTANT is a composite context: skills for any of these types are applicable
    _FILE_ASSISTANT_COVERS = {"CHAT", "FILE_GEN", "DOC_ANNOTATE", "RESEARCH"}

    @classmethod
    def _task_type_matches(
        cls, task_type: Optional[str], applicable_types: list
    ) -> bool:
        """Return True if the skill should fire for the given task_type."""
        if not applicable_types or not task_type:
            return True
        tt = task_type.upper()
        if tt == "FILE_ASSISTANT":
            return bool(cls._FILE_ASSISTANT_COVERS.intersection(applicable_types))
        return tt in applicable_types

    @classmethod
    def inject_into_prompt(
        cls,
        base_instruction: str,
        task_type: Optional[str] = None,
        user_input: Optional[str] = None,
        temp_skill_ids: Optional[List[str]] = None,
    ) -> str:
        """
        将当前启用的、适用于 task_type 的 Skills 注入到 base_instruction 末尾。

        冲突处理：当两个互相冲突的 Skill 同时启用时，优先级（priority）更高的
        skill 正常注入，低优先级的 skill 被静默抑制（但仍保持「启用」状态供用户查看）。

        Token 膨胀保护：单轮注入的用户启用 Skill 数（不含长期记忆）超过
        _MAX_ACTIVE_INJECT 时，按 priority 降序仅保留靠前的 skill，其余跳过。

        Args:
            base_instruction: 原始系统指令文本
            task_type:        当前任务类型（如 "CHAT"），None 表示通用
            user_input:       用户当前输入文本；传入后为长期记忆 skill
                              提供语义检索依据，精准命中相关记忆条目
            temp_skill_ids:   本轮临时激活的 Skill ID 列表（AutoMatcher 推荐）。
                              这些 Skill 即使 enabled=False 也会注入，且不修改
                              持久状态；注入后标注「自动匹配」供模型区分。

        Returns:
            注入后的系统指令文本
        """
        cls._ensure_init()
        active_prompts = []
        memory_block = ""
        seen_ids: set = set()  # 防止重复注入
        _inject_skill_count = 0  # 已注入的非系统 Skill 计数（用于上限保护）

        # ── 预计算冲突：找出所有因冲突被抑制的 skill_id ────────────────────
        suppressed_ids: set = set()
        all_enabled = {
            sid: s for sid, s in cls._registry.items() if s.get("enabled", False)
        }
        for sid, s in all_enabled.items():
            pri_a = s.get("priority", 50)
            for conflict_id in s.get("conflict_with", []):
                if conflict_id not in all_enabled:
                    continue
                pri_b = all_enabled[conflict_id].get("priority", 50)
                # 低优先级的那个被抑制
                if pri_a >= pri_b:
                    suppressed_ids.add(conflict_id)
                    logger.debug(
                        f"[SkillManager] 冲突抑制: {sid}(p={pri_a}) 抑制了 "
                        f"{conflict_id}(p={pri_b})"
                    )
                # 如果两者 priority 相等，按字母序决策（确保稳定性）
                elif pri_a == pri_b and sid < conflict_id:
                    suppressed_ids.add(conflict_id)

        # 遍历所有 registry 中的 Skill（内置 + 自定义），按 priority 排序
        all_skill_items = sorted(
            cls._registry.items(),
            key=lambda kv: kv[1].get("priority", 50),
            reverse=True,  # 高 priority 先注入
        )

        for skill_id, s in all_skill_items:
            if skill_id in seen_ids:
                continue

            if not s.get("enabled", False):
                continue

            seen_ids.add(skill_id)

            # 跳过被冲突抑制的 Skill
            if skill_id in suppressed_ids:
                logger.debug(f"[SkillManager] 跳过被抑制的 Skill: {skill_id}")
                continue

            applicable_types = s.get("task_types", [])
            if not cls._task_type_matches(task_type, applicable_types):
                continue

            # ── 长期记忆 skill：优先从 ShadowWatcher 检索记忆并注入 ────────────
            if skill_id == "long_term_memory":
                try:
                    from app.core.monitoring.shadow_watcher import get_shadow_watcher

                    ctx = get_shadow_watcher().get_memories_context_string(
                        user_input or ""
                    )
                    if ctx.strip():
                        memory_block = ctx
                except Exception as _me:
                    logger.debug(f"[SkillManager] 影子记忆注入跳过: {_me}")
                    # 回退：旧 MemoryManager
                    try:
                        from web.memory_manager import MemoryManager

                        _mm = MemoryManager()
                        ctx = _mm.get_context_string(user_input or "")
                        if ctx.strip():
                            memory_block = ctx
                    except Exception:
                        pass
                continue  # 长期记忆不走普通 prompt 通道

            # ── 注入上限检测（长期记忆走了 continue，不计入此计数）─────────────
            if _inject_skill_count >= cls._MAX_ACTIVE_INJECT:
                logger.debug(
                    "[SkillManager] 注入上限 (%d) 已达，跳过低优先级 Skill: %s",
                    cls._MAX_ACTIVE_INJECT,
                    skill_id,
                )
                continue

            # 优先使用新版 SkillDefinition 的 render_prompt()
            skill_def = cls._def_registry.get(skill_id)
            if skill_def:
                _is_domain = (
                    getattr(skill_def.category, "value", skill_def.category) == "domain"
                )
                p = skill_def.render_prompt(
                    with_examples=_is_domain,
                    with_output_spec=_is_domain,
                ).strip()
            else:
                p = s.get("prompt", "").strip()

            if skill_id == "divination" and p:
                p = cls._normalize_divination_prompt(p, user_input)

            if p:
                # 注入 plan_template（仅在 prompt 中尚未包含执行步骤时追加，避免重复）
                pt = (
                    getattr(skill_def, "plan_template", None) if skill_def else None
                ) or s.get("plan_template", [])
                if pt and "执行步骤" not in p:
                    p = p + (
                        "\n\n### ⚙️ 执行步骤（必须严格按顺序完成）\n"
                        + "\n".join(f"{i+1}. {step}" for i, step in enumerate(pt))
                    )
                active_prompts.append(p)

            _inject_skill_count += 1

            # ── Word 模板 skill：追加模板字段说明 ─────────────────────────────
            tmpl_path_rel = s.get("template_path")
            if tmpl_path_rel:
                try:
                    import sys as _sys
                    from pathlib import Path as _Path

                    _base = (
                        _Path(_sys.executable).parent
                        if getattr(_sys, "frozen", False)
                        else _Path(__file__).resolve().parents[3]
                    )
                    tmpl_abs = _base / tmpl_path_rel
                    if not tmpl_abs.exists():
                        # 也尝试约定路径
                        tmpl_abs = (
                            _base
                            / "config"
                            / "skill_templates"
                            / skill_id
                            / "template.docx"
                        )
                    if tmpl_abs.exists():
                        from app.core.skills.template_engine import TemplateEngine

                        fields = TemplateEngine.parse_fields(tmpl_abs)
                        preview = TemplateEngine.get_raw_text(tmpl_abs)
                        tmpl_prompt = TemplateEngine.build_agent_prompt(
                            s.get("name", skill_id), fields, preview
                        )
                        active_prompts.append(tmpl_prompt)
                except Exception as _te:
                    logger.debug(f"[SkillManager] 模板提示注入跳过 ({skill_id}): {_te}")

        # ── 临时 Skill 注入（AutoMatcher 推荐，本轮生效，不改变持久状态）────
        auto_prompts = []
        _temp_ids = temp_skill_ids or []
        for skill_id in _temp_ids:
            if skill_id in seen_ids:
                continue  # 已作为用户启用 Skill 注入过，无需重复
            seen_ids.add(skill_id)
            s = cls._registry.get(skill_id)
            if not s:
                logger.debug(f"[SkillManager] 临时 Skill 不存在，跳过: {skill_id}")
                continue
            skill_def = cls._def_registry.get(skill_id)
            if skill_def:
                _is_domain = (
                    getattr(skill_def.category, "value", skill_def.category) == "domain"
                )
                p = skill_def.render_prompt(
                    with_examples=_is_domain,
                    with_output_spec=_is_domain,
                ).strip()
            else:
                p = s.get("prompt", "").strip()
            if skill_id == "divination" and p:
                p = cls._normalize_divination_prompt(p, user_input)
            if p:
                # 临时 skill 也注入 plan_template（不注入 examples，避免 token 浪费）
                pt = getattr(skill_def, "plan_template", None) if skill_def else None
                if pt:
                    p = p + (
                        "\n\n### ⚙️ 执行步骤（必须严格按顺序完成）\n"
                        + "\n".join(f"{i+1}. {step}" for i, step in enumerate(pt))
                    )
                auto_prompts.append(p)
                logger.debug(f"[SkillManager] 🤖 临时注入 Auto-Skill: {skill_id}")

        # ── 协同检测：找出所有已注入 Skill 中存在 synergizes_with 关系的配对 ──
        all_injected_ids = seen_ids  # 含用户启用 + 临时注入
        synergy_lines: List[str] = []
        already_noted: set = set()
        for sid in all_injected_ids:
            s_def = cls._def_registry.get(sid)
            if not s_def:
                continue
            partners = getattr(s_def, "synergizes_with", []) or []
            for partner_id in partners:
                pair_key = tuple(sorted([sid, partner_id]))
                if pair_key in already_noted:
                    continue
                if partner_id not in all_injected_ids:
                    continue
                already_noted.add(pair_key)
                p_def = cls._def_registry.get(partner_id)
                sid_name = s_def.name or sid
                p_name = getattr(p_def, "name", partner_id) if p_def else partner_id
                synergy_lines.append(f"- **{sid_name}** + **{p_name}**")
                logger.debug(f"[SkillManager] 🔗 检测到协同对: {sid} ↔ {partner_id}")

        # 组装注入块：记忆优先放在 skills 前面
        result = base_instruction
        if memory_block:
            result = (
                result + "\n\n─────────────────────────────────────────" + memory_block
            )
        if active_prompts:
            separator = "\n\n─────────────────────────────────────────"
            skills_block = (
                separator
                + "\n## 🎯 当前激活的 Skills（用户自定义行为）\n"
                + "\n".join(active_prompts)
            )
            result = result + skills_block
        if auto_prompts:
            separator = "\n\n─────────────────────────────────────────"
            auto_block = (
                separator
                + "\n## 🤖 自动匹配的 Skills（本轮智能推荐，仅本次生效）\n"
                + "\n".join(auto_prompts)
            )
            result = result + auto_block
        # 追加协同说明块（只在有 2 个以上互相协同的 Skill 时才生成）
        if synergy_lines:
            separator = "\n\n─────────────────────────────────────────"
            synergy_block = (
                separator + "\n## 🔗 协同工作说明\n"
                "以下技能正在协同发挥作用，请在回答中体现它们的互补关系，"
                "不要重复描述各自的工作流程，而是以整体视角输出统一的结果：\n"
                + "\n".join(synergy_lines)
            )
            result = result + synergy_block
        return result

    @classmethod
    def get_active_skill_names(cls, task_type: Optional[str] = None) -> List[str]:
        """返回当前启用的、适用于 task_type 的技能名称列表（含自定义 Skill）"""
        cls._ensure_init()
        names = []
        seen_ids: set = set()
        for skill_id, s in cls._registry.items():
            if skill_id in seen_ids:
                continue
            seen_ids.add(skill_id)
            if not s.get("enabled", False):
                continue
            applicable_types = s.get("task_types", [])
            if not cls._task_type_matches(task_type, applicable_types):
                continue
            names.append(s["name"])
        return names

    @classmethod
    def reload(cls):
        """强制重新加载（settings 文件被外部修改后调用）"""
        cls._initialized = False
        cls._ensure_init()

    # ═══════════════════════════════════════════════════════════════
    # ▼  v2 新增 API（SkillDefinition / MCP / 自定义 Skill 支持）
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def get_definition(cls, skill_id: str) -> Optional[SkillDefinition]:
        """
        返回指定 skill 的完整 SkillDefinition 对象。
        用于路由决策、变量渲染、输出验收。
        """
        cls._ensure_init()
        return cls._def_registry.get(skill_id)

    @classmethod
    def list_definitions(cls) -> Dict[str, SkillDefinition]:
        """Return all SkillDefinition objects without exposing the internal registry."""
        cls._ensure_init()
        return dict(cls._def_registry)

    @classmethod
    def is_enabled(cls, skill_id: str) -> bool:
        """Return the effective enabled state across the v2 definition and runtime view."""
        cls._ensure_init()
        return cls._skill_enabled(skill_id, cls._def_registry.get(skill_id))

    @classmethod
    def get_runtime_entry(cls, skill_id: str) -> Optional[Dict]:
        """Return the merged runtime view used by dict-based call sites while migration is in progress."""
        cls._ensure_init()
        entry = cls._registry.get(skill_id)
        if entry is None and skill_id in cls._def_registry:
            entry = cls._runtime_entry_from_definition(
                cls._def_registry[skill_id],
                existing=None,
            )
            cls._registry[skill_id] = entry
        return dict(entry) if entry else None

    @classmethod
    def list_runtime_entries(cls) -> Dict[str, Dict]:
        """Return a copy of all runtime entries without exposing the internal registry."""
        cls._ensure_init()
        entries: Dict[str, Dict] = {}
        for skill_id in set(cls._registry) | set(cls._def_registry):
            entry = cls._registry.get(skill_id)
            if entry is None and skill_id in cls._def_registry:
                entry = cls._runtime_entry_from_definition(
                    cls._def_registry[skill_id],
                    existing=None,
                )
                cls._registry[skill_id] = entry
            if entry:
                entries[skill_id] = dict(entry)
        return entries

    @classmethod
    def update_runtime_fields(
        cls, skill_id: str, *, remove_fields: Optional[List[str]] = None, **changes
    ) -> bool:
        """Update runtime metadata through one sync point while external callers migrate off _registry."""
        cls._ensure_init()
        entry = cls._registry.get(skill_id)
        if entry is None:
            skill_def = cls._def_registry.get(skill_id)
            if skill_def is None:
                return False
            entry = cls._runtime_entry_from_definition(skill_def, existing=None)
            cls._registry[skill_id] = entry
        for field in remove_fields or []:
            entry.pop(field, None)
        entry.update(changes)
        cls._save_states_to_settings()
        return True

    @classmethod
    def list_mcp_tools(cls) -> List[Dict]:
        """
        将所有 **已启用** 的 Skill 导出为 MCP (Model Context Protocol) 兼容的
        Tool 描述列表，可直接传给支持 MCP 的 LLM host 或外部系统。
        """
        cls._ensure_init()
        tools = []
        for skill_id, skill_def in cls._def_registry.items():
            if cls._skill_enabled(skill_id, skill_def):
                tools.append(skill_def.to_mcp_tool())
        return tools

    @classmethod
    def list_all_mcp_tools(cls) -> List[Dict]:
        """
        导出所有 Skill（不论是否启用）的 MCP Tool 描述列表。
        用于 Studio / Marketplace 展示。
        """
        cls._ensure_init()
        return [skill_def.to_mcp_tool() for skill_def in cls._def_registry.values()]

    @classmethod
    def register_custom(cls, skill_def: SkillDefinition) -> bool:
        """
        注册一个新的自定义 Skill（运行时动态注册）。
        同时写入 _registry 和 _def_registry，并持久化到 config/skills/{id}.json。

        Args:
            skill_def: 完整的 SkillDefinition 对象

        Returns:
            True 成功，False 失败（id 已存在于 builtin 且 author=="builtin" 时拒绝覆盖）
        """
        cls._ensure_init()
        existing = cls._def_registry.get(skill_def.id)
        if existing and existing.author == "builtin":
            logger.warning(
                f"[SkillManager] 拒绝覆盖内置 Skill: {skill_def.id}。"
                f"如需修改内置 Skill，请先 fork 并使用不同 id。"
            )
            return False

        skill_def.author = skill_def.author or "user"
        cls._def_registry[skill_def.id] = skill_def
        cls._registry[skill_def.id] = cls._runtime_entry_from_definition(
            skill_def,
            existing=cls._registry.get(skill_def.id),
            enabled=skill_def.enabled,
            prompt=skill_def.render_prompt(),
        )

        cls._apply_default_triggers(skill_def)

        # 持久化到 config/skills/{id}.json
        cls._persist_custom_skill(skill_def)
        logger.info(
            f"[SkillManager] ✅ 注册自定义 Skill: {skill_def.id} (v{skill_def.version})"
        )
        return True

    @classmethod
    def uninstall_custom_skill(cls, skill_id: str) -> bool:
        """
        卸载一个自定义 Skill。
        从内存注销并删除 config/skills/{id}.json，同时清除对应的配置。
        """
        cls._ensure_init()

        # 1. 检查是否存在且非内置
        skill_def = cls._def_registry.get(skill_id)
        if not skill_def:
            return False

        if getattr(skill_def, "author", "") == "builtin":
            logger.warning(f"[SkillManager] 拒绝卸载内置 Skill: {skill_id}")
            return False

        # 2. 从内存中移除
        cls._def_registry.pop(skill_id, None)
        cls._registry.pop(skill_id, None)

        # 3. 清理 user_settings 中的配置信息
        try:
            p = cls._settings_path()
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "skills" in data and skill_id in data["skills"]:
                    del data["skills"][skill_id]
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[SkillManager] 卸载时清理设置失败: {e}")

        # 4. 删除物理文件
        try:
            skills_dir = cls._settings_path().parent / "skills"
            skill_file = skills_dir / f"{skill_id}.json"
            if skill_file.exists():
                skill_file.unlink()
        except Exception as e:
            logger.error(f"[SkillManager] 卸载时删除物理文件失败: {e}")
            return False

        # 5. 解绑绑定的触发器（可选，如果不在此处处理也OK，依赖系统的懒惰清理）
        try:
            from app.core.skills.skill_trigger_binding import get_skill_binding_manager

            binding_manager = get_skill_binding_manager()
            binding_manager.unbind_all_for_skill(skill_id)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Silenced exception caught", exc_info=True
            )  # 若没启用该管理器也不影响

        logger.info(f"[SkillManager] ✅ 成功卸载自定义 Skill: {skill_id}")
        return True

    @classmethod
    def _apply_default_triggers(cls, skill_def: SkillDefinition):
        """Register manifest v2 default triggers once per skill/config pair."""
        default_triggers = list(getattr(skill_def, "default_triggers", None) or [])
        if not default_triggers:
            return

        try:
            from app.core.skills.skill_trigger_binding import get_skill_binding_manager

            binding_manager = get_skill_binding_manager()
            existing = binding_manager.list_bindings(
                skill_id=skill_def.id,
                binding_type="trigger",
            )
            existing_keys = {
                (
                    binding.trigger_type,
                    json.dumps(
                        binding.trigger_config or {}, sort_keys=True, ensure_ascii=False
                    ),
                )
                for binding in existing
            }

            for trigger in default_triggers:
                trigger_type = (
                    trigger.get("trigger_type") or trigger.get("type") or ""
                ).strip()
                trigger_config = trigger.get("config") or {}
                if not trigger_type:
                    continue

                trigger_key = (
                    trigger_type,
                    json.dumps(trigger_config, sort_keys=True, ensure_ascii=False),
                )
                if trigger_key in existing_keys:
                    continue

                binding_manager.bind_trigger(
                    skill_id=skill_def.id,
                    trigger_type=trigger_type,
                    trigger_config=trigger_config,
                    mode=trigger.get("mode", "execute"),
                    job_payload=trigger.get("job_payload")
                    or {
                        "skill_id": skill_def.id,
                        "query": trigger.get("query") or f"执行技能: {skill_def.name}",
                    },
                    name=trigger.get("name"),
                )
                existing_keys.add(trigger_key)
        except Exception as exc:
            logger.warning(f"[SkillManager] 应用默认触发器失败: {exc}")

    @classmethod
    def _persist_custom_skill(cls, skill_def: SkillDefinition):
        """将自定义 Skill 写入 config/skills/{id}.json"""
        try:
            skills_dir = cls._settings_path().parent / "skills"
            skills_dir.mkdir(parents=True, exist_ok=True)
            skill_file = skills_dir / f"{skill_def.id}.json"
            with open(skill_file, "w", encoding="utf-8") as f:
                json.dump(skill_def.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[SkillManager] 自定义 Skill 持久化失败: {e}")

    @classmethod
    def _load_custom_skills_dir(cls):
        """从 config/skills/ 目录加载所有自定义 Skill JSON 文件"""
        import sys

        dirs_to_scan: list[Path] = []
        # 打包模式：先扫描 _internal/config/skills/（bundled 默认技能，低优先级）
        if getattr(sys, "frozen", False):
            bundle_skills = Path(sys._MEIPASS) / "config" / "skills"
            if bundle_skills.exists():
                dirs_to_scan.append(bundle_skills)
        # 再扫描 exe 旁 config/skills/（用户自定义，高优先级可覆盖）
        user_skills = cls._settings_path().parent / "skills"
        if user_skills.exists():
            dirs_to_scan.append(user_skills)

        if not dirs_to_scan:
            return

        for skills_dir in dirs_to_scan:
            try:
                for skill_file in skills_dir.glob("*.json"):
                    try:
                        with open(skill_file, "r", encoding="utf-8-sig") as f:
                            data = json.load(f)
                        skill_def = SkillDefinition.from_dict(data)
                        if skill_def.id in cls._def_registry:
                            # 已有内置注册：将 JSON 文件的增强字段合并进去
                            # （trigger_keywords / plan_template / executor_tools / examples / prompt）
                            # 保留 enabled 状态由 _load_states_from_settings 管理，不从 JSON 覆盖
                            existing = cls._def_registry[skill_def.id]
                            if skill_def.trigger_keywords:
                                existing.trigger_keywords = skill_def.trigger_keywords
                            if skill_def.plan_template:
                                existing.plan_template = skill_def.plan_template
                            if skill_def.executor_tools:
                                existing.executor_tools = skill_def.executor_tools
                            if skill_def.examples:
                                existing.examples = skill_def.examples
                            if skill_def.prompt:
                                existing.prompt = skill_def.prompt
                                # 同步到 _registry 的 prompt 字段
                                reg_entry = cls._registry.get(skill_def.id)
                                if reg_entry:
                                    reg_entry["prompt"] = skill_def.render_prompt()
                                    reg_entry["plan_template"] = skill_def.plan_template
                            # 同步 ui_config / ui_extensions 到 _registry（供 get_active_ui_config 读取）
                            if data.get("ui_config"):
                                reg_entry = cls._registry.get(skill_def.id)
                                if reg_entry is not None:
                                    reg_entry["ui_config"] = data["ui_config"]
                                    reg_entry["priority"] = data.get(
                                        "priority", reg_entry.get("priority", 50)
                                    )
                            if data.get("ui_extensions"):
                                reg_entry = cls._registry.get(skill_def.id)
                                if reg_entry is not None:
                                    reg_entry["ui_extensions"] = data["ui_extensions"]
                            if data.get("permissions"):
                                reg_entry = cls._registry.get(skill_def.id)
                                if reg_entry is not None:
                                    reg_entry["permissions"] = data["permissions"]
                            logger.debug(
                                f"[SkillManager] 合并自定义增强字段到内置 Skill: {skill_def.id}"
                            )
                        else:
                            cls._def_registry[skill_def.id] = skill_def
                            entry = {
                                "id": skill_def.id,
                                "name": skill_def.name,
                                "icon": skill_def.icon,
                                "category": (
                                    skill_def.category.value
                                    if hasattr(skill_def.category, "value")
                                    else skill_def.category
                                ),
                                "skill_nature": data.get(
                                    "skill_nature", "domain_skill"
                                ),
                                "description": skill_def.description,
                                "priority": data.get("priority", 50),
                                "task_types": skill_def.task_types,
                                "prompt": skill_def.render_prompt(),
                                # 始终以 disabled 状态注册；enabled 状态完全由
                                # _load_states_from_settings 从 user_settings.json 恢复，
                                # 不从 JSON 文件直接继承（与 builtin 分支保持一致）。
                                "enabled": False,
                                "plan_template": skill_def.plan_template,
                                "permissions": data.get("permissions", []),
                            }
                            # 保留 template_path 和 bound_tools（若 JSON 中有）
                            if data.get("template_path"):
                                entry["template_path"] = data["template_path"]
                            if data.get("bound_tools"):
                                entry["bound_tools"] = data["bound_tools"]
                            # 保留 ui_config（供 get_active_ui_config 使用）
                            if data.get("ui_config"):
                                entry["ui_config"] = data["ui_config"]
                            # 保留 ui_extensions（供 get_active_ui_config 使用）
                            if data.get("ui_extensions"):
                                entry["ui_extensions"] = data["ui_extensions"]
                            cls._registry[skill_def.id] = entry
                            logger.info(
                                f"[SkillManager] 加载自定义 Skill: {skill_def.id}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"[SkillManager] 加载 {skill_file.name} 失败: {e}"
                        )
            except Exception as e:
                logger.warning(
                    f"[SkillManager] 加载自定义 Skill 目录失败: {skills_dir}: {e}"
                )

    @classmethod
    def validate_output(cls, skill_id: str, text: str) -> tuple:
        """
        使用指定 Skill 的 OutputSpec 验收文本。
        返回 (passed: bool, reason: str)
        若 Skill 不存在或无 OutputSpec，默认通过。
        """
        cls._ensure_init()
        skill_def = cls._def_registry.get(skill_id)
        if not skill_def:
            return True, "Skill 不存在，跳过验收"
        return skill_def.output_spec.validate(text)

    @classmethod
    def get_intent_descriptions(cls) -> Dict[str, str]:
        """
        返回所有已启用 Skill 的 {id: intent_description} 映射。
        供 Qwen Router 在意图识别时参考，提升路由准确性。
        """
        cls._ensure_init()
        result = {}
        for skill_id, skill_def in cls._def_registry.items():
            if cls._skill_enabled(skill_id, skill_def) and skill_def.intent_description:
                result[skill_id] = skill_def.intent_description
        return result

    # ═══════════════════════════════════════════════════════════════
    # ▼  智能推荐：根据用户输入建议相关 Skill
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def suggest_skills(
        cls,
        user_input: str,
        task_type: Optional[str] = None,
        top_k: int = 3,
        exclude_enabled: bool = True,
    ) -> List[Dict]:
        """
        根据用户输入和任务类型，推荐最相关的未启用 Skill。

        算法：
        1. 将 user_input 与每个 Skill 的 intent_description + description + tags 做关键词匹配打分
        2. 同时检查 task_type 适配性
        3. 返回得分最高的 top_k 个 Skill

        Args:
            user_input:     用户当前消息文本
            task_type:      当前任务类型（如 "CHAT", "CODER"）
            top_k:          返回建议数量
            exclude_enabled: True = 只推荐未启用的（让用户决定是否开启）

        Returns:
            [{"id", "name", "icon", "description", "score", "reason"}, ...]
        """
        import re as _re

        cls._ensure_init()
        user_lower = user_input.lower()
        scores: List[Dict] = []

        for skill_id, skill_def in cls._def_registry.items():
            # 排除已启用的（可选）
            if exclude_enabled and cls._skill_enabled(skill_id, skill_def):
                continue

            # 检查 task_type 适配性
            applicable = skill_def.task_types or []
            if not cls._task_type_matches(task_type, applicable):
                continue

            score = 0.0
            matched_reasons: List[str] = []

            # 计算与 intent_description 的相关性
            intent = (skill_def.intent_description or "").lower()
            desc = (skill_def.description or "").lower()
            tags = " ".join(skill_def.tags).lower()
            combined = f"{intent} {desc} {tags}"

            # 词频匹配 — 提取用户输入的关键词
            words = _re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", user_lower)
            for word in words:
                if word in combined:
                    score += 1.0
                    matched_reasons.append(word)

            # 精确短语匹配加权
            for phrase_len in (4, 3, 2):
                for i in range(len(user_lower) - phrase_len + 1):
                    phrase = user_lower[i : i + phrase_len]
                    if phrase in combined:
                        score += phrase_len * 0.5
                        break

            # 名称完全或部分匹配
            skill_name_lower = (skill_def.name or "").lower()
            if any(w in skill_name_lower for w in words if len(w) >= 2):
                score += 2.0
                matched_reasons.append(f"名称匹配: {skill_def.name}")

            if score > 0:
                reason = "与「{name}」相关：{r}".format(
                    name=skill_def.name,
                    r=(
                        "、".join(dict.fromkeys(matched_reasons))[:50]
                        if matched_reasons
                        else "语义相关"
                    ),
                )
                scores.append(
                    {
                        "id": skill_id,
                        "name": skill_def.name,
                        "icon": skill_def.icon,
                        "description": skill_def.description,
                        "score": round(score, 2),
                        "reason": reason,
                        "category": (
                            skill_def.category.value
                            if hasattr(skill_def.category, "value")
                            else skill_def.category
                        ),
                    }
                )

        # 按得分降序排列，取 top_k
        scores.sort(key=lambda x: x["score"], reverse=True)
        return scores[:top_k]

    # ═══════════════════════════════════════════════════════════════
    # ▼  冲突检测：防止相互矛盾的 Skill 同时启用
    # ═══════════════════════════════════════════════════════════════

    # 已知冲突组 — 同组内同时启用 2+ 个则报冲突
    _CONFLICT_GROUPS: List[tuple] = [
        # 详细 vs 精简
        ("step_by_step", "concise_mode"),
        # 正式 vs 随意（无强制，作为警告提示）
        # 高幽默 vs 严谨模式（警告级别）
        ("strict_mode", "emoji_assist"),
    ]
    # 软冲突（警告但不阻止）
    _SOFT_CONFLICTS: Dict[str, List[str]] = {
        "concise_mode": ["step_by_step", "teaching_mode", "proactive_suggestions"],
        "step_by_step": ["concise_mode"],
        "strict_mode": ["creative_writing", "emoji_assist"],
        "creative_writing": ["strict_mode", "professional_tone", "data_analysis"],
        "professional_tone": ["creative_writing"],
    }

    @classmethod
    def detect_conflicts(cls, skill_id: str) -> Dict:
        """
        检测启用 skill_id 后是否与当前其他已启用 Skill 产生冲突。
        综合检查：内置冲突规则表 + SkillDefinition.conflict_with 声明字段

        Returns:
            {
              "has_conflict": bool,
              "hard_conflicts": [{"id", "name", "reason"}, ...],
              "soft_conflicts": [{"id", "name", "reason"}, ...],
            }
        """
        cls._ensure_init()
        hard: List[Dict] = []
        soft: List[Dict] = []

        # 当前已启用集合
        enabled_ids = {
            sid
            for sid, skill_def in cls._def_registry.items()
            if sid != skill_id and cls._skill_enabled(sid, skill_def)
        }

        this_def = cls._def_registry.get(skill_id)
        this_name = this_def.name if this_def else skill_id

        # 声明式 conflict_with 字段检查
        if this_def and this_def.conflict_with:
            for other_id in this_def.conflict_with:
                if other_id in enabled_ids:
                    other_def = cls._def_registry.get(other_id)
                    other_name = other_def.name if other_def else other_id
                    hard.append(
                        {
                            "id": other_id,
                            "name": other_name,
                            "reason": f"「{this_name}」声明与「{other_name}」不兼容",
                        }
                    )

        # 内置硬冲突规则
        hard_ids = {h["id"] for h in hard}
        for group in cls._CONFLICT_GROUPS:
            if skill_id in group:
                others = [g for g in group if g != skill_id]
                for other_id in others:
                    if other_id in enabled_ids and other_id not in hard_ids:
                        other_def = cls._def_registry.get(other_id)
                        other_name = other_def.name if other_def else other_id
                        hard.append(
                            {
                                "id": other_id,
                                "name": other_name,
                                "reason": f"「{this_name}」与「{other_name}」行为相反，同时启用会产生矛盾",
                            }
                        )
                        hard_ids.add(other_id)

        # 软冲突检测
        soft_list = cls._SOFT_CONFLICTS.get(skill_id, [])
        for other_id in soft_list:
            if other_id in enabled_ids and other_id not in hard_ids:
                other_def = cls._def_registry.get(other_id)
                other_name = other_def.name if other_def else other_id
                soft.append(
                    {
                        "id": other_id,
                        "name": other_name,
                        "reason": f"与「{other_name}」可能存在风格不一致，建议选其一",
                    }
                )

        return {
            "has_conflict": bool(hard) or bool(soft),
            "hard_conflicts": hard,
            "soft_conflicts": soft,
        }

    # ═══════════════════════════════════════════════════════════════
    # ▼  响应验收：对 LLM 回复批量验证所有激活 Skill 的 OutputSpec
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def validate_response(
        cls,
        text: str,
        task_type: Optional[str] = None,
    ) -> Dict:
        """
        对 LLM 生成的回复文本，批量检验所有当前激活 Skill 的 OutputSpec。

        Args:
            text:      LLM 生成的回复文本
            task_type: 当前任务类型

        Returns:
            {
              "all_passed": bool,
              "results": [{"skill_id", "skill_name", "passed", "reason"}, ...]
            }
        """
        cls._ensure_init()
        results = []
        all_passed = True

        for skill_id, skill_def in cls._def_registry.items():
            if not cls._skill_enabled(skill_id, skill_def):
                continue
            applicable = skill_def.task_types or []
            if not cls._task_type_matches(task_type, applicable):
                continue
            # 若 OutputSpec 约束为空（默认），跳过
            spec = skill_def.output_spec
            has_constraint = (
                spec.must_contain
                or spec.must_not_contain
                or spec.min_chars
                or spec.max_chars
                or spec.required_json_keys
            )
            if not has_constraint:
                continue

            passed, reason = spec.validate(text)
            if not passed:
                all_passed = False
            results.append(
                {
                    "skill_id": skill_id,
                    "skill_name": skill_def.name,
                    "passed": passed,
                    "reason": reason,
                }
            )

        return {"all_passed": all_passed, "results": results}

    # ═══════════════════════════════════════════════════════════════
    # ▼  Skill 摘要：供调试 / UI 状态面板使用
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def get_status_summary(cls) -> Dict:
        """
        返回当前 Skill 库的完整状态摘要，供 UI/日志使用。
        """
        cls._ensure_init()
        total = len(cls._def_registry)
        enabled = sum(1 for s in cls._registry.values() if s.get("enabled", False))
        builtin_count = sum(
            1 for s in cls._def_registry.values() if s.author == "builtin"
        )
        custom_count = total - builtin_count
        active_names = cls.get_active_skill_names()

        return {
            "total": total,
            "enabled": enabled,
            "builtin": builtin_count,
            "custom": custom_count,
            "active_skill_names": active_names,
            "version": "2.1",
        }
