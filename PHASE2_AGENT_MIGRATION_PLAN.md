# Phase2 Agent 迁移计划（进行中）

更新时间：2026-02-19

## 目标
- 让统一 Agent 成为默认 API 与执行入口。
- 保留旧 Adaptive Agent 能力作为兼容通道，逐步淘汰。
- 消除重复路由、重复实现与 SDK 技术债。

## 已完成（本轮）
- [x] `GeminiProvider` 迁移到 `google.genai`（消除 `google.generativeai` 弃用警告）
- [x] 主应用接入统一 Agent 蓝图：`/api/agent`
- [x] 在统一 Agent 增加兼容端点：
  - `/api/agent/process`
  - `/api/agent/process-stream`
- [x] 旧 Adaptive 蓝图改挂载到 `/api/adaptive-agent`，消除 `/api/agent/*` 路由冲突
- [x] 前端 Agent 模式流式请求切换到 `/api/agent/process-stream`
- [x] 前端新增事件协议适配：`agent_step/task_final/error` -> 现有渲染事件

## 下一步（Phase2 待办）
- [ ] 前端调用路径收敛：把剩余非 Agent 的旧分支按策略逐步切换/统一
- [ ] 统一 SSE/NDJSON 事件协议（`agent_step / task_final / error`）
- [ ] 清理 `UnifiedAgent` 中遗留重复/不可达代码块
- [ ] 将旧 Adaptive 特有能力按插件方式并入 `app/core/agent/plugins`
- [ ] 增加关键端点回归测试（`/api/agent/chat`, `/process`, `/process-stream`）

## 回滚策略
- 旧接口仍可通过 `/api/adaptive-agent/*` 使用。
- 若统一入口异常，可临时将前端切回旧路径并保留新代码。
