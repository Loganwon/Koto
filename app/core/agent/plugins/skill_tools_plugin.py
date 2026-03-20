"""
SkillToolsPlugin — 向 UnifiedAgent 暴露 Skill 管理工具。

注册的工具:
  - save_as_skill(skill_name, description, user_input, ai_response)
      从用户输入 + AI 回复中提取并保存一个新 Skill，立即生效。
  - list_skills(category)
      列出当前已加载的所有 Skill，可按分类过滤。
  - enable_skill(skill_id) / disable_skill(skill_id)
      动态启用 / 停用某个 Skill。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.agent.base import AgentPlugin

logger = logging.getLogger(__name__)


class SkillToolsPlugin(AgentPlugin):
    """Agent plugin for managing and creating Skills at runtime."""

    @property
    def name(self) -> str:
        return "SkillTools"

    @property
    def description(self) -> str:
        return "Tools for creating, listing and toggling Koto Skills."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "save_as_skill",
                "func": self.save_as_skill,
                "description": (
                    "将当前对话内容或用户提供的输入/输出示例保存为一个新的 Skill，"
                    "保存后立即注册并可在后续对话中复用。"
                    "当用户说「把这段对话保存为技能」「保存为 skill」「记住这个能力」时调用。"
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "skill_name": {
                            "type": "STRING",
                            "description": "Skill 的名称，例如「邮件润色助手」「SQL 优化专家」。",
                        },
                        "description": {
                            "type": "STRING",
                            "description": "简短描述该 Skill 的用途（1-2 句话）。",
                        },
                        "user_input": {
                            "type": "STRING",
                            "description": "作为 Skill 样本的用户输入（原始请求），可留空则自动从本轮对话提取。",
                        },
                        "ai_response": {
                            "type": "STRING",
                            "description": "对应的 AI 回复示例，可留空则自动从本轮对话提取。",
                        },
                        "overwrite": {
                            "type": "BOOLEAN",
                            "description": "若同名 Skill 已存在，是否覆盖（默认 false）。",
                        },
                        "permissions": {
                            "type": "ARRAY",
                            "description": (
                                "可选。声明该 Skill 需要的权限列表，用户启用后会看到授权提示。"
                                "可选值：ui_style | ui_interactive | notifications | "
                                "clipboard_read | clipboard_write | storage | autorun。"
                                "示例：[\"ui_interactive\"]"
                            ),
                        },
                        "ui_extensions": {
                            "type": "OBJECT",
                            "description": (
                                "可选。UI 交互扩展配置，需要 permissions 包含 'ui_interactive'。"
                                "支持三个子字段："
                                "action_buttons（输入框上方按钮列表），"
                                "quick_replies（AI 回复后快速回复芯片列表），"
                                "floating_widget（浮动面板，type 可选：dice_roller/timer/notes/calculator/word_counter/color_picker）。"
                            ),
                        },
                    },
                    "required": ["skill_name", "description"],
                },
            },
            {
                "name": "list_skills",
                "func": self.list_skills,
                "description": (
                    "列出当前已加载的全部 Skill，包含 ID、名称、启用状态和描述。"
                    "当用户问「有哪些技能」「技能列表」「我能用哪些 skill」时调用。"
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "category": {
                            "type": "STRING",
                            "description": (
                                "按分类过滤，可选值：style / domain / workflow / custom。"
                                "留空则返回全部。"
                            ),
                        },
                        "enabled_only": {
                            "type": "BOOLEAN",
                            "description": "仅返回已启用的 Skill（默认 false）。",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "enable_skill",
                "func": self.enable_skill,
                "description": (
                    "启用指定 ID 的 Skill，使其在后续对话中持续生效。"
                    "当用户说「启用 xxx 技能」「开启 xxx」时调用。"
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "skill_id": {
                            "type": "STRING",
                            "description": "要启用的 Skill ID。",
                        },
                    },
                    "required": ["skill_id"],
                },
            },
            {
                "name": "disable_skill",
                "func": self.disable_skill,
                "description": (
                    "停用指定 ID 的 Skill。"
                    "当用户说「关闭 xxx 技能」「停用 xxx」时调用。"
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "skill_id": {
                            "type": "STRING",
                            "description": "要停用的 Skill ID。",
                        },
                    },
                    "required": ["skill_id"],
                },
            },
            {
                "name": "grant_skill_permission",
                "func": self.grant_skill_permission,
                "description": (
                    "为指定 Skill 授予某个权限，让其 UI 交互功能生效。"
                    "仅在用户明确表示同意授予权限时调用（例如用户回复「同意」「授权」「允许」）。"
                    "不要在未经用户确认时自动调用此工具。"
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "skill_id": {
                            "type": "STRING",
                            "description": "要授权的 Skill ID。",
                        },
                        "permission": {
                            "type": "STRING",
                            "description": (
                                "权限名称。可选值："
                                "ui_style（修改主题）| ui_interactive（UI 交互控件）| "
                                "notifications（系统通知）| clipboard_read（读剪贴板）| "
                                "clipboard_write（写剪贴板）| storage（本地存储）| autorun（自动执行）"
                            ),
                        },
                    },
                    "required": ["skill_id", "permission"],
                },
            },
        ]

    # ── 工具实现 ──────────────────────────────────────────────────────────────

    def save_as_skill(
        self,
        skill_name: str,
        description: str,
        user_input: str = "",
        ai_response: str = "",
        overwrite: bool = False,
        permissions: list = None,
        ui_extensions: dict = None,
    ) -> str:
        """从输入/输出示例或当前对话保存一个新 Skill（含 LLM 语义分析）。

        Args:
            permissions   : 可选列表，声明 Skill 需要的权限。例如 ["ui_interactive"]。
                            可用值：ui_style | ui_interactive | notifications |
                                     clipboard_read | clipboard_write | storage | autorun
            ui_extensions : 可选字典，UI 交互扩展配置（需要 ui_interactive 权限）。
                            支持三个子字段：
                              action_buttons  —— 输入框上方的快捷按钮列表
                              quick_replies   —— AI 回复后出现的快速回复芯片
                              floating_widget —— 可拖动浮动面板（type: dice_roller/timer/notes/calculator/word_counter/color_picker）
        """
        try:
            from app.core.skills.skill_recorder import SkillRecorder

            if user_input and ai_response:
                skill_def = SkillRecorder.from_text(
                    user_input=user_input,
                    ai_response=ai_response,
                    skill_name=skill_name,
                    description=description,
                    use_ai_analysis=True,
                )
            elif user_input:
                skill_def = SkillRecorder.from_text(
                    user_input=user_input,
                    ai_response=description,
                    skill_name=skill_name,
                    description=description,
                    use_ai_analysis=True,
                )
            else:
                skill_def = SkillRecorder.from_text(
                    user_input=f"请按照「{skill_name}」的方式处理以下内容：",
                    ai_response=description,
                    skill_name=skill_name,
                    description=description,
                    use_ai_analysis=False,  # 无对话内容时跳过分析
                )

            # 注入权限和 UI 扩展字段
            if permissions and isinstance(permissions, list):
                skill_def.permissions = permissions
            if ui_extensions and isinstance(ui_extensions, dict):
                skill_def.ui_extensions = ui_extensions

            skill_id = SkillRecorder.save_and_register(skill_def, overwrite=overwrite)

            # 展示 LLM 提取的元数据
            meta_lines = []
            if skill_def.intent_description:
                meta_lines.append(f"  - 🎯 触发意图: {skill_def.intent_description}")
            if skill_def.task_types:
                meta_lines.append(f"  - 📋 任务类型: {', '.join(skill_def.task_types)}")
            if skill_def.tags:
                meta_lines.append(f"  - 🏷️ 关键标签: {', '.join(skill_def.tags)}")
            trigger_kws = getattr(skill_def, "trigger_keywords", None) or []
            if trigger_kws:
                meta_lines.append(f"  - 🔑 触发关键词: {', '.join(trigger_kws)}")
            exec_tools = getattr(skill_def, "executor_tools", None) or []
            if exec_tools:
                meta_lines.append(f"  - 🔧 执行工具: {', '.join(exec_tools)}")
            plan = getattr(skill_def, "plan_template", None) or []
            if plan:
                plan_str = "\n".join(f"    {i+1}. {s}" for i, s in enumerate(plan))
                meta_lines.append(f"  - ⚙️ 执行步骤:\n{plan_str}")
            if skill_def.permissions:
                meta_lines.append(f"  - 🔐 权限声明: {', '.join(skill_def.permissions)}")
            if skill_def.ui_extensions:
                ext = skill_def.ui_extensions
                parts = []
                if ext.get("action_buttons"):
                    parts.append(f"{len(ext['action_buttons'])} 个操作按钮")
                if ext.get("quick_replies"):
                    parts.append(f"{len(ext['quick_replies'])} 个快速回复")
                if ext.get("floating_widget"):
                    parts.append(f"浮动面板 ({ext['floating_widget'].get('type', '?')})")
                if parts:
                    meta_lines.append(f"  - 🎛️ UI 扩展: {', '.join(parts)}")
            analysis_note = (
                "\n**语义分析结果:**\n" + "\n".join(meta_lines)
                if meta_lines else "\n（未进行 LLM 语义分析，使用规则提取）"
            )

            perm_note = ""
            if skill_def.permissions:
                perm_note = (
                    f"\n\n> ⚠️ 该 Skill 声明了权限 `{', '.join(skill_def.permissions)}`。"
                    f"用户在启用后需要在「技能设置」中授予权限，UI 交互功能才会生效。"
                )

            return (
                f"✅ Skill 已保存并注册！\n"
                f"- ID: `{skill_id}`\n"
                f"- 名称: {skill_name}\n"
                f"- 描述: {skill_def.description}"
                f"{analysis_note}"
                f"{perm_note}\n\n"
                f"该 Skill 已立即生效，后续对话将自动识别并注入。"
            )

        except FileExistsError as e:
            return (
                f"⚠️ Skill 已存在：{e}\n"
                f"如需覆盖，请将 overwrite 参数设为 true 重新调用。"
            )
        except Exception as e:
            logger.warning(f"[SkillToolsPlugin] save_as_skill 失败: {e}")
            return f"❌ 保存失败：{e}"

    def grant_skill_permission(self, skill_id: str, permission: str) -> str:
        """为指定 Skill 授予某个权限（需要用户明确同意才调用）。

        Args:
            skill_id   : Skill ID
            permission : 权限名称，可选：ui_style | ui_interactive | notifications |
                                         clipboard_read | clipboard_write | storage | autorun
        """
        try:
            from app.core.skills.skill_permissions import SkillPermissionManager, PERMISSION_META
            from app.core.skills.skill_manager import SkillManager

            if permission not in PERMISSION_META:
                valid = ', '.join(PERMISSION_META.keys())
                return f"❌ 未知权限 `{permission}`。可用权限：{valid}"

            SkillManager._ensure_init()
            if skill_id not in SkillManager._registry:
                return f"❌ 未找到 Skill ID: `{skill_id}`"

            SkillPermissionManager.grant(skill_id, permission)
            meta = PERMISSION_META[permission]
            name = SkillManager._registry[skill_id].get("name", skill_id)
            return (
                f"✅ 已为「{name}」(`{skill_id}`) 授予权限：**{meta['label']}**\n"
                f"  - 说明：{meta['description']}\n"
                f"  - 风险等级：{meta['risk']}"
            )
        except Exception as e:
            logger.warning(f"[SkillToolsPlugin] grant_skill_permission 失败: {e}")
            return f"❌ 授权失败：{e}"

    def list_skills(
        self,
        category: Optional[str] = None,
        enabled_only: bool = False,
    ) -> str:
        """列出已加载的 Skill。"""
        try:
            from app.core.skills.skill_manager import SkillManager
            SkillManager._ensure_init()
            rows = []
            for sid, s in SkillManager._registry.items():
                if category and s.get("category", "") != category:
                    continue
                if enabled_only and not s.get("enabled", False):
                    continue
                status = "✅" if s.get("enabled") else "○"
                rows.append(
                    f"{status} `{sid}` — {s.get('name', sid)}: "
                    f"{s.get('description', '')[:60]}"
                )
            if not rows:
                return "（没有找到符合条件的 Skill）"
            return "\n".join(rows)
        except Exception as e:
            logger.warning(f"[SkillToolsPlugin] list_skills 失败: {e}")
            return f"❌ 读取 Skill 列表失败：{e}"

    def enable_skill(self, skill_id: str) -> str:
        """启用指定 Skill。"""
        try:
            from app.core.skills.skill_manager import SkillManager
            SkillManager._ensure_init()
            if skill_id not in SkillManager._registry:
                return f"❌ 未找到 Skill ID: `{skill_id}`，请先用 list_skills 确认正确 ID。"
            SkillManager._registry[skill_id]["enabled"] = True
            name = SkillManager._registry[skill_id].get("name", skill_id)
            return f"✅ 已启用 Skill：**{name}** (`{skill_id}`)"
        except Exception as e:
            logger.warning(f"[SkillToolsPlugin] enable_skill 失败: {e}")
            return f"❌ 启用失败：{e}"

    def disable_skill(self, skill_id: str) -> str:
        """停用指定 Skill。"""
        try:
            from app.core.skills.skill_manager import SkillManager
            SkillManager._ensure_init()
            if skill_id not in SkillManager._registry:
                return f"❌ 未找到 Skill ID: `{skill_id}`，请先用 list_skills 确认正确 ID。"
            SkillManager._registry[skill_id]["enabled"] = False
            name = SkillManager._registry[skill_id].get("name", skill_id)
            return f"✅ 已停用 Skill：**{name}** (`{skill_id}`)"
        except Exception as e:
            logger.warning(f"[SkillToolsPlugin] disable_skill 失败: {e}")
            return f"❌ 停用失败：{e}"
