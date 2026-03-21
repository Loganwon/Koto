"""
示例工具文件 — 简易笔记管理
将此文件重命名为 example_notes.py（去掉开头的 _）即可激活。

激活后，你可以对 Koto 说：
  "帮我记一条笔记，标题是'明天事项'，内容是'开会、买菜、健身'"
  "列出我的所有笔记"
  "读取笔记'明天事项'"
  "删除笔记'明天事项'"
"""
import json
import os

from app.core.tools.user_tool_loader import koto_tool

_NOTES_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "workspace", "my_notes.json")


def _load() -> dict:
    if os.path.exists(_NOTES_FILE):
        with open(_NOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(notes: dict) -> None:
    os.makedirs(os.path.dirname(_NOTES_FILE), exist_ok=True)
    with open(_NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)


@koto_tool(
    description="保存一条笔记到本地文件，可以记录任何信息",
    parameters={
        "title": {"type": "STRING", "description": "笔记标题（作为唯一 ID）"},
        "content": {"type": "STRING", "description": "笔记内容"},
    },
    required=["title", "content"],
)
def save_note(title: str, content: str) -> str:
    notes = _load()
    notes[title] = content
    _save(notes)
    return f"笔记 '{title}' 已保存（共 {len(notes)} 条）"


@koto_tool(
    description="列出所有已保存的笔记标题",
    parameters={},
)
def list_notes() -> str:
    notes = _load()
    if not notes:
        return "还没有保存任何笔记"
    lines = [f"共 {len(notes)} 条笔记："] + [f"- {t}" for t in notes.keys()]
    return "\n".join(lines)


@koto_tool(
    description="读取指定标题的笔记内容",
    parameters={
        "title": {"type": "STRING", "description": "要读取的笔记标题"},
    },
    required=["title"],
)
def read_note(title: str) -> str:
    notes = _load()
    if title not in notes:
        all_titles = ", ".join(notes.keys()) or "（无）"
        return f"找不到笔记 '{title}'。现有笔记：{all_titles}"
    return f"**{title}**\n\n{notes[title]}"


@koto_tool(
    description="删除指定标题的笔记",
    parameters={
        "title": {"type": "STRING", "description": "要删除的笔记标题"},
    },
    required=["title"],
)
def delete_note(title: str) -> str:
    notes = _load()
    if title not in notes:
        return f"找不到笔记 '{title}'，无法删除"
    del notes[title]
    _save(notes)
    return f"笔记 '{title}' 已删除（剩余 {len(notes)} 条）"
