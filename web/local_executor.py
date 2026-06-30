# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
local_executor.py — 本地系统信息执行器

让 Koto 能够：获取系统时间/日期/状态等低风险本地信息。
所有方法均为 classmethod，无需实例化。
不依赖 web/app.py 的任何模块级变量，可以独立导入。

从 web/app.py 的内联 LocalExecutor 类提取 (2026-03-09)。
"""

from __future__ import annotations

class LocalExecutor:
    """
    本地系统信息执行器。
    高风险的系统原生打开、应用控制、电源操作、按键模拟已移除。
    """

    # 知识提问模式 —— 如果匹配到这些，说明用户是在**问问题**，不是在下命令
    QUESTION_PATTERNS = [
        "怎么",
        "如何",
        "什么办法",
        "什么方法",
        "什么意思",
        "什么是",
        "是什么",
        "为什么",
        "为啥",
        "能不能",
        "可以吗",
        "可不可以",
        "怎样",
        "咋",
        "一般用",
        "通常",
        "有没有",
        "有什么",
        "哪些",
        "哪个",
        "哪种",
        "区别",
        "对比",
        "比较",
        "最好的",
        "推荐",
        "建议",
        "教程",
        "步骤",
        "流程",
        "原理",
        "概念",
        "用什么",
        "是啥",
        "啥意思",
        "讲讲",
        "说说",
        "介绍",
        "how to",
        "what is",
        "why",
        "which",
        "recommend",
        "difference between",
        "best way",
        "tutorial",
    ]

    @classmethod
    def is_system_command(cls, text):
        """检测是否是系统操作请求（祈使句/命令句，非知识提问）"""
        text_lower = text.lower().strip()

        if any(qp in text_lower for qp in cls.QUESTION_PATTERNS):
            return False

        if len(text_lower) > 30:
            return False

        action_keywords = [
            "时间",
            "几点",
            "日期",
            "几号",
            "星期几",
            "time",
            "date",
            "状态",
            "信息",
            "配置",
            "内存",
            "cpu",
            "硬盘",
        ]
        has_action = any(kw in text_lower for kw in action_keywords)
        if not has_action:
            return False

        standalone_commands = [
            "时间",
            "几点",
            "日期",
            "几号",
            "星期几",
            "time",
            "date",
            "系统状态",
            "电脑状态",
            "系统信息",
            "电脑信息",
            "配置",
            "内存",
            "cpu",
            "硬盘",
        ]
        is_standalone = any(cmd in text_lower for cmd in standalone_commands)
        return is_standalone

    @classmethod
    def execute(cls, user_input):
        """执行系统操作"""
        text_lower = user_input.lower()
        result = {"success": False, "action": "", "message": "", "details": ""}

        # === 系统时间/日期 ===
        if any(
            kw in text_lower
            for kw in ["时间", "几点", "日期", "几号", "星期几", "time", "date"]
        ):
            import datetime

            now = datetime.datetime.now()
            weekdays = [
                "星期一",
                "星期二",
                "星期三",
                "星期四",
                "星期五",
                "星期六",
                "星期日",
            ]
            weekday_str = weekdays[now.weekday()]

            if any(kw in text_lower for kw in ["日期", "几号", "星期几", "date"]):
                time_str = now.strftime(f"%Y年%m月%d日 {weekday_str}")
                msg = f"📅 当前日期是：{time_str}"
            else:
                time_str = now.strftime(f"%Y-%m-%d %H:%M:%S {weekday_str}")
                msg = f"🕒 当前系统时间是：{time_str}"

            result["success"] = True
            result["action"] = "get_time"
            result["message"] = msg
            return result

        # === 系统状态 ===
        if any(
            kw in text_lower
            for kw in [
                "系统状态",
                "电脑状态",
                "系统信息",
                "电脑信息",
                "配置",
                "内存",
                "cpu",
                "硬盘",
            ]
        ):
            info = cls.get_system_info()
            if info.get("success"):
                mem = info.get("memory", {})
                disk = info.get("disk", {})
                msg = (
                    f"💻 **系统状态报告**\n\n"
                    f"- **操作系统**: {info.get('system')} ({info.get('platform')})\n"
                    f"- **处理器**: {info.get('processor')}\n"
                    f"- **CPU 使用率**: {info.get('cpu_percent')}%\n"
                    f"- **内存**: 已用 {mem.get('percent')}% (剩余 {mem.get('available')} / 总共 {mem.get('total')})\n"
                    f"- **C盘**: 已用 {disk.get('percent')}% (剩余 {disk.get('free')} / 总共 {disk.get('total')})\n"
                )
                result["success"] = True
                result["action"] = "get_system_info"
                result["message"] = msg
                return result

        result["message"] = "❓ 无法识别该系统操作"
        return result

    @classmethod
    def get_clipboard(cls):
        """获取剪贴板内容"""
        try:
            import pyperclip

            content = pyperclip.paste()
            return {
                "success": True,
                "content": content,
                "length": len(content),
                "message": f"✅ 已获取剪贴板内容 ({len(content)} 字符)",
            }
        except Exception as e:
            return {
                "success": False,
                "content": "",
                "message": f"❌ 无法读取剪贴板: {str(e)}",
            }

    @classmethod
    def set_clipboard(cls, text):
        """设置剪贴板内容"""
        try:
            import pyperclip

            pyperclip.copy(text)
            return {"success": True, "message": f"✅ 已复制到剪贴板 ({len(text)} 字符)"}
        except Exception as e:
            return {"success": False, "message": f"❌ 无法写入剪贴板: {str(e)}"}

    @classmethod
    def get_system_info(cls):
        """获取系统信息"""
        try:
            import platform

            import psutil

            return {
                "success": True,
                "system": platform.system(),
                "platform": platform.platform(),
                "processor": platform.processor(),
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory": {
                    "total": f"{psutil.virtual_memory().total / (1024**3):.2f} GB",
                    "available": f"{psutil.virtual_memory().available / (1024**3):.2f} GB",
                    "percent": psutil.virtual_memory().percent,
                },
                "disk": {
                    "total": f"{psutil.disk_usage('/').total / (1024**3):.2f} GB",
                    "free": f"{psutil.disk_usage('/').free / (1024**3):.2f} GB",
                    "percent": psutil.disk_usage("/").percent,
                },
            }
        except Exception as e:
            return {"success": False, "message": f"❌ 无法获取系统信息: {str(e)}"}

    @classmethod
    def list_running_apps(cls):
        """列出正在运行的应用"""
        try:
            import psutil

            apps = []
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    apps.append({"name": proc.info["name"], "pid": proc.info["pid"]})
                except Exception:
                    continue
            return {
                "success": True,
                "apps": apps[:30],
                "count": len(apps),
                "message": f"✅ 找到 {len(apps)} 个运行中的进程",
            }
        except Exception as e:
            return {"success": False, "message": f"❌ 无法列出应用: {str(e)}"}

