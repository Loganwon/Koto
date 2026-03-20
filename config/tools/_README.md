# Koto 自定义工具系统 — `config/tools/`

在这个目录里放 `.py` 文件，用 `@koto_tool` 装饰器注册函数，就能变成 AI 可以直接调用的工具。

文件名以 `_` 开头的会被跳过（可用于禁用或草稿）。

---

## 基本用法

```python
from app.core.tools.user_tool_loader import koto_tool

@koto_tool(
    description="搜索我的笔记",
    parameters={
        "query": {
            "type": "STRING",
            "description": "搜索关键词"
        }
    },
    required=["query"]
)
def search_my_notes(query: str) -> str:
    # 你的逻辑
    results = []
    # ... 搜索代码 ...
    return "\n".join(results) if results else "没有找到相关笔记"
```

---

## `@koto_tool` 参数说明

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `description` | str | ✅ | 工具的功能描述，AI 会用它判断何时调用 |
| `parameters` | dict | ❌ | 参数定义，键为参数名，值为 `{type, description}` 字典 |
| `required` | list | ❌ | 必填参数名列表 |

### 支持的参数类型
- `"STRING"` — 文本
- `"INTEGER"` — 整数
- `"NUMBER"` — 浮点数
- `"BOOLEAN"` — 布尔值

---

## 完整示例

```python
from app.core.tools.user_tool_loader import koto_tool
import json, os

NOTES_FILE = os.path.expanduser("~/my_notes.json")

@koto_tool(
    description="将内容保存为笔记",
    parameters={
        "title": {"type": "STRING", "description": "笔记标题"},
        "content": {"type": "STRING", "description": "笔记内容"}
    },
    required=["title", "content"]
)
def save_note(title: str, content: str) -> str:
    notes = {}
    if os.path.exists(NOTES_FILE):
        with open(NOTES_FILE) as f:
            notes = json.load(f)
    notes[title] = content
    with open(NOTES_FILE, "w") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)
    return f"笔记 '{title}' 已保存"


@koto_tool(
    description="列出所有已保存的笔记标题",
    parameters={}
)
def list_notes() -> str:
    if not os.path.exists(NOTES_FILE):
        return "还没有保存任何笔记"
    with open(NOTES_FILE) as f:
        notes = json.load(f)
    return "笔记列表：\n" + "\n".join(f"- {t}" for t in notes.keys())
```

---

## 热重载

工具文件修改后，无需重启 Koto。在对话中发送：

> "重新加载工具"  
> 或调用 API: `POST /api/skills/tools/reload`

---

## 注意事项

- 工具函数必须返回字符串（AI 无法处理其他类型）
- 异常会被捕获并作为错误信息返回给 AI，不影响主程序
- 每个文件可以定义多个工具
- 示例文件：`_example_notes.py`（以 `_` 开头，默认禁用，重命名激活）
