# Koto 插件接入协议 v1.0

状态：`stable-draft`
协议版本：`1.0`
Kernel API：`1`

本协议只定义插件如何被 Koto Agent 底座接入、审查、授权和执行，不定义任何
法律、商业、银行、RAG 或数据库插件，也不包含插件市场和安装器。

## 1. 设计目标

插件是 Agent Kernel 的能力贡献者，不是另一套 Agent。插件可以贡献：

- `tool`：一个具有严格输入、输出和副作用声明的模型工具；
- `retriever`：一个返回可追溯证据的 RAG/数据库检索器。

插件不得接管任务规划、Agent 循环、最终回答验证、会话状态或 SSE/HTTP 输出。
这些职责始终属于 Koto Kernel 和宿主适配器。

```mermaid
flowchart LR
    A["插件包与 manifest"] --> B["Schema 与语义校验"]
    B --> C["宿主权限、依赖、数据政策准入"]
    C --> D["生命周期初始化"]
    D --> E["工具 / Retriever 原子注册"]
    E --> F["按任务 Profile 选择"]
    F --> G["Kernel 执行预算与超时"]
    G --> H["输出 Schema、大小、证据与 ACL 校验"]
    H --> I["审计事件与结构化结果"]
```

任一门禁失败，插件均不得部分注册或静默降级为更高权限模式。

## 2. 插件包必须满足的条件

### 2.1 身份与版本

插件必须提供 `PluginManifestV1`：

- `schema_version` 必须为 `1.0`；
- `api_version` 必须与 Kernel API `1` 相同；
- `plugin_id`、贡献 ID、工具名和能力 ID 必须是稳定的小写标识符；
- `version` 必须使用 SemVer；
- 同一版本的 manifest 内容必须保持不可变，可通过 SHA-256 摘要审计；
- 插件升级不得偷偷扩大权限、数据范围或工具副作用。

### 2.2 贡献声明

每个贡献必须声明：

- 唯一 `id`、公开 `name`、说明和能力 ID；
- `kind`：只能是 `tool` 或 `retriever`；
- 所需权限，且必须是插件顶层权限的子集；
- `read_only`；
- Draft 2020-12 `input_schema` 和 `output_schema`；
- 可选的单次超时，并且不能超过插件总限制。

运行时提供的 ToolSpec/RetrieverSpec 必须与 manifest **完全同名**，来源必须是
`plugin:<plugin_id>`，版本、能力、读写属性和输入 schema 必须一致。未声明贡献、
漏交贡献、同名工具或覆盖核心工具都会被拒绝。

### 2.3 权限

v1 权限集合固定为：

| 权限 | 含义 |
|---|---|
| `workspace.read` / `workspace.write` | 读取或修改宿主工作区 |
| `database.read` / `database.write` | 查询或修改外部数据库 |
| `network.egress` | 向宿主之外发送网络请求 |
| `model.invoke` | 调用额外模型；仍受宿主模型预算约束 |
| `process.execute` | 启动进程或执行代码 |
| `secrets.use` | 使用 manifest 声明的密钥绑定 |
| `user.notify` | 产生用户可见的外部通知或副作用 |

要求：

- 默认零授权，安装不等于授权，授权也不等于对所有任务可见；
- 任何 `read_only=false` 的工具必须声明至少一种副作用权限；
- 插件只能按名字解析 manifest 中声明的密钥，不能列举或读取密钥存储；
- 配置值必须通过 `config_schema`，密钥不得写进 manifest 或普通配置；
- HTTP 插件必须额外获得 `network.egress`；
- 未知权限一律拒绝，不能以字符串扩展绕过审核。

## 3. 数据与数据库接入条件

数据库连接、连接池、索引和查询实现由插件拥有；Agent 状态、用户会话和授权状态
仍由宿主拥有。数据库/RAG 插件还必须满足：

1. 声明接受和产生的数据等级：`public`、`internal`、`confidential`、
   `restricted`；
2. 声明数据是否发往外部、是否持久化以及明确保留天数；
3. 使用数据库权限时必须声明 `tenant_isolation=true`；
4. Retriever 查询必须携带 `tenant_id`、`principal_id` 和关联 ID；
5. Database Tool 必须设置 `requires_invocation_context=true`，并通过保留的
   `invocation_context` 参数接收宿主身份、用途和关联 ID；该参数不得出现在模型
   `input_schema` 中；
6. ACL 必须在检索前过滤，不能先把跨租户结果交给模型再过滤；
7. `confidential/restricted` 证据块必须带非空 ACL 标签；
8. 写数据库必须使用独立工具和 `database.write`，不能把读工具动态升级为写；
9. 必须有超时、最大并发、最大返回字节数和最大证据块数；
10. 所有写入型 Tool 的输入 Schema 必须把 `idempotency_key` 声明为必填字段；
11. Addon 注册表使用单调递增 revision，所有服务进程在调用前校对并刷新运行时；
12. 运行时必须实际执行并发信号量、超时、熔断退避和持久化审计，不能只校验 manifest 数值；
13. 缺少/无效上下文或模型伪造上下文时，必须在 handler 执行前拒绝并记录
    `plugin.tool.denied`；
14. 禁止把数据库句柄、游标、ORM 对象或原始连接返回给 Agent。

宿主默认拒绝把 `restricted` 数据发送到外部；只有部署策略明确允许时才可准入。

## 4. RAG 证据协议

Retriever 接受 `RetrievalRequest`，返回 `RetrievalBatch`。每个
`EvidenceChunk` 必须包含：

- 稳定 `chunk_id`；
- 文本 `text`；
- `source_uri` 和 `source_title`；
- 可直接展示或映射的 `citation`；
- 可选的 0–1 相关度；
- 元数据和 ACL 标签。

Retriever 必须保留请求的 `correlation_id`，返回的 `provider_id` 必须等于贡献名。
超过 `top_k`/插件块数限制、缺引用、敏感数据缺 ACL 或返回任意字典而非标准批次，
均按协议错误处理，不进入模型上下文。

## 5. 工具执行协议

插件工具只能通过 `ToolCatalog` 和 `ToolExecutor` 被调用：

- 所有工具先校验输入 JSON Schema；
- `invocation_context` 是 Kernel 带外参数；模型参数中出现该字段一律策略拒绝；
- 写工具串行执行，只有明确 `read_only=true` 的工具才可并行；
- 使用工具级或插件级超时；
- 返回值必须可 JSON 序列化、符合 `output_schema` 且不超过字节限制；
- 超时、参数错误、策略拒绝和执行异常必须转成结构化 ToolResult；
- 插件不得直接构造最终回答，也不得向前端发送 SSE；
- 插件不得自行递归调用 Kernel 或建立第二个无限工具循环；
- 需要额外模型的工具必须声明 `model.invoke`，并接受宿主预算、模型 allowlist
  和审计策略。

## 6. 传输条件

| 传输 | entrypoint | 默认条件 |
|---|---|---|
| `in_process` | `python.module:Object` | 仅适用于受信任代码；仍需准入 |
| `http` | HTTPS URL，禁止 URL 内凭据 | 默认禁用；需要网络授权和远程隔离适配器 |
| `mcp` | 稳定的小写 server id | 默认禁用；需要配置的 MCP 宿主和能力映射 |

传输方式只改变调用适配器，不改变 manifest、权限、数据、证据或输出契约。
不受信任插件不能因为声明为 `in_process` 就获得进程内执行资格，应由部署策略强制
使用远程进程/容器隔离。

## 7. 生命周期

宿主拥有以下顺序：

1. 读取并校验 manifest；
2. 校验权限、配置、密钥绑定、依赖、数据政策和资源限制；
3. 加载传输适配器，但尚不向 Agent 暴露能力；
4. 调用 `initialize(PluginHostContext)`；
5. 检查 `health()`；
6. 一次性原子注册全部贡献；
7. 按任务 Profile/allowlist 选择，而非加入全局工具全集；
8. 禁用、升级或退出时先停止新调用，再等待在途调用，最后 `shutdown()`。

初始化、健康检查或注册失败时不得留下部分工具。可选插件失败只影响自身；被部署
策略标记为必需的插件失败时，应阻止对应 Profile 启动，而不是运行残缺流程。

`PluginHostContext` 只能暴露已校验配置、已授权权限、声明密钥的按名解析器和审计
出口。插件不得接收 Flask app、全局 ServiceRegistry、用户完整会话或 Kernel 内部
可变状态。

## 8. 依赖与兼容

- 依赖必须用插件 ID 和最小/最大 SemVer 声明；
- 必需依赖缺失或版本不匹配时拒绝准入；
- 可选依赖缺失只产生告警，插件必须保持其已声明契约不变；
- v1 不允许插件动态安装 Python 包或修改宿主依赖；
- manifest schema 或 Kernel API 主版本变化需要显式迁移，不能静默兼容；
- 插件下线后，历史任务记录仍应保留插件 ID、版本和 manifest 摘要。

## 9. 审计最低字段

宿主至少记录：`plugin_id`、插件版本、manifest 摘要、贡献名、调用关联 ID、租户/
主体标识、权限快照、开始与结束时间、结果状态、错误码、输入/输出字节数和数据等级。
敏感输入、密钥和完整证据正文不能直接写入日志，只记录摘要或脱敏元数据。

## 10. 代码边界

规范实现位于：

- `app/core/agent/plugin_protocol/contracts.py`：manifest、权限、数据和贡献契约；
- `app/core/agent/plugin_protocol/schema.py`：严格 JSON Schema、解析和摘要；
- `app/core/agent/plugin_protocol/admission.py`：宿主准入与原子工具注册；
- `app/core/agent/plugin_protocol/retrieval.py`：RAG 证据协议；
- `app/core/agent/plugin_protocol/lifecycle.py`：宿主生命周期接口。
- `app/core/agent/addons/contracts.py`：Addon 任务请求、绑定与执行计划；
- `app/core/agent/addons/runtime.py`：生命周期、准入、任务选择和身份约束检索；
- `app/core/agent/tool_profiles.py`：把已准入 Addon 工具组成到 Agent 工具面。

协议层不得导入 `web.*`、具体插件、数据库驱动、LLM Provider 或业务领域模块。具体
Addon 不得被核心 Runtime 按包名直接导入。部署引导层必须先构造候选对象，再显式
交给 `AddonRuntime.admit()`；运行时只保存已经初始化、健康检查和协议准入的对象。

Legacy Skill 不属于本协议。Skill 不能贡献 Addon 工具、不能触发 Addon 路由，也不能
借助旧 `SkillToolAdapter` 进入生产 Agent 工具面。

宿主内置工具统一位于 `app/core/agent/toolkits/builtin`。它们虽然为兼容内部注册器
仍实现 `AgentPlugin` 接口，但属于固定 Foundation/宿主工具面，不是可安装插件，也
不会经过 Addon 注册、授权或外部协议；`app/core/agent/plugins` 命名空间已移除。

## 11. 当前仍明确不实现

- 任何法律、商业、银行、OCR、数据库或 RAG 插件；
- 插件目录扫描、下载安装、签名验证或插件市场；
- HTTP/MCP 远程执行适配器；
- 插件自动启用或自动授予权限；
- 业务 Prompt、业务工作流和专用 Agent。

这些能力未来只能建立在本协议上，不得另开一套工具注册或 Agent 循环。

当前已实现的是通用 Addon Runtime：宿主代码显式准入 Addon；按任务类型、意图、
文件类型、能力和数据等级生成执行计划；将计划内工具加入 Agent allowlist；RAG 调用
必须提供可信 `tenant_id` 和 `principal_id`。这不等于已经实现安装器或任何业务 Addon。

## 12. 当前管理面

Addon 管理面已经从 Skill 市场物理拆分到独立 `/addons` 页面。它提供：

- 查看协议版本、运行时状态、支持贡献类型和已准入 Addon；
- 载入或粘贴 manifest，并调用严格解析器执行结构与语义预检；
- 展示权限、数据外传、租户隔离、持久化策略、贡献类型和 manifest 摘要；
- 明确展示 Agent、Addon 与 Legacy Skill 的边界。

对应只读/预检 API 位于 `/api/plugin-protocol`：`schema`、`example`、`validate`
和 `catalog`。`validate` 成功只代表 manifest 合法，不会发现、安装、导入、注册或执行
Addon 代码；`catalog` 只显示引导层已经准入的对象。未来的安装与发现层仍必须经过
同一个准入控制器。

状态接口分别暴露 `schema_transports` 和 `runtime_enabled_transports`。前者表示协议
能够描述的传输类型，后者才表示当前宿主实际允许执行的传输；v1 当前只有受信任的
`in_process`，HTTP/MCP 仍不得因为出现在 Schema 中就被描述为已启用。
