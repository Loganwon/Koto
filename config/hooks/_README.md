# Koto Hook System — `config/hooks/`

在这个目录里放 `.py` 文件，Koto 会在特定时机自动执行它们。  
文件名以 `_` 开头的会被跳过（可用于禁用或作为草稿）。

---

## 可用的 Hook 函数

在你的 `.py` 文件中定义以下任意函数，Koto 会自动发现并调用它们：

### `pre_message(text: str, ctx: HookContext) -> str | None`
消息在进入 AI 之前触发。可以修改消息内容（返回新字符串），或不做修改（返回 None）。

```python
def pre_message(text: str, ctx) -> str | None:
    # 例如：为每条消息附加当前时间
    from datetime import datetime
    return text + f"\n[本地时间: {datetime.now().strftime('%H:%M')}]"
```

### `post_response(text: str, ctx: HookContext) -> str | None`
AI 的回复在发给用户之前触发。可以修改回复内容，或返回 None 保持原样。

```python
def post_response(text: str, ctx) -> str | None:
    # 例如：过滤敏感词
    return text.replace("某敏感词", "***")
```

### `on_skill_change(skill_id: str, enabled: bool, ctx: HookContext) -> None`
当某个 Skill 被启用或禁用时触发。

```python
def on_skill_change(skill_id: str, enabled: bool, ctx) -> None:
    print(f"Skill '{skill_id}' 已{'启用' if enabled else '禁用'}")
```

### `on_session_start(session_id: str, ctx: HookContext) -> None`
新会话开始时触发。

```python
def on_session_start(session_id: str, ctx) -> None:
    print(f"新会话: {session_id}")
```

### `on_tool_result(tool_name: str, result: str, ctx: HookContext) -> str | None`
AI 调用工具后，结果返回给 AI 之前触发。可修改工具输出。

```python
def on_tool_result(tool_name: str, result: str, ctx) -> str | None:
    # 记录工具调用
    with open("tool_log.txt", "a") as f:
        f.write(f"{tool_name}: {result[:100]}\n")
    return None  # 不修改结果
```

---

## HookContext 对象

所有 hook 都会收到一个 `ctx` 对象，包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ctx.session_id` | str | 当前会话 ID |
| `ctx.task_type` | str | 任务类型（如 `"chat"`, `"skill_toggle"`） |
| `ctx.skill_id` | str | 当前激活的 Skill ID（如有） |
| `ctx.active_skills` | List[str] | 所有已启用的 Skill ID 列表 |
| `ctx.extra` | Dict | 附加信息（因 hook 类型而异） |

---

## 热重载

修改 hook 文件后，无需重启 Koto。在 Koto 界面发送：

> "重新加载 hooks"  
> 或调用 API: `POST /api/skills/hooks/reload`

---

## 示例文件

- `_example_logger.py` — 将所有消息记录到日志文件（以 `_` 开头，默认禁用）
- 重命名为 `example_logger.py` 即可激活

---

## 注意事项

- Hook 函数中的异常会被静默捕获，不会影响 Koto 正常运行
- 避免在 hook 中执行耗时操作（会阻塞响应）
- 同一类型可以有多个 hook 文件，都会被调用
