# Koto 信息管理与 Addon 可信调用进度报告

日期：2026-07-20

## 本阶段结论

本阶段完成了 Phase 0 的核心目标：`AddonInvocationContext` 已不再只是协议定义，
而是从 Web 宿主认证身份出发，经 `KernelAgent`、`KernelRuntime` 和 `ToolExecutor`
带外传递到经过准入的 Addon Tool。

模型只能生成业务参数，不能生成、覆盖或在 Tool Schema 中声明
`invocation_context`。声明 `database.read` 或 `database.write` 的 Tool 如果没有启用
可信上下文契约，会在 Addon 准入阶段失败；运行时缺少或伪造上下文，则在 handler
执行前返回 `policy_denied`，并产生 `plugin.tool.denied` 审计事件。

## 已完成能力

| 能力 | 状态 | 说明 |
|---|---|---|
| Addon 可信调用上下文 | 完成 | tenant、principal、purpose、request/session/correlation 和数据等级 |
| Kernel 带外注入 | 完成 | 上下文不进入模型消息、Tool Schema 或 ToolCall.arguments |
| Database Tool 准入 | 完成 | database.read/write 强制 `requires_invocation_context=True` |
| 模型伪造防护 | 完成 | 模型参数出现保留字段时直接策略拒绝 |
| 缺失/无效身份防护 | 完成 | handler 执行前默认拒绝 |
| 上下文审计 | 完成 | started/succeeded/failed/denied 携带主体、用途和关联 ID，不记录参数正文 |
| 旧普通 Tool 兼容 | 完成 | 非受管核心/文件 Tool 沿用原调用方式 |
| Web Agent 身份桥接 | 完成 | 身份来自宿主认证解析，purpose 由宿主固定，不读取客户端字段 |
| 信息管理只读内存层 | 完成 | 目录、模板、默认拒绝、脱敏、血缘、新鲜度、Mock Connector |
| Addon Retriever 兼容 | 完成 | 受治理信息结果映射为现有 EvidenceChunk/RetrievalBatch |

兼容性说明：普通核心 Tool、文件 Tool、Retriever 和非数据库 Addon Tool 不需要修改。
已有 Database Tool 必须增加 `requires_invocation_context=True`，并让 handler 接受
`invocation_context`；未迁移的数据库 Tool 会被安全地阻止准入，不会静默降级运行。

## 测试证据

本阶段定向运行 393 项测试，全部通过：

- 71 项：Kernel、插件协议、Addon Runtime、Mock Addon、信息管理安全闭环；
- 291 项：架构边界、任务链路、基础工具包、Addon 中心和 Web 启动回归；
- 1 项：Web 请求认证身份到 Agent Addon Tool 的真实注入路径；
- 30 项：ToolRegistry、参数归一化、KernelAgent 和 Chat 编排契约。

同时通过 Black、Flake8 和目标文件 `git diff --check`。本报告不宣称约 5400 项完整
单元目录全量通过；本阶段采用的是覆盖变更面和关键相邻链路的定向回归。

## Phase 进度

| 阶段 | 进度判断 | 当前状态 |
|---|---:|---|
| Phase 0：协议安全加固 | 100% | 可信身份、准入、执行拒绝和审计闭环完成 |
| Phase 1：只读信息层 MVP | 约 75% | 内存核心与 Mock 闭环完成；持久化和资源预算未完成 |
| Phase 2：真实只读数据产品 | 0% | 尚未连接真实数据库/API，符合当前安全计划 |
| Phase 3：权限感知知识/法律证据 | 设计完成 | 尚未建设企业 ACL 索引和删除传播 |
| Phase 4：确定性银行工作流 | 设计完成 | 尚未开放开户写入、审批或账务操作 |

Phase 1 的 14 项验收条件中，10 项已在本地闭环完成，4 项仍为部分完成：真实来源的
行级策略、字节/扫描成本预算、数据产品 revision 即时撤销，以及缓存/索引的跨租户
隔离。Mock 隔离测试不能替代生产数据源验证。

## 当前不能做的事情

- 不能直接连接生产核心银行数据库；
- 不能让模型生成或执行任意 SQL；
- 不能进行开户落库、账户修改、支付或资金交易；
- 不能把本地工作区 RAG 当作银行级多租户知识设施；
- 不能在没有真实 SSO 岗位/机构映射、Secret Manager、网络隔离和不可变审计的情况
  下处理生产 restricted 数据。

## 下一阶段建议

下一阶段应完成 Phase 1 的持久化控制平面，而不是立即开发银行业务 Addon：

1. 为 Source、DataProduct、FieldPolicy、QueryTemplate 和 Addon 绑定增加原子 JSON/数据库
   持久化；
2. 为目录增加单调 revision、快照和即时撤销；
3. 为 Information Gateway 增加执行时间、返回字节、分页、并发和扫描成本预算；
4. 增加多进程刷新、缓存隔离、审计失败和 revision 变化中的并发测试；
5. 完成后选择低风险、只读、脱敏的数据产品进入 Phase 2。
