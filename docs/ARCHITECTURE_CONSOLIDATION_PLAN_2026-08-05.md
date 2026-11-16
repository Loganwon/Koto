# Koto 全体系清理与结构收敛计划

日期：2026-08-05  
状态：执行中（第一轮治理与高把握删除已完成）  
范围：除已完成的 Kernel/文件任务主链清理外，覆盖启动装配、依赖管理、API、后台任务、工具与 Addon、模型调用、文件/知识/文档领域、前端运行时、状态数据与架构治理。

2026-09-05 进展：旧 `TaskScheduler` 与重复 Job 查询/控制 API 已删除；自动归纳已迁移到
`TriggerRegistry → JobRunner → TaskLedger`；旧 `FileIndexer` 已由核心 `RAGService`
取代；无消费者的前端 `wsStore/state-kernel` 影子状态已删除；致命 Python lint、
前端 lint、测试与 bundle 预算已纳入 CI。下文保留初始审计数据，作为迁移历史基线。

## 1. 结论

当前 Kernel 与文件任务主链已经具备可继续演进的基础，但**整个 Koto 结构还不能判定为稳定**。主要风险已经不再是“有没有一条能运行的任务链”，而是同一职责同时存在多个所有者：

- `web.app`、`web.app_startup`、`ServiceRegistry`、`AppContext`、lazy loaders 都在参与启动或服务构造；
- `TaskScheduler`、`JobRunner`、`TriggerRegistry` 同时承担后台调度；
- Kernel ToolCatalog、多个 ToolRegistry、foundation catalog、MCP registry、旧 PluginRegistry 和 Addon store 重复描述工具或扩展；
- provider、runtime gateway、Kernel model gateway、文件任务 gateway 分别处理模型选择、fallback 和响应归一化；
- FileRegistry、FileScanner、FileIndexer、RAGService、KnowledgeBase、KnowledgeGraph 等重复维护文件或知识状态；
- 文档/PPT 生成存在多套编排器，部分模块没有生产引用；
- 前端仍有大量 `window` 级耦合、模板内联事件和已提交的生成 bundle；
- `config/` 混入用户画像、触发器、索引、统计和数据库等运行时状态；
- 架构治理文档引用的部分预算文件已删除，当前审计虽返回成功，但同时报告 compatibility ledger schema 错误，治理门禁并未真实闭合。

因此下一阶段不应继续增加功能，也不应先做机械拆文件。应先完成“单一所有者收敛”，再对仍然过大的实现做内部拆分。

## 2. Agent Harness 视角下的保留边界

### 2.1 必须保留的确定性代码

- 工具原语：读取、写入、转换、搜索、执行、导出；
- 权限和副作用控制：路径约束、审批、锁、幂等、事务、回滚；
- 状态与生命周期：任务状态、取消、恢复、审计、事件协议；
- 验证：格式、产物、引用、事实证据、输出完整性；
- 协议适配：HTTP、SSE、WebSocket、MCP、Addon；
- 模型网络适配：鉴权、请求发送、流式解析、供应商错误映射；
- 用户明确要求的确定性业务规则。

### 2.2 默认删除或合并的程序化设计

- 用关键词、recipe 或 workflow 提前替模型决定完整步骤；
- 为某一种文档任务单独建立 orchestrator、planner、quality loop；
- 多处重复做模型选择、fallback、prompt 拼装和响应解析；
- 同一实体在多个 registry、JSON、SQLite 或内存单例中重复登记；
- 仅为兼容旧 import 而存在、且调用方可迁移的 re-export shim；
- 没有生产入口、只被自身示例或旧测试引用的模块；
- 读取 getter 时隐式创建线程、启动监控或写入状态的服务定位器。

判定原则是：**让模型负责理解、规划和工具选择；让代码负责能力、边界、状态和验证。**

## 3. 审计基线与已确认缺陷

以下数据来自当前工作树的静态引用审计和 `scripts/audit_code_baseline.py --json`：

| 领域 | 当前证据 | 判断 |
| --- | --- | --- |
| Agent 体量 | `app/core/agent` 现有 212 个 Python 文件，约 1.92 MB | 文件任务主链已收敛，但目录中仍混有多代 registry、toolkit 和 adapter |
| 启动重复 | `web/app.py` 与 `web/app_startup.py` 有 13 个 AST 完全相同的函数 | 可直接建立单一实现，禁止双份维护 |
| 服务构造 | `ServiceRegistry`、`ChatRuntimeServices`、`runtime_services`、lazy loader cache、`app.core.app_context.ctx` 并存 | 生命周期与依赖所有权不唯一 |
| 兼容层 | `web/` 下存在大量指向 `app/core/services` 或二级 `web.*` 包的 shim | 迁移调用后应批量删除，只保留明确的 transport adapter |
| 任务/作业 API | `/api/tasks` 与 `/api/jobs` 都实现 TaskLedger 查询、状态、取消、恢复和 SSE | 同一任务资源有两套接口和序列化逻辑 |
| 后台调度 | `TaskScheduler`、`JobRunner`、`TriggerRegistry` 会在运行时同时出现；AutoCatalog 又依赖旧 scheduler | 应统一为 Trigger -> JobRunner -> TaskLedger |
| 工具目录 | Kernel registry、`agent/tools.ToolRegistry`、foundation registry/catalog/capabilities/profile、UnifiedToolRegistry、MCP registry 并存 | 工具定义不是单一事实源 |
| 扩展注册 | 生产插件接口使用 Addon store；旧 `plugin_protocol.PluginRegistry` 无生产调用方 | 旧 registry 是高把握删除候选 |
| 模型边界 | 全仓仍有 55 处 provider/gateway 相关命中，多层分别处理选择、fallback、归一化 | 应只保留 provider adapter + 一个生成服务 + Kernel adapter |
| 文件/检索 | FileRegistry 自行创建 RAG；RAG API、FileRAGIndexer、KnowledgeBase、GraphRAG 又各自构造索引 | 文件身份、扫描和索引生命周期重复 |
| 文档/PPT | `ppt_pipeline`、enhanced generator、synthesizer、quality 模块无生产调用；`ppt_generation_service` 仅由 template library 使用 | 先删孤立编排栈，再统一到确定性渲染器和原子工具 |
| 前端边界 | 56 个 TS/Vue 文件、230 处 `window.*` 使用；全部 HTML 中有 152 个内联事件；30 个生成 bundle 文件被 Git 跟踪 | 模块边界仍依赖全局状态，审计脚本只覆盖了其中很小一部分 |
| 状态目录 | 用户画像、token、trigger、RAG index、数据库出现在 `config/`；测试 DB 出现在 `data/db` | 配置、状态、缓存、用户产物边界不清 |
| 治理门禁 | 审计输出 `architecture_budget_status={}`，compatibility debt schema 报错，feature ownership 仍引用已删除 blueprint | 当前“审计通过”不等于架构约束通过 |

大文件不是单独的删除理由。当前 16 个超过 1500 行的生产文件，只在职责收敛后再判断是否需要拆分。

## 4. 目标结构

```text
Transport (Flask / SSE / WebSocket / MCP)
        |
        v
Application services
  - ChatService
  - AgentTaskService
  - FileService
  - RetrievalService
  - JobService
        |
        v
Kernel / domain contracts
  - KernelRuntime
  - TaskLedger
  - ToolSpec + ToolCatalog
  - FileRecord
  - Artifact / validation contracts
        |
        v
Infrastructure adapters
  - LLM providers
  - filesystem / SQLite / vector index
  - Addon / MCP projections
  - office renderers

唯一 composition root：创建、注入、start、stop
```

硬性约束：

1. 每个长期状态只有一个所有者；
2. 每个服务只有 composition root 可以构造并管理生命周期；
3. transport 不拥有业务单例，domain 不 import `web.*`；
4. ToolSpec 是工具元数据唯一事实源，MCP 和 UI 只做投影；
5. TaskLedger 是执行记录唯一事实源，Job 只是提交方式；
6. provider 不做业务级模型选择，业务服务不直接创建 provider；
7. runtime getter 不启动线程、不写文件、不注册全局副作用。

## 5. 分阶段处理计划

### Phase 0：恢复真实治理门禁

目的：先让“是否又长出重复链路”可被自动发现。

处理：

1. 修复或重建最小化 architecture budget；不恢复已经删除的大量阶段性文档；
2. 修复 `config/compatibility_debt.json` schema，所有保留 shim 必须登记调用者、替代路径和删除条件；
3. 移除 feature ownership 中已删除的 `pptx_editor` blueprint 所有权；
4. 扩大前端审计范围，覆盖全部产品模板，不只统计主模板；
5. 增加以下架构守卫：
   - `app/core` 不得 import `web.*`；
   - 禁止新增 `get_*()` 全局单例；
   - 禁止新增工具 registry；
   - 禁止新增直接 provider 调用方；
   - shim 数量、`window.*` 使用、内联事件只能下降；
6. 保存当前可重复运行的启动、collection、Kernel、前端和浏览器基线。

验收：审计脚本遇到 schema 错误、缺失预算或失效 owner 必须非零退出；CI 使用同一命令。

### Phase 1：删除高把握孤立代码和失效兼容层

目的：先降低认知噪声，避免在重构时继续兼容没有消费者的实现。

优先删除候选：

- `app/core/agent/tools/__init__.py` 中无外部生产消费者的第二套 `ToolRegistry`；
- 无生产入口的旧 `app/core/plugin_protocol/registry.py` 及只服务于它的安装状态代码；
- 无生产入口的 `ppt_pipeline.py`、`ppt_generator_enhanced.py`、`ppt_synthesizer.py`、`ppt_quality.py`；
- 只被上述孤立模块引用的 feedback/quality 辅助层；
- 已删除 WorkflowEngine 遗留的 `config/workflows/*.json`；
- `data/db/test_*.db` 等误落入运行目录的测试状态；
- 零生产调用的 root `web/*.py` shim。

删除前每项执行三重核验：静态 import、字符串/动态 import、路由/打包 manifest。删除时同步删除只测试旧实现的测试，不保留“测试让死代码继续活着”的情况。

验收：应用启动、全仓 collection、相关 API smoke、打包源清单检查通过；deleted-symbol guard 为零。

### Phase 2：收敛启动与依赖生命周期

目的：建立真正唯一的 composition root，这是后续所有合并的基础。

处理：

1. 将 `web/app.py` 与 `web/app_startup.py` 的 13 个完全重复函数迁入唯一启动模块；
2. `web/app.py` 只保留 app factory 暴露和兼容的 chat 边界，不再保存启动实现副本；
3. 以 `ServiceRegistry` 为唯一公开容器，吸收 `app_context.ctx` 必要能力；
4. `ChatRuntimeServices` 改为从 registry 构造的请求级只读依赖视图，不持有第二套全局 `_services`；
5. 删除 `runtime_services.py` 和 lazy loader 的独立 cache；
6. 将线程启动、监控启动、定时器注册集中到 `start_runtime()`，将停止动作集中到 `stop_runtime()`；
7. 服务 getter 只允许查询，不允许隐式启动或持久化。

验收：同一服务多次获取对象身份一致；启动/停止可重复；import `web.app` 不启动后台线程；不存在第二个全局服务 cache。

### Phase 3：统一任务、作业与调度

目的：后台工作也使用同一状态和执行语义。

处理：

1. 保留 `TaskLedger` 作为状态、取消、恢复、进度和 SSE 的唯一实现；
2. 保留 `JobRunner` 作为后台执行队列，不再复制 Task 资源接口；
3. 保留 `TriggerRegistry` 作为触发规则，触发结果只能提交到 JobRunner；
4. 删除 `TaskScheduler`，将 chat cancel 迁到 TaskLedger，将 AutoCatalog 迁为 trigger/job handler；
5. `/api/jobs` 仅保留 submit/retry/trigger 类动作，返回 `task_id` 并链接 `/api/tasks/{id}`；
6. 删除 `/api/jobs` 中重复的 list/status/cancel/resume/SSE；
7. Goal、morning brief、proactive、catalog、reminder 的周期执行统一注册为 job handler + trigger；
8. 明确崩溃恢复只由 JobRunner/TaskLedger 执行一次。

验收：一个任务只有一个状态序列化器、一条 SSE 实现和一个取消入口；启动时只有一个调度线程族。

### Phase 4：统一工具、Addon 与 MCP 元数据

目的：工具能力只定义一次。

处理：

1. 扩充 Kernel `ToolSpec`，承载 schema、side effect、capability、timeout、approval、artifact/change metadata；
2. Kernel ToolCatalog 成为运行时唯一工具目录；
3. foundation registry、catalog、capabilities、tool_profiles 改为由 ToolSpec 生成，随后删除重复手写表；
4. Addon store 只负责安装状态和贡献声明，启用后的工具注册到 ToolCatalog；
5. MCP registry 改成 ToolCatalog 的传输投影，不再拥有另一份可执行工具事实；
6. 证明 UnifiedToolRegistry 的生产入口；若只是桥接旧表，删除其 bootstrap、bridge、executor 和 agent bridge；
7. UI capability panel 读取同一 ToolSpec 投影。

验收：给定工具名，在仓库中只有一个 schema 和一个副作用声明；Kernel、Addon、MCP、UI 展示一致。

### Phase 5：统一模型调用边界

目的：消除每条功能链各自选择模型和 fallback 的做法。

目标层次：

```text
LLMProvider: 单供应商网络适配
GenerationService: 模型选择、重试、fallback、文本/流式归一化
KernelModelGateway: 把 GenerationService 映射为 tool-calling contract
```

处理：

1. 从旧 `ollama_provider.py` 抽离本地模型发现/健康信息，删除 Gemini 风格兼容代理；
2. 合并 `runtime_gateway`、`provider_model_gateway` 和文件任务模型适配中重复的 fallback/normalization；
3. editor、task planner、job handler、document service 不再直接 `get_llm_provider()`；
4. prompt 由调用用例提供，provider 不拼装业务 prompt；
5. chat 的一次性生成与 Kernel tool loop 共用 GenerationService，但保持不同应用接口；
6. 保留 provider 专属请求/流解析测试，删除只验证旧 adapter 形状的测试。

验收：直接 provider import 只允许出现在 `app/core/llm/providers` 和 composition root；fallback 策略只有一份。

### Phase 6：收敛文件、知识、记忆和检索领域

目的：一份文件身份、一套索引生命周期、多个逻辑 collection。

目标所有权：

| 组件 | 唯一职责 |
| --- | --- |
| FileService | 路径策略与文件变更 |
| FileScanner | 发现快照，不持久化第二份业务记录 |
| FileRegistry | `FileRecord` 身份、元数据、版本 |
| FileWatcher | 产生文件变更事件 |
| RetrievalService | 文档、记忆等 collection 的统一索引与检索 |
| KnowledgeGraph | 可选的检索投影，不拥有原始文档 |
| MemoryService | 记忆语义与用户确认，不自建另一套检索实现 |

处理：

1. 合并两套 `FileEntry` 为 `FileRecord`；
2. FileWatcher -> FileRegistry -> RetrievalService 建立单向事件流；
3. 删除 FileRegistry 内部自行构造 RAG singleton 的逻辑；
4. 将 `RAGService`、`FileRAGIndexer`、旧 `KnowledgeBase` 收敛为一个 RetrievalService 和多个 collection；
5. GraphRAG 只消费检索和实体事件，不通过动态 import `web.knowledge.knowledge_graph` 构造实例；
6. 删除 `app/core` 对 `web.memory_runtime`、`web.shared`、`web.knowledge` 的反向 import；
7. 审核 FileIndexer/FileProcessor/FileAssistant 中重复的扫描、解析和索引；无独立职责则删除；
8. MemoryManager 只管理记忆记录、画像和摘要，向 RetrievalService 写入 memory collection。

验收：文件增删改只触发一次索引更新；应用重启后 registry 与 index 可一致恢复；domain 层对 `web.*` import 为零。

### Phase 7：收敛文档与 Office 生成

目的：模型生成内容，确定性 renderer 生成文件，不再为每种任务维护专用编排器。

处理：

1. 保留 DOCX/PPTX/XLSX/PDF 的原子写入、布局、导出和验证工具；
2. Kernel 通过这些工具完成内容规划与迭代，不再进入独立 PPT master/pipeline/feedback loop；
3. `template_library` 改用同一 renderer，不单独调用 AI PPT service；
4. 核验 `document_generator.py` 与 `doc_gen_service.py` 的实际消费者，合并共同保存能力，其余删除；
5. 将 `pdf_annotator`、document editor、direct edit 中的真实格式操作下沉到 exporter/editor；
6. 删除只负责“先规划、再评估、再重写”的程序化外壳；质量标准转为产物验证器和模型可见反馈。

验收：每种 Office 格式只有一套写入/保存实现；模板生成和 Agent 生成通过同一 renderer；生成产物通过真实打开/解析验证。

### Phase 8：收敛 API 与前端运行时

目的：transport 只映射应用服务，浏览器端只有明确模块边界。

处理：

1. 建立单一 blueprint manifest，删除 `app/api.__getattr__` 和特殊 function-route 注册；
2. 先删除无路由消费者的模板和页面，再处理剩余 152 个内联事件；
3. 将模板内事件迁为模块事件委托；
4. 以 feature registry/component bridge 作为唯一跨 bundle 边界，逐步消除 56 个文件中的任意 `window.*` 依赖；
5. `window` 只允许极少量经过登记的启动/第三方适配对象；
6. 区分源码与生成物：bundle 禁止手工编辑；决定是发布时构建还是保留可复现产物；
7. 若继续提交 30 个 bundle/map 文件，CI 必须从源码重建并验证零 diff；否则从 Git 移除并在打包阶段生成；
8. 大型 TS/Vue 文件只按状态所有权、IO、渲染边界拆分，不按行数拆。

验收：产品模板内联事件为零；未登记 window global 为零；源码构建可重复；无第二套前端状态内核。

### Phase 9：统一状态目录与清理文档

目的：运行时文件位置可预测、可迁移、可测试。

目录语义：

```text
config/         只放版本化默认配置和模板
data/state/     用户/运行时持久状态
data/db/        生产 SQLite
data/cache/     可重建索引和缓存
workspace/      用户主动创建或导入的产物
test temp dir   所有测试状态
```

处理：

1. 建立唯一 `AppPaths`，支持环境变量和测试隔离；
2. 将 profile、personality、token usage、triggers、email account 等运行时数据迁出 `config/`；
3. 将 RAG index 迁到 `data/cache/`，不作为配置读取；
4. 删除 JSON/SQLite 双写，确需人类可读导出时采用显式 export；
5. 测试 DB 只允许写入 pytest temp；
6. 删除已失效的功能指南、完成报告和旧架构说明；
7. 最终只保留：当前架构、稳定性契约、Addon/MCP 协议、开发/发布指南、迁移说明。

验收：干净 checkout 首次启动不会修改 `config/`；测试后 Git 状态不产生运行时文件；所有状态路径来自 AppPaths。

## 6. 执行优先级

| 优先级 | 阶段 | 原因 |
| --- | --- | --- |
| P0 | Phase 0、1 | 先修门禁并删除确定性死代码，收益高、风险低 |
| P1 | Phase 2、3 | 解决启动、单例、线程和任务状态多所有者，是稳定性的核心 |
| P1 | Phase 4、5 | 解决工具和模型边界重复，防止 Agent 体系再次分叉 |
| P2 | Phase 6、7 | 合并文件/知识/文档领域，改动面大但可显著减量 |
| P2 | Phase 8 | 在后端接口稳定后收敛前端，避免重复返工 |
| P3 | Phase 9 | 在最终所有权确定后迁移数据与清理文档 |

推荐每轮只处理一个所有权集群，不同时跨越多个 Phase。每轮都必须交付“删除清单、替代 owner、调用方归零证据、测试结果”四项。

## 7. 每轮标准流程

1. 建立生产入口矩阵：HTTP、后台启动、动态 import、打包 manifest；
2. 标出 canonical owner 和待删除 owner；
3. 先迁移消费者，再删除实现和只验证旧实现的测试；
4. 增加禁止旧符号回归的架构测试；
5. 运行针对性测试、全仓 collection、前端 typecheck/build；
6. 涉及启动、任务、文件写入或页面交互时运行对应集成/E2E；
7. 更新本计划中的基线数字，不新增“永久临时兼容层”。

## 8. 完成标准

只有以下条件全部满足，才能认为整套结构稳定：

- composition root、任务账本、工具目录、模型 fallback、文件身份、检索引擎各只有一个 owner；
- `web/app.py` 与启动模块不存在重复实现；
- `app/core -> web` 反向依赖为零；
- root service shim 降为零，或只剩有明确删除期限的 transport adapter；
- TaskScheduler 删除，Job API 不再复制 Task API；
- 旧 PluginRegistry 和无生产入口的工具 registry 删除；
- 工具 schema/side-effect/capability 只有一个事实源；
- 业务模块直接 provider 构造为零；
- Office 每种格式只有一套确定性写入/保存实现；
- 产品模板内联事件为零，未登记 window global 为零；
- `config/` 首次启动保持只读，测试状态完全隔离；
- 架构审计不存在空预算、schema 错误或失效 owner，并在 CI 中真正失败；
- Python collection、核心/集成测试、前端测试与构建、浏览器 smoke、打包源检查全部通过。

## 9. 建议立即开始的第一轮

第一轮只处理 **Phase 0 + Phase 1 的高把握项**：

1. 修复治理门禁，使错误真的阻断 CI；
2. 删除无生产入口的旧 PluginRegistry、第二套 agent/tools ToolRegistry；
3. 删除孤立 PPT pipeline/enhanced/synthesizer/quality 栈；
4. 删除旧 workflow 配置；
5. 迁移零到少量调用的 web shim，并建立 shim 数量 ratchet；
6. 运行启动、collection、Kernel/Addon/MCP、文档/PPT、前端构建和打包源检查。

这一轮不改 ServiceRegistry、不合并 RAG、不迁移状态路径，避免把“删除确定性死代码”和“重构核心生命周期”混在同一批修改中。

## 10. 执行记录

### 2026-08-05：第一轮

已完成：

- 恢复 architecture 和 frontend asset budgets；
- 将 compatibility debt 重置为合法、可校验的空 ledger；
- 修正 PPTX feature owner，移除对已删除 blueprint 的声明；
- 架构审计覆盖全部产品模板，且预算缺失、超额、manifest 错误或旧 Agent 入口回归时返回非零；
- 删除旧 `PluginRegistry`，Addon 安装状态只由 `AddonRegistrationStore` 持有；
- 删除 `app.core.agent.tools` 内第二套自注册 `ToolRegistry`，`task_tools` 直接引用 canonical registry；
- 删除孤立的 PPT pipeline、synthesizer、quality 和 enhanced generator；
- 删除无入口的 document batch/direct-edit 程序化链路及 root shim；
- 删除 WorkflowEngine 遗留配置；
- 删除只为上述孤立 PPT 模块保活的测试段，并增加 deleted-path guard。

验证：

- 架构审计通过且无 manifest/owner/budget 错误；
- Python 全仓 collection 通过，共收集 6283 项；
- 架构、Addon、Plugin Protocol、Kernel registry、foundation toolkit、MCP 和当前 PPT generation service 的针对性测试通过；
- 前端 225 项测试、TypeScript 检查和全部 bundle 构建通过；
- Python `app/web/launcher/scripts` 编译检查通过。

下一轮进入 Phase 2：先合并 `web.app`/`web.app_startup` 的完全重复启动实现，再收敛 `AppContext`、lazy loaders 和 `ServiceRegistry` 的生命周期所有权。

### 2026-08-05：第二轮

已完成：

- 删除未被引用、与 `web.app` 完全重复的 `web.app_startup`；
- 删除 `web.runtime_services` 与 `web.lazy_loaders` 的第二套全局缓存，将批处理文件服务纳入 `ServiceRegistry` 的具名工厂；
- 为 `ServiceRegistry` 增加线程安全的注册、解析、失效和关闭生命周期；
- 删除已无生产消费者的 `AppContext`，不再用通用 DI 容器重复持有 Agent、内存、知识库和配置实例；
- 内存、知识库和配置管理器改由各自核心模块明确持有生命周期，其中补齐了此前缺失的 `get_knowledge_base()`；
- `KernelAgentService` 成为生产 Agent 的唯一生命周期门面，按云端/本地、模型、工具配置和 Addon 集合隔离并缓存实例；
- 流式聊天、后台任务、长期目标和晨报统一通过 Kernel 门面；删除本地 AGENT 直接请求 Ollama 的纯文本旁路；
- MCP 监督工具不再导入 Agent 工厂私有函数，改用公开工具配置接口；
- 删除只验证旧容器存在的测试，增加旧路径保持删除、唯一 Agent 构造入口和核心服务所有权护栏。

保留说明：

- `ChatRuntimeServices` 与 `SettingsRuntimeServices` 目前只作为已绑定依赖的类型化视图，不再负责构造或缓存核心服务；后续可继续压缩其转发 API，但它们不是本轮发现的第二生命周期所有者。

下一轮建议进入 Phase 3：审查 `web/` 根目录仍存在的模块级单例和兼容转发层，优先处理 RAG/indexer、workspace 路径、session/runtime settings 的重复状态所有权。

### 2026-08-05：第三轮

已完成：

- RAG 服务和文件索引器改为按规范化索引/工作区路径缓存，由 `app.core.services` 的工厂唯一持有生命周期；蓝图、知识库、内存和文件注册表不再直接构造并长期持有第二实例；
- 工作区活动路径只由 `app.core.config.workspace_runtime` 持有，删除 `web.shared.WORKSPACE_DIR`、`web.shared.CHAT_DIR` 等启动快照，工作区路由、助手、自动保存和测试全部读取动态 owner；
- 聊天会话目录由 `web.session_manager` 显式持有，删除指向 `web.app` 的目录回调，补齐线程安全的默认 manager、目录切换和测试重置；
- 删除 `web.chat_runtime_services`，聊天、会话、设置及流式生成统一直接使用 `ServiceRegistry`；模型 ID 解析移入核心模型选择模块；
- 删除 `web.settings_runtime_services` 与 `web.settings_runtime_bootstrap`，设置路由通过同一注册表读取应用版本、代理和模型状态，并通过核心 workspace/session owner 更新存储路径；
- 删除依赖已移除阶段配置的 `test_p7_route_convergence.py`，移除仍为已删除 token-stats 路由保活的历史测试；
- 更新发布采用清单，增加旧运行时桥、路径镜像、重复 RAG 构造和会话回调不得回归的架构约束。

验证：

- 设置、会话、工作区切换、RAG、启动装配和运行时组合回归 94 项通过；
- Kernel 文件任务入口、分类、执行、验证、聊天编排和前端任务契约 227 项通过；
- 工作区路由、自动保存、启动导入与架构护栏 100 项通过；
- 架构审计、Python 编译和全仓 collection 通过，共收集 6276 项；
- 实际导入 `web.app` 成功，25 个 blueprint、284 条路由完成装配，核心聊天流和文件任务流入口存在。

剩余风险：

- 发布打包门禁仍有 6 个与本轮生命周期收敛无关的历史失败，集中在公开发布文档、已归档 Gemini 检查、PyInstaller hidden-import 去重和桌面性能预算；
- 前端按钮/页面契约仍有 4 个既有失败，集中在旧页面链接、模板事件清单和源码可达性；它们应在后续前端/发布所有权轮次独立处理，不应重新引入已删除后端路由。

下一轮建议进入 Phase 6/7 的兼容 shim 清理：以 `web.documents`、`web.files`、`web.knowledge`、`web.proactive` 四个包为单位，先证明根目录转发模块的真实外部兼容需求，再逐包迁移调用方并降低 shim 数量。

### 2026-08-05：第四轮

已完成：

- 审计 `documents`、`files`、`knowledge`、`proactive` 四个领域的根目录兼容表面，确认内部生产调用只剩少量旧 import，未发现需要继续支持根模块路径的外部协议或动态插件契约；
- 将生产代码、测试和当前文档全部迁到 `web.documents`、`web.files`、`web.knowledge`、`web.proactive` 包入口；已经迁入 Core 的转换器、文档生成器、PDF、修订跟踪和触发器直接引用 Core owner；
- 删除 29 个根目录 shim，按 Git 基线净删除约 1.8 万行重复实现/转发表面；
- 修复流式 Web 搜索中隐藏的 `from web import web_searcher` 旁路，并更新发布采用清单、功能所有权和项目 Agent 指南；
- GraphRAG 不再通过动态字符串或显式反向 import 构造 Web 知识图谱；由 `web.app` 组合根注入图谱工厂，`app.core` 的反向依赖预算保持不增长；
- 包完整性护栏现在同时验证 29 个旧文件不存在，并扫描生产源码禁止重新引用这些模块名。

验证：

- 领域包完整性与架构护栏 112 项通过；
- 转换、路径安全、PDF、搜索、文档生成和 Agent 转换工具回归 271 项通过；
- Kernel/聊天流/启动契约 19 项通过；
- 架构审计、Python 编译、全仓 collection 和实际应用导入通过；应用完成 25 个 blueprint 装配，聊天流与文件任务流入口存在。

保留说明：

- `web.documents` 内仍有 4 个模块转发到 Core，`web.files.file_converter` 和 `web.proactive.proactive_trigger` 也仍是包级适配器；它们现在是包 API 到 Core 的单层边界，不再存在根目录双层转发；
- 下一轮应评估这 6 个包级适配器能否由包 `__init__` 直接导出 Core owner 后删除，并继续处理 `web.tasks` 的 3 个根 shim。

### 2026-08-05：第五轮

已完成：

- 删除 `web.documents`、`web.files`、`web.proactive` 中 7 个包级适配模块；包 `__init__` 和实际消费者直接引用文档生成、DocumentReader、PDF、转换器、修订跟踪和触发器的 Core owner；
- 删除 `web.local_executor`、`web.template_library`、`web.operation_history` 三个根 shim，生产与测试统一使用 `web.tasks` 包；
- 删除没有生产消费者的 `web.services.intent` 整个关键词分类包及其保活测试，包括旧 annotation/file-generation 程序化路由；
- `LocalExecutor` 本体仍保留在 `web.tasks`，只负责当前白名单系统动作，不承担自由文本任务分类；
- 更新包导出、功能文档、发布清单和开发指南，并增加 11 个包级旧路径不得恢复的删除护栏。

验证：

- tasks 包导入及 LocalExecutor、TemplateLibrary、OperationHistory 行为测试 96 项通过；
- PDF、文档生成、DocumentReader、触发器和工作区接口测试 139 项通过；
- 架构、包完整性、启动、Kernel 与聊天流契约 121 项通过；
- 架构审计、Python 编译、全仓 collection 与实际应用导入通过；当前收集 6202 项，25 个 blueprint 正常装配。

下一轮建议处理剩余 19 个 `web/*.py → app.core.services` 根服务 shim。应先按生产消费者数量分组，优先删除没有消费者或只有 1 个调用方的模块，不要一次迁移调度器、任务队列和文件任务主入口。

### 2026-08-05：第六轮

已完成：

- 将剩余 19 个根服务 shim 按启动骨架与普通服务分组，保留 4 个仍承担启动/transport 边界的模块，删除其余 15 个无独立协议价值的转发文件；
- 应用、蓝图、聊天流、Agent 工具和测试统一直接导入 `app.core.services` 的 calendar、chat instruction、context、editor、file analysis/organization、image、cleanup、processed network 与 reminder owner；
- 清除 `misc_api`、批处理、文件问答、自动目录整理、文件监听器中的裸模块 fallback，避免启动目录改变时解析到第二套实现；
- 根服务兼容层由 19 个降至 4 个，包完整性护栏新增 15 个旧路径的删除与生产引用禁用检查；
- 更新项目指南和当前文件整理文档，不再把已删除的 `web/*.py` 描述为实现位置。

验证：

- 包完整性、架构、启动、上下文以及整理基础回归 117 项通过；
- image、document editor/validator、file analyzer/organizer/scanner/fields、cleanup、processed network、reminder、calendar 与 context 服务回归 154 项通过；
- 聊天系统指令与上下文分析回归 15 项通过，批处理、自动目录调度与 Core 文件监听回归 65 项通过；
- `test_web_modules_batch10.py` 中仍有 13 个指向早已删除的 `web.file_watcher` 的历史测试失败；Core `FileWatcher` 的 14 项现行测试通过，此失败不构成本轮恢复旧模块的理由。
- 架构审计、Python 编译、全仓 collection 与实际应用导入通过；当前收集 6202 项，25 个 blueprint、259 条路由完成装配，核心聊天流与文件任务流入口存在。

保留说明：

- `web.auto_catalog_scheduler`、`web.task_scheduler`、`web.task_queue` 和 `web.file_task_stream` 是最后 4 个根服务适配器；下一轮应逐个迁移启动动态导入和文件任务私有测试，不再扩大兼容面；
- `app.core.services.context_injector` 仍包含关键词式 QuestionClassifier/ContextSelector。它不再负责 HTTP 路由，但仍会按自由文本选择系统上下文，是下一轮 Agent Harness 语义清理的优先审计对象；
- 当时仍保留的 `ContextAnalyzer`、SmartDispatcher 与 routing rule chain 已在第八轮完成审计并删除。

### 2026-08-05：第七轮

已完成：

- 删除最后 4 个根服务适配器：`web.auto_catalog_scheduler`、`web.task_scheduler`、`web.task_queue` 与 `web.file_task_stream`；启动线程、聊天蓝图、Editor AI、后台任务和测试全部直接引用 Core owner；
- 根目录 `web/*.py → app.core.services` re-export shim 数量降为零，并将 4 个旧路径加入生产引用禁用护栏；
- 文件任务流不再通过 Web `ServiceRegistry` 注入未被使用的 `gemini_client`；Core stream 从唯一的 `workspace_runtime` 读取活动工作区，`FileTaskRuntime` 同时删除无消费者的 `_gemini_client` 状态；
- 删除 `app.core.services.context_injector` 及其 QuestionClassifier、ContextSelector、ContextBuilder、全局缓存和保活测试；自由文本不再通过关键词切换系统提示或预采集机器状态；
- 聊天系统指令收敛为单一模板，仅包含稳定能力边界与时间锚点；长期记忆继续由聊天生成管线的 canonical memory runtime 注入，CPU、磁盘、进程等信息只在 Agent 明确调用工具时读取；
- 更新功能所有权、架构说明、事件协议、执行入口矩阵和自动目录文档，消除对已删除 Web 文件的当前引用。

验证：

- 架构、包完整性、启动、Kernel、聊天编排、系统动作和记忆 owner 回归 128 项通过；
- 文件任务事件、压缩、失败契约、架构与前端阶段投影相关断言 103 项通过；该前端架构文件另有 1 个与本轮无关的既有 assembly dead-binding 失败；
- TaskScheduler、AutoCatalogScheduler 与稳定聊天系统指令回归 21 项通过；
- 旧根服务模块和关键词上下文分类器的生产引用均为零。
- 架构审计、Python 编译、全仓 collection 与实际应用导入通过；当前收集 6200 项，25 个 blueprint、259 条路由完成装配，核心聊天流与文件任务流入口存在。

该轮提出的 `ContextAnalyzer → SmartDispatcher → routing_rule_chain` 审计已在第八轮完成。

### 2026-08-05：第八轮

已完成：

- 未锁定的聊天请求统一进入 Kernel Agent（`AGENT`），未知显式任务也回落到 Kernel；不再按关键词、相似度、历史延续词或轻量分类模型推断任务类型；
- 工作区继续保留明确文件事实与白名单系统动作的确定性快路径，其余模糊请求统一进入 `FileTaskRuntime`，由模型和工具循环判断实际步骤；
- 非流式聊天与 Mini Chat 固定为稳定 `CHAT` 边界；设置页的分析接口只解释显式任务契约和模型选择，不再承担自由文本意图识别；
- 模型选择从任务分类中拆出为 `select_task_model()`，只接受调用方提供的显式任务类型、图像状态和复杂度；
- 删除 `ContextAnalyzer`、`SmartDispatcher`、`IntentAnalyzer`、routing rule chain、RuleRouter、routing config 与 TaskClassifier，以及训练脚本、训练语料和序列化分类模型；
- 测试改为守护单一 Kernel/FileTaskRuntime 链路和显式任务契约，旧路径仅作为“不得恢复”的负向护栏存在。

稳定边界：

- `locked_task` 是 transport contract，不是自然语言推断结果；
- 本地模型只由显式 `local` 模式或云端故障回退触发；不再按文本“是否简单”自动切换；
- 旧 `LocalModelRouter` 已拆除，OllamaRuntime 只负责连接、模型解析和内容生成，不暴露分类或路由接口；
- 删除已无生产调用的 AIRouter，以及只为训练 `koto-router` 服务的开发 API、SQLite 标签库、合成语料与记忆训练桥；文件归档结束后也不再后台触发隐式训练任务；
- 文件审阅等能力内部可以保留面向工具执行的局部判定，但不能重新成为全局聊天路由器。

### 2026-08-05：第九轮

已完成：

- `FileTaskRuntime` 的 Kernel 前置阶段不再识别 summary、translation、polish、financial、report、PPT design 等任务语义，也不再产生 semantic reason code；
- 删除 `file_task_classification_recipes.py`、`file_task_classification_semantics.py` 以及 1360 行的 `file_task_recipes.py`；生产代码中 `select_task_recipe`、`recipe_matches`、`recipe_by_id` 与 `FileTaskRecipe` 均为零；
- IntentPlanner、Whitebox skeleton、requirements、mainline normalization、tool exposure 和暂停检查不再重复选择 recipe；所有写入任务使用 `kernel_generic_file_task` 合同，Kernel 根据原始任务、文件事实和已准入工具形成实际计划；
- 分类只保留请求类型、显式写权限、只读否定、目标文件、文件类型、确认/恢复、已注册原子能力和诊断状态；任务族默认只表达 `analyze`、`transform`、`compare` 等执行边界，不表达业务语义；
- 质量检查、提示和兼容性恢复所需的显式文本标记收敛到 `file_task_quality_markers.py`；它们不能改变前置路由、工具集或任务合同，剩余执行期 fallback 需要在下一轮继续审计；
- 删除基于 financial 关键词自动生成 DOCX 目标路径的逻辑；新文件输出格式必须来自结构化 `target_path`、目标文件标志或任务中明确命名的输出路径。

稳定边界：

- 程序负责授权、目标解析、只读保护和可验证完成条件；模型负责“要做什么”和“怎样组合工具”；
- 通用写入合同必须观察到真实 `file.changed`，但不再预设某个业务 recipe 的工具顺序；
- DOCX 对比批注等已注册原子能力可以保留 capability 事实，不能据此恢复 recipe 评分层；
- 后续若继续清理，应审计 `file_task_quality_markers.py`、`file_task_supervisor_prompts.py` 和 `file_task_quality_gate.py` 中的语义标记，只保留能够由实际文件与工具结果验证的验收条件。

验证：

- 全部 `test_file_task*` 单元测试 339 项通过；
- Kernel、聊天流、架构、启动、工作区与 FileTaskRuntime 跨模块回归 539 项通过；
- Python 编译、全仓测试收集、应用装配和旧 recipe 符号扫描通过。

### 2026-09-05：第十轮

已完成：

- 删除 `task_tools` 的 `globals().update(...)` 环境注入，工具域改为显式依赖和显式导出；同时修复 PDF 工具别名递归和一批此前被动态注入掩盖的未定义符号；
- 删除重复取消模块与 DOCX 表格解包实现；统一后台调度为 `TriggerRegistry → JobRunner → TaskLedger`，删除旧 `TaskScheduler`，并将 `/api/jobs` 收敛为提交/重试入口；
- `UnifiedToolRegistry` 降为只读发布投影并在启动后封存，不再作为第二执行器；
- 删除旧文件索引器，文件问答和增删索引统一使用 Core `RAGService`，同一来源重建时先替换旧分块，删除文件时同步移除向量与词法索引；
- 删除没有消费者的前端 `wsStore/state-kernel` 影子状态，生产 bundle 全量重建；
- 将共享格式化工具下沉到 Core，最后一个搜索工具对 Web 的反向 import 改为由组合根注入的 Core 搜索网关，`app/core → web` 反向依赖降为零；
- 将工作区文档/PDF 路由、文件系统管理路由拆为独立模块；`workspace_assistant.py` 从 2276 行降至 1498 行；
- 将 DOCX 段落分类、标题/目录识别和样式继承拆为独立语义模块；`docx_rich_renderer.py` 从 2715 行降至 1946 行；
- 将写作风格和模型展示辅助逻辑移出 `web/app.py`，主应用文件保持 1120 行预算；
- Python 致命 lint 扩大到 `app/launcher/scripts/src/tests/web`，前端 lint 和 bundle 构建预算加入 CI；移除已无生产依赖的 `schedule` 包。

治理指标：

- 超过 2000 行的生产文件：2 → 0；
- 超过 1500 行的生产文件：16 → 15；计入预算的总行数：29455 → 26410；
- `app/core` 对 `web` 的反向 import：1 → 0；
- 架构预算同步下调到当前值，禁止重新增长。

验证：

- 完整单元测试 4546 项通过，完整集成测试 682 项通过；其余非浏览器测试 405 项复跑通过；
- DOCX、工作区、调度、RAG、工具注册和启动链路均完成针对性回归；
- 前端 lint、TypeScript 检查、58 个测试文件共 225 项测试以及全部生产 bundle 构建/体积预算通过；
- 全仓致命 Python lint、Python 编译和架构审计通过。

剩余结构债务：

- 仍有 15 个超过 1500 行的生产文件，优先候选为 DOCX 主渲染器、文件任务质量门、桌面入口和大型 CSS 分片；
- DOCX 主渲染函数仍接近 1900 行，下一轮应继续按图片、表格和 section renderer 拆分，而不是只做机械分文件；
- Office 生成仍需完成 `document_generator` / `doc_gen_service` 的消费者与保存职责合并；
- 运行时状态路径、提交的生成 bundle 和少量登记过的浏览器全局变量仍属于后续 Phase 8/9 范围。

### 2026-09-06：第十一轮

已完成：

- 将图片编码、浮动/行内图片、Run、超链接、批注锚点和 DOCX 修订标记迁入 `docx_rich_inline_renderer.py`；主渲染器从 1946 行降至 1469 行；
- 将明确短语、页数、原文保留、表格、章节、公式、图表等可由产物验证的要求迁入 `file_task_explicit_quality_gates.py`；质量门主文件从 1931 行降至 665 行；
- 两个新模块均按职责命名和直接导入，不恢复历史 `part_1/part_2` 拼接文件，也不复制质量规则；
- 架构大文件预算继续下调：超过 1500 行的文件 15 → 13，计入总行数 26410 → 22533。

验证：

- DOCX 渲染、图片、修订、渐进预览与真实文档相关 86 项测试通过或按样本可用性预期跳过；
- 质量门核心回归 143 项通过，全部 `test_file_task*` 311 项通过；
- 致命 Python lint、Python 编译、架构审计和大文件回归门禁通过。
