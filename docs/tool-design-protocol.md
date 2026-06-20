# Tool Design Protocol

Koto 在文件任务里遇到缺失能力时，不让模型伪造成功，也不让模型在运行时直接“发明并上线工具”。

正式流程只有五步：

1. 先检查现有 allowlist 工具是否已经能完成任务。
2. 一个工具不够时，优先组合多个现有工具。
3. 只是一次性计算、制图、批量转换或复杂处理时，优先使用 `run_python_code`。
4. 只有当现有工具和 `run_python_code` 都不能稳定完成、且缺的是可复用原生能力时，才返回 `tool_gap`。
5. `tool_gap` 被接受后，再进入实现、测试、接入 gateway/provider、加入 allowlist 的正式流程。

## 设计原则

- `proposed_tool` 必须是最小下一能力，不要把多步工作流、UI 按钮、提示词模板或外部系统打包成一个工具。
- `proposed_tool` 是设计草案，不是可立即执行的工具调用。
- Koto 始终保留控制权：allowlist、真实写入、`file.changed` 事件、核验、最终成败判断都由 Koto 负责。

## 结构化返回

模型在缺失能力时必须返回：

```json
{
  "tool_gap": {
    "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
    "missing_capability": "read_cad_file",
    "why_missing": "allowlist 中没有可读取 dwg 的工具。",
    "suggested_next_step": "先实现只读 CAD 解析工具，再决定写入方案。",
    "proposed_tool": {
      "name": "read_cad_file",
      "description": "解析 DWG/DXF 为可检索的结构化文本。",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"}
        },
        "required": ["path"]
      },
      "returns": "Koto 标准 file-change payload，包含 path、operation、summary、preview、change_type。",
      "rationale": "CAD 文件需要格式感知解析。",
      "implementation_notes": ["第一版只读，不写回 CAD。"],
      "safety_constraints": ["不得伪造已经写入或已经完成。"],
      "acceptance_tests": ["DWG/DXF 示例文件可以返回图层和实体摘要。"]
    }
  }
}
```

## 代码边界

- 协议实现集中在 `app/core/agent/tool_design_protocol.py`。
- `file_task_runtime.py` 负责把 `tool_gap` 转成 `tool.missing` 和 `next_action_artifact`。
- `file_task_runtime.py` 负责保持 native-only 执行边界，不再通过独立 planner 文件维护旧版 `tool_gap` schema。
- `file_task_capability.py` 用同一协议生成已知 native capability gap。
