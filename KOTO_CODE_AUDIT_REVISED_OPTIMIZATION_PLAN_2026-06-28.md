# Koto 代码审计校准版优化方案

日期：2026-06-28

来源：对 `C:\Users\12524\Desktop\Koto_Code_Audit_2026-06-28.md` 的校准复核，以及当前 Koto 工作树、既有架构文档、守护测试的对照。

## 1. 总体判断

原审计报告的方向基本成立，但不能直接按其 P0/P1 执行。它准确指出了 Koto 仍存在的几类结构债务：

- `web/` 仍承载部分核心业务逻辑；
- Agent、LangGraph、旧 AgentLoop、文件任务 runtime 存在多条执行路径；
- 文件 CRUD、安全检查、备份逻辑在多个层次重复；
- 前端 TypeScript、ESLint、bundle、vendor、构建脚本仍有明显收敛空间；
- CI/发布配置存在重复定义、版本不一致和路径硬编码。

同时，原报告存在统计口径和路径漂移问题：

- `web/app.py` 当前约 3501 行，不是报告概览中的 3038 行；
- `app/core/agent/` 顶层 `.py` 当前为 120 个，递归统计为 145 个，数字以 `scripts/audit_code_baseline.py` 为准；
- TODO/FIXME “仅 1 处”的结论不严谨，扫描会命中配置、示例、文档、构建产物和真实 TODO；
- `web/build-bundles.mjs` 路径已不准确，当前实际路径是 `web/scripts/build-bundles.mjs`；
- `workspace.css` 的主题覆盖问题需要浏览器验证，不能简单按 `:root` 覆盖定性；
- “删除/合并 Agent 三套实现”过于激进，当前仍有生产入口和测试依赖。

因此，本方案采用“先收敛配置和契约，再合并执行内核，最后退役兼容路径”的顺序。

## 1.1 2026-06-30 执行校正

外部审计报告的 P0 项需要重新排序后执行：

- `agent_loop.py` / `LangGraphAgent` / `UnifiedAgent` 不作为第一轮删除或合并对象。当前已有入口矩阵和 legacy facade 拆分，第一轮只继续封死旧入口、补契约测试，等 editor AI、socket doc AI、chat stream 全部迁移后再退役实现。
- 文件 CRUD 收敛不等于删除 `file_tools.py` 或 `fs_service.py`。这两个模块分别承载 Agent 工具字符串响应和 workspace UI JSON 契约，第一轮采用“委托 `FileService` + 保留入口契约”的方式。
- 依赖拆分只移动真正的测试/开发工具：`pytest*`、`hypothesis`、`mutmut`、`locust`。`send2trash` 是运行时删除到回收站能力，必须留在 runtime requirements 并加版本约束。
- 大规模 web 业务迁移、PPTX 双引擎合并、TypeScript strict 全开启都暂缓到守护测试和入口矩阵完善后分批做。

## 2. 执行原则

1. 不按文件名判断废弃状态，先确认生产入口、测试入口、打包入口和前端调用。
2. 不一次性删除兼容路径，先迁移调用方，再用守护测试锁定缺口。
3. 对用户可见链路优先保行为：文件任务、编辑器 SSE、workspace 前端、PPT/DOCX/XLSX 生成必须逐步验证。
4. 每一阶段都要留下可复跑的验证命令或 guard test。
5. 继续沿用既有架构方向：`web.app` 只保留入口和兼容别名，新实现进入 blueprint、service、runtime context 或 `app/core`。

## 3. 优先级总览

| 阶段 | 主题 | 风险 | 收益 | 目标 |
| --- | --- | --- | --- | --- |
| P0 | 证据化和低风险配置清理 | 低 | 高 | 修正审计口径，清理明显重复配置 |
| P1 | 前端构建与质量门槛收敛 | 中 | 高 | TypeScript/ESLint/build alias/vendor 管理进入可持续状态 |
| P1 | 文件 CRUD 内核统一 | 中 | 高 | 统一安全、路径、备份语义，保留各入口响应契约 |
| P2 | 路由/文件任务分类收敛 | 中高 | 高 | 减少重复 LLM 判断，建立路由结果传递契约 |
| P2 | Agent 执行路径退役计划 | 高 | 高 | 明确 `UnifiedAgent`、`LangGraphAgent`、`KotoAgentLoop` 的边界 |
| P3 | `web/` 业务逻辑继续迁移 | 中高 | 中高 | 缩小 `runtime_context.py` 和 `web.app` 兼容面 |
| P3 | PPT/workflow/skill 双路径治理 | 中 | 中 | 先建路由矩阵，再统一服务层 |

## 4. P0：证据化和低风险配置清理

第一轮实际执行范围：

- 运行时 requirements 去除 dev-only 测试工具，新增 `config/requirements-dev.txt`；
- `send2trash` 保留在 runtime requirements，并显式约束版本；
- 增加发布守护测试，阻止 pytest/hypothesis/mutmut/locust 回流到 runtime requirements；
- Agent 文件工具的基础 CRUD 开始委托 `FileService`，不改变工具层返回文本和 registry 同步契约。
- Workspace 文件助手的文件级 create folder / rename / copy / move / delete 也开始复用 `FileService`，目录递归操作暂时保留在 `WorkspaceFsService`，以维持前端文件树 JSON 契约和目录语义。
- `FileService` 已补齐 `delete_path` / `copy_path` / `move_path`，Workspace 文件助手的目录级 copy / move / delete 也改为委托 canonical 服务；`WorkspaceFsService` 只保留前端参数校验、去重命名和错误码映射。
- Agent 文件工具的批量重命名、批量移动、重复文件清理和撤销 rename / move / copy 也已改为复用 `FileService`；`file_tools.py` 中剩余直接删除只限压缩失败时清理刚创建的输出文件。
- 已新增 `scripts/audit_code_baseline.py`，固定当前 checkout 的审计统计口径：`web/app.py` 行数、agent 文件数、过滤后的 TODO/FIXME、bundle/vendor 体积、`web.app` 导出和 Agent 入口命中清单。
- 已增加 `tests/unit/test_audit_code_baseline.py`，防止 TODO/FIXME 统计重新扫入 tests/docs/vendor/build 等噪声。
- `koto.spec` / `build_cython.py` 的 protected dirs 已经由 `build_config.py` 单源化；`koto.spec` 也在自动发现 app/web hiddenimports 后做保序去重，先消除重复输入，不直接删除手写兜底清单。
- `.pre-commit-config.yaml` 的 bandit hook 引用 `setup.cfg`，`setup.cfg` 已补齐 `[bandit]` 配置并由发布守护测试覆盖。
- `release.yml` 中官方基础 actions 已与 `build.yml` / `ci.yml` 对齐为 `checkout@v4`、`setup-python@v5`、`upload-artifact@v4`、`download-artifact@v4`，并修复 Job 编号注释错位。
- Inno Setup 编译器路径发现已抽到 `scripts/resolve_inno_setup.ps1`，`Build_Release.ps1`、`build.yml`、`release.yml` 均调用该脚本，避免三处候选路径漂移。

### 4.1 建立审计校准基线

已通过 `scripts/audit_code_baseline.py` 固定以下统计口径：

- `web/app.py` 行数；
- `app/core/agent/` 顶层与递归 `.py` 数量；
- 生产代码 TODO/FIXME 数量，排除构建产物、vendor、示例和文档；
- 前端 bundle 文件大小；
- `node_modules` 与 `static/vendor` 体积；
- `web.app` 兼容导出列表；
- Agent 三条路径的生产调用点和测试调用点。

当前基线输出：

- `web/app.py`：3501 行；
- `app/core/agent/`：顶层 120 个 `.py`，递归 145 个 `.py`，递归体积 2006725 bytes；
- 过滤后的 TODO/FIXME：11；
- 主要 bundle：`sheets-main.js` 10616976 bytes，`workspace-bundle.js` 1082980 bytes，`tiptap-docx-bundle.js` 517261 bytes；
- 目录体积：`web/node_modules` 386823206 bytes，`web/static/vendor` 17989111 bytes；
- Agent 命中：`KotoAgentLoop` 3 个文件，`LangGraphAgent` 8 个文件，`UnifiedAgent` 40 个文件，`FileTaskRuntime` 24 个文件。

验收：

- `python scripts/audit_code_baseline.py`
- `python scripts/audit_code_baseline.py --json`
- `python -m pytest tests/unit/test_audit_code_baseline.py -q`

### 4.2 构建配置去重

优先处理低风险重复：

- 已将 `koto.spec` 与 `build_cython.py` 中的 protected dirs 提取为单一配置源；
- 已梳理 `koto.spec` 手写 hiddenimports 与 `_discover_hidden_imports()` 的关系，并在 `Analysis` 前保序去重；完整构建验证前暂不删除手写兜底清单；
- 已统一 `build.yml` / `release.yml` 中 Python、artifact action 版本；Inno Setup 发现逻辑已抽到共享 PowerShell 脚本；
- 已修复 `release.yml` Job 编号注释错位；
- 已修复 `.pre-commit-config.yaml` 引用 `setup.cfg` 但缺少 `[bandit]` 配置的问题；
- 已清理 `config/requirements.lock` 中仍锁定但主 requirements 不再声明的 dev-only 包，例如 `pytest*` 和 `pyaudio`，并由发布守护测试覆盖 runtime/dev/lock 的边界。

验收：

- `python -m py_compile build_cython.py`
- 能运行一条不打包的 spec/hiddenimport 静态校验；
- `python -m pytest tests/unit/test_release_packaging_guards.py -q`
- CI workflow YAML 能被解析；
- requirements lock 重新生成或有明确注释说明保留原因。

## 5. P1：前端构建与质量门槛收敛

### 5.1 TypeScript 和 ESLint 分阶段开启

不建议直接把 `strict: true` 一步打开。更稳的顺序：

1. 先保持 `strict: false`，开启局部规则：`noUnusedLocals`、`noUnusedParameters`、`noFallthroughCasesInSwitch`；
2. 给 `web/eslint.config.js` 增加基础规则，先覆盖新 TS 源，不扫构建产物；
3. 针对 `web/src/workspace/*` 先加类型守护，避免 workspace 前端迁移倒退；
4. 最后再逐目录开启 strict 或 `strictNullChecks`。

当前执行状态：

- 已保持 `strict: false` / `noImplicitAny: false`，避免把历史 unused/implicit-any 债务一次性变成构建阻塞；
- 已开启 `noFallthroughCasesInSwitch`，并通过 `tests/unit/test_frontend_quality_config.py` 固定渐进式 TypeScript 门槛；
- `web/eslint.config.js` 已限制到 `web/src/**/*.ts(x)`，忽略 `node_modules/**` 和 `static/**`，并以 warning 形式覆盖 `no-fallthrough`、重复 import、常量二元表达式、unused 与 `prefer-const`；
- 已修复 `web/src/workspace/task-runner.ts` 中一个真实的 constant-binary-expression 死 fallback，lint warning 从 430 降到 429；
- `npm --prefix web run typecheck`、`npm --prefix web run lint`、`npm --prefix web run build` 均可通过。

验收：

- `npm --prefix web run build`
- `npm --prefix web run lint` 或新增等价脚本；
- `pytest tests/unit/test_frontend_button_route_contract.py -q`
- workspace bundle 重新构建后浏览器 smoke test 通过。

### 5.2 构建 alias 单源化

原审计中提到 alias 容易在 `web/vite.config.ts` 和 `web/scripts/build-bundles.mjs` 间重复。当前实现已经收敛到 `web/build-aliases.mjs`，Vite 和 bundle 构建脚本都通过 `createAliases()` 消费同一份配置。

当前执行状态：

- `web/vite.config.ts` 和 `web/scripts/build-bundles.mjs` 已共同使用 `web/build-aliases.mjs`；
- `tests/unit/test_frontend_quality_config.py` 已新增 bundle 构建链 guard，固定 `npm run build` 的真实脚本、bundle entry 清单、IIFE 输出格式、`emptyOutDir: false`、模板引用和构建产物存在性；
- guard 覆盖 `auth-bundle`、`app-bundle`、`skills-ui-bundle`、`skills-panel-bundle`、`workspace-bundle`、`review-bundle`、`skill-marketplace-bundle`、`skill-community-bundle`，避免新增或迁移入口时只改源码不改模板/输出。

验收：

- `@workspace`、`@chat`、`@skills`、`@review`、`@shared` 只在共享配置中定义一次；
- Vite 构建和 esbuild 脚本都消费同一份配置。
- `pytest tests/unit/test_frontend_quality_config.py -q`
- `npm --prefix web run typecheck`
- `npm --prefix web run build`

### 5.3 Vendor 和包体治理

先做观测，不立刻大规模迁移：

- 建立 bundle size budget 报告；
- 明确 `web/static/vendor` 中哪些是运行时必需、哪些可从 npm 管理；
- 先清理完全未引用 vendor，再考虑 npm workspace；
- 对 Univer、TipTap、workspace bundle 分别建立加载路径和缓存策略。

当前执行状态：

- 已新增 `config/frontend_asset_budgets.json`，对 `sheets-main.js`、`workspace-bundle.js`、`tiptap-docx-bundle.js` 和 `web/static/vendor` 设置当前 checkout 附近的小幅余量预算；
- `scripts/audit_code_baseline.py` 已输出 `frontend asset budgets`，同时支持 JSON 字段 `asset_budget_status`；
- `tests/unit/test_audit_code_baseline.py` 已覆盖预算报告结构，并校验当前 checkout 的前端资产不超预算；
- 当前预算状态均为 ok：`sheets-main.js` 10616976 / 11200000，`workspace-bundle.js` 1082980 / 1150000，`tiptap-docx-bundle.js` 517261 / 550000，`web/static/vendor` 6510883 / 6800000。
- 已新增 vendor 包级引用图，`scripts/audit_code_baseline.py` 现在输出 `vendor_reference_graph`，按 `web/static/vendor` 顶层包统计体积和生产源码引用文件；
- 当前引用图显示 `d3`、`font-awesome`、`highlight.js`、`katex`、`marked`、`mermaid`、`pdfjs-dist`、`split.min.js`、`tailwindcss` 仍有生产引用；
- 已清理无生产引用的旧 `web/static/vendor/univer`，释放约 11224742 bytes；当前 XLSX 实际运行时仍走 `/static/univer-dist/assets/sheets-main.js`，并由 installer/static-asset 测试继续覆盖；
- 已清理无生产引用的 `floating-ui`、`react`、`rxjs`，并同步修正 `scripts/download_vendors.py`，避免这些 retired 目录被重新下载；
- `scripts/download_vendors.py` 已对齐当前静态引用：Tailwind 下载 `tailwindcss/tailwind-play-cdn.js`，PDF.js 下载 `pdfjs-dist/3.11.174/build/pdf.min.js` 与 `pdf.worker.min.js`；
- 当前 vendor 引用图没有剩余无引用顶层包。

验收：

- 静态引用图说明每个大 vendor 的入口；
- 清理项有前端路由和浏览器验证；
- 不因包体优化破坏 DOCX/PPTX/XLSX 编辑器加载。

## 6. P1：文件 CRUD 内核统一

原报告认为三层 CRUD 应“仅保留 `file_service.py`”。这个方向需要修正为：统一内核，保留入口契约。

### 6.1 当前边界

- `app/core/services/file_service.py`：适合作为安全、备份、基础 CRUD 的核心；
- `app/core/file/file_tools.py`：Agent 工具入口，还包含增强读取、摘要、搜索、PII 等语义；
- `app/core/file_assistant/fs_service.py`：workspace 文件树和 UI API 的响应契约；
- `app/core/agent/plugins/file_editor_plugin.py`：Agent 工具适配层，已委托 `FileService` 的部分能力。

### 6.2 收敛顺序

1. 抽出共享路径策略：workspace root、safe path、覆盖策略、trash/backup 策略；
2. 让 `fs_service.py` 的 create/delete/copy/move 委托共享内核，但保持原 JSON shape；
3. 让 `file_tools.py` 的基础 CRUD 委托共享内核，保留增强工具逻辑；
4. 最后删除重复的安全检查和备份实现。

验收：

- `pytest tests/unit/test_task_tools_file_task_contracts.py -q`
- `pytest tests/integration/test_file_hub_routes.py -q`
- `pytest tests/integration/test_workspace_assistant_routes.py -q`
- 真实 workspace 文件创建、移动、删除、撤销/备份 smoke test。

## 7. P2：路由与文件任务分类收敛

原报告指出 routing 层与 Agent/file-task 层重复分类，这个问题成立，但不能简单删除 Agent 侧判断。

### 7.1 目标契约

建立一个 `TaskRoutingDecision` 或等价结构，在一次请求中传递：

- 原始输入；
- routing 层分类、置信度、候选 workflow；
- 文件上下文；
- 是否需要二次意图裁决；
- 最终工具/执行路径；
- 用于前端展示的分类标签和计划步骤。

当前执行状态：

- 已建立等价结构 `FileTaskRoutingDecision`，`FileTaskRequest.from_mapping()` 同时兼容顶层 `routing_decision`、`route_decision`、`workspace_route_intent` 和 `options.workspace_route_intent`；
- `FileTaskRuntime` 已构造 `decision_context`，把 routing decision、classification、intent plan、requirements、plan check、intent adjudication 和 effective planner 聚合后返回给前端；
- 高置信度且明确为 `file_task` 的 routing decision 已可跳过默认 `TaskClassifier`/AI 意图裁决；模糊写入、读写边界不清等情况仍保留二次裁决；
- 本轮补齐 routing decision 的可选契约字段：`candidate_workflows`、`requires_adjudication`、`final_tool_path`、`frontend_label`、`plan_steps`，用于后续把分类标签、候选 workflow 和前端执行计划串起来；
- `web/src/workspace/task-dispatcher.ts` 已透传并清洗这些可选字段，保持旧 payload 兼容。
- 已将 routing 层 `RuleRouter.should_use_annotation_system()` 的 DOCX 审阅/批注判断收敛到 `app/core/agent/file_task_review_intent.py::should_use_docx_review_system()`，避免 routing 与 file-task 对“润色/批注/翻译腔”等关键词各自维护一份规则。
- 已将 `routing_rule_chain` 的 DOCX file-edit 快速规则接入 `should_route_docx_file_edit()`；md/txt workflow 编辑仍保留原 `EDIT_INTENT_KEYWORDS`，避免把非 DOCX 编辑路由收窄。

### 7.2 收敛顺序

1. 先让 `FileTaskRuntime` 接收可选 routing decision；
2. 在 decision 置信度足够时跳过重复 LLM 分类；
3. 只在文件语义不明确、用户指代模糊、读写边界不清时触发 `_adjudicate_intent_if_needed()`；
4. 继续将关键词规则拆到共享 intent pattern 模块，routing 和 file-task 都引用；DOCX 审阅/批注与 DOCX file-edit 快速判断已先完成单源化；
5. 最后移除重复规则。

验收：

- “先搜索金价，再生成 Excel 图表”仍能走多步计划；
- 文件只读总结不会误写；
- DOCX 审阅/批注/翻译意图仍能区分；
- 前端展示分类、执行计划、实际工具、产物文件一致；
- `pytest tests/unit/test_file_task_runtime*.py -q`
- `pytest tests/unit/test_file_task_routing_decision_contract.py -q`
- `pytest tests/unit/test_docx_review_intent_routing_shared.py -q`
- `pytest tests/unit/test_ai_task_chain_architecture.py -q`
- `npm --prefix web run typecheck`
- `npm --prefix web run build`
- 必要时加 Playwright workspace E2E。

## 8. P2：Agent 执行路径退役计划

原报告的“合并 `unified_agent.py` + `langgraph_agent.py`，删除 `agent_loop.py`”不应作为第一步。

### 8.1 先建立入口矩阵

需要确认并记录：

- `UnifiedAgent`：目标任务、后台 job、技能注入、完整工具链；
- `LangGraphAgent`：chat stream 的 AGENT fallback、dev 路由、LangGraph 工作流兼容；
- `KotoAgentLoop`：editor AI stream、socket doc AI、旧 editor 快捷操作；
- `FileTaskRuntime` / `ToolStepRunner`：workspace 文件任务和计划任务。

### 8.2 退役顺序

1. 先把 `KotoAgentLoop` 的活跃入口迁移到明确的新执行器，保留事件格式兼容；
2. 把 tests 从旧模块导入迁移到新执行器或兼容 facade；
3. 为旧入口添加 deprecation guard，禁止新增生产调用；
4. 再决定 LangGraph 是主后端、实验后端，还是只保留 workflow runtime；
5. 最后删除旧实现。

当前执行状态：

- 已建立 `docs/AGENT_EXECUTION_ENTRYPOINT_MATRIX.md`，记录 `FileTaskRuntime`、editor SSE executors、doc WebSocket executor、`UnifiedAgent`、`LangGraphAgent` 和 retired `KotoAgentLoop` 的当前入口与迁移方向；
- `KotoAgentLoop` 已是 fail-closed shim，`run()` 会抛出 retired runtime error；
- `tests/unit/test_ai_task_chain_architecture.py` 已禁止生产代码重新 import / instantiate `KotoAgentLoop`，并要求入口矩阵记录 `agent_production_entrypoint_hits` 审计字段；
- `scripts/audit_code_baseline.py --json` 已输出 `agent_production_entrypoint_hits`，当前 `KotoAgentLoop` 生产入口命中为 `[]`，全量 `agent_entrypoint_hits` 仍保留 tests 和 shim 命中用于历史对照。

验收：

- editor AI SSE 事件不变；
- socket doc AI 行为不变；
- UnifiedAgent 工具调用测试通过；
- LangGraphAgent run/stream 兼容测试通过或被明确迁移；
- `rg "agent_loop|KotoAgentLoop|LangGraphAgent|UnifiedAgent"` 的结果与入口矩阵一致。

## 9. P3：`web/` 业务逻辑继续迁移

这部分与既有 `ARCHITECTURE_STABILIZATION_PLAN.md` 和 `LEGACY_CODE_PATH_AUDIT.md` 保持一致。

### 9.1 当前正确方向

- `web.runtime_context.py` 是迁移桥，不应在第一阶段移除；
- `web.app` 继续缩小为入口、compat export 和少量运行时 glue；
- 新业务逻辑进入 `web/blueprints/*`、`web/services/*` 或 `app/core/*`；
- 对仍在 `web/` 但属于核心服务的模块，先迁移测试和调用方，再移动文件。

当前执行状态：

- `tests/unit/test_architecture_guardrails.py` 已守住 `web.app` route surface、line budget、生产 direct import、`get_app_attr(...)` 和 `call_app_factory(...)` 生产调用边界；
- 本轮将 `app/core/agent/file_task_model.py` 的 `from web import app as ...` 改为通过 `web.runtime_context.get_model_map()` 获取模型路由，避免 `app/core` 直接依赖 `web.app`；
- direct import guard 已扩展到 `from web import app as ...` 这类 package-level 绕过形式；当前生产 `app/` 和 `web/` 中没有直接 `web.app` import。
- `WEB_APP_LINE_BUDGET` 已从 3525 收紧到当前实际 3501 行，后续迁出业务逻辑后继续向下 ratchet。
- 本轮将 `MemoryToolsPlugin` 和 `SkillRecorder` 中通过 `sys.modules` 触碰 `web.app` 的隐性访问改为 `web.runtime_context` 命名 helper；架构 guard 已禁止除 `web/runtime_context.py` 之外的生产代码直接检查 `sys.modules["web.app"]`。
- `TaskOrchestrator._merge_results` 已拆为 `web.task_orchestrator_results.merge_task_results()` 纯函数，原 classmethod 仅保留兼容委托；`TASK_ORCHESTRATOR_LINE_BUDGET` 已从 230 收紧到当前实际 199 行。
- `web/file_task_stream.py` 与 `web/services/chat_stream/` 的 app/core 迁移候选清单已落到 `docs/WEB_SERVICE_MIGRATION_CANDIDATES.md`，并由 `tests/unit/test_architecture_guardrails.py` 强制覆盖关键路径、核心依赖和 `web.app` 禁区。
- `web/services/chat_stream/generate/regular_handler.py` 的初始模型选择、本地快速通道判定和首 token 等待时间已抽到 `app.core.llm.chat_generation_policy`，并补单测与架构守卫；web handler 继续保留 SSE/session/runtime 责任。

### 9.2 建议顺序

1. 继续迁移 `web.app` chat wrappers 的测试导入；
2. 把剩余模型/client 全局访问收进显式 runtime accessor；
3. 将 `TaskOrchestrator._merge_results` 变为纯函数或结果组装服务；已完成，后续继续迁出剩余 class wrapper；
4. 对 `web/file_task_stream.py`、`web/services/chat_stream/` 建立 app/core 迁移候选清单；已完成，后续按清单先补行为契约测试再移动代码；
5. 每移出一块，降低 `web/app.py` line budget。

验收：

- `tests/unit/test_architecture_guardrails.py`
- `web.app` line budget 不回升；
- 生产代码不直接 import `web.app`；
- `get_app_attr(...)` 和 `call_app_factory(...)` 不重新出现在生产调用方。

## 10. P3：PPT、workflow、skill 双路径治理

### 10.1 PPT

当前确有两条生成路径：

- `doc_gen_plugin.py` -> `services/doc_gen_service.py.generate_presentation()`;
- `ppt_plugin.py` -> `web/ppt_master.py` / `web/ppt_generator.py`。

建议先建立“生成、编辑、模板、下载、任务流”的路由矩阵，再抽公共 PPT rendering service。不要先删除任一路径。

当前执行状态：

- PPT / workflow / skill 路由矩阵已落到 `docs/PPT_WORKFLOW_SKILL_ROUTE_MATRIX.md`，明确 `DocGenPlugin.create_presentation`、`PPTPlugin.generate_ppt`、`web.task_orchestrator_ppt.execute_ppt_multi_step` 和 PPTX 编辑 API 的不同 owner；
- `PPTPlugin` 已改为依赖 `app.core.services.ppt_generation_service` facade，不再直接 import `web.ppt_master` / `web.ppt_generator`；当前实现仍由 facade lazy-load 旧 web 模块，后续可继续把具体 planner/generator 迁出；
- `web.task_orchestrator_ppt.execute_ppt_multi_step` 已切到同一个 `PPTGenerationService` facade，避免任务流 PPT 与 Agent PPT 继续各自直连旧 web planner/generator；
- `web.task_orchestrator_filegen.execute_file_gen` 的单步 PPT fallback 也已切到 `PPTGenerationService` facade，保留现有质量门控、主题选择、自动配图和进度回调；
- 单步 PPT fallback 原本内嵌的 Markdown 大纲解析和主题关键词判断已抽到 `app.core.services.ppt_generation_service`，并补单测锁定 `[对比]` / `[过渡页]` 等旧格式行为；
- `web.template_library.TemplateLibrary._generate_pptx_from_template` 已切到同一个 `PPTGenerationService` facade，facade 现在会规范化旧 generator 返回值中的 `success` / `output_path` 元数据，避免模板路径直接依赖 `web.ppt_generator` 的返回细节；
- `web.ppt_api_routes.render_pptx` 已切到 `PPTGenerationService.render_editor_pptx()`，保留 session ownership 与响应格式，移除编辑 API 对 `web.ppt_generator` 的直接依赖；
- `app.core.services.ppt_generation_contract` 已拆出纯契约 helper，承接 slide normalization、fallback outline、Markdown outline parsing、theme selection 和 renderer result normalization；`PPTGenerationService` 只保留 planner/generator lazy-load 与调用编排；
- `app.core.services.ppt_generation_legacy_adapter` 已拆出旧实现 lazy-load 边界，`PPTGenerationService` 不再直接 import `web.ppt_master` / `web.ppt_generator`，后续替换具体实现只需改 adapter；
- `web.ppt_pipeline.PPTGenerationPipeline` 已确认为 dormant legacy module，当前无生产调用方；新增架构守卫，限制直接 `web.ppt_generator` import 只出现在 `ppt_generation_legacy_adapter`，并防止生产路径重新接入旧 pipeline；
- workflow 元数据目录已从 `web.blueprints.workflow_api` 移入 `app.core.workflows.catalog`，`/api/workflow/list` 通过 core catalog 返回原有 shape，避免 web 层保留重复 `_WORKFLOW_REGISTRY`；
- workflow Python executor lookup 已从 `web.blueprints.workflow_api` 移入 `app.core.workflows.registry`，web 蓝图保留上传、下载、SSE transport，执行器 owner 回到 `app/core`；
- workflow 执行前校验、chat-only 拦截和 executor 加载失败处理已移入 `app.core.workflows.execution`，`workflow_api.py` 只保留 Flask JSON/SSE 包装；
- workflow 上传临时目录、文件名规整和下载路径校验已移入 `app.core.workflows.file_store`，`workflow_api.py` 保留 Flask request/response 外壳；
- workflow-like builtin skill 到 deterministic workflow executor 的映射已落到 `app.core.workflows.skill_mapping`，覆盖同 ID 直连、宽泛 affinity 和需要意图判定的候选关系；
- workflow catalog 现在从 `skill_mapping` 派生 `related_skill_ids`，让 `/api/workflow/list` 的公开元数据能与技能面板/路由层使用同一映射源；
- 架构 guard 已阻止 `workflow_api.py` 重新增长逐个 workflow 的 direct import 表或重复元数据注册表。

验收：

- PPT 生成 API、任务流 PPT 生成、PPTX 编辑器分别有 smoke test；
- 样式、字体、模板选择逻辑只有一个最终 owner。

### 10.2 Workflow 与 Skill

`app/core/workflows/*` 与 `builtin_skills.py` 中的同 ID 能力并存，说明“能力声明”和“执行器”边界不清。

建议：

- 将 builtin skill 定位为能力声明和 prompt 注入；
- workflow 模块定位为确定性执行器；
- 建立 skill id -> executor id 映射；
- 禁止同一能力在两个入口独立演化。

验收：

- 五个重复 ID 有映射表；已完成，且扩展覆盖 `multi_doc_synthesis`、`spreadsheet_analyst`、`excel_data_cleaner`、`contract_reviewer`、`legal_doc_review` 等非一一对应能力；
- 前端技能面板、workflow 执行、SSE 状态展示路径一致。

## 11. 暂不建议立刻做的事

- 不要立刻删除 `agent_loop.py`；
- 不要立刻把 `LangGraphAgent` 合并进 `UnifiedAgent`；
- 不要立刻删除 `runtime_context.py`；
- 不要直接开启全仓 TypeScript strict；
- 不要只按 `TODO/FIXME` 关键词清理代码；
- 不要仅凭 `web/` 路径判断模块应该移动；
- 不要在没有真实文件任务验证的情况下调整文件任务路由。

## 12. 第一轮可执行任务包

建议先从以下 6 个小任务开始，每个都能单独验证：

1. 新增审计统计脚本或文档命令，修正原报告数字。
2. 提取构建 protected dirs 单一配置源。
3. 统一 `web/vite.config.ts` 与 `web/scripts/build-bundles.mjs` 的 alias 定义。
4. 给 `web/eslint.config.js` 加基础规则，并只覆盖 `web/src/**/*.ts`。
5. 为文件 CRUD 共享路径策略写一个小型 adapter，不改响应 shape。
6. 建立 Agent 入口矩阵文档，先禁止新增 `KotoAgentLoop` 生产入口。

推荐验证集合：

```powershell
python -m pytest tests/unit/test_architecture_guardrails.py -q
python -m pytest tests/unit/test_frontend_button_route_contract.py -q
python -m pytest tests/unit/test_task_tools_file_task_contracts.py -q
npm --prefix web run build
```

如果触及 workspace 前端或文件任务，还需要追加真实前端 smoke test，至少覆盖：

- 发送一个普通对话；
- 执行一个真实文件读取/修改任务；
- 执行一个多步任务，例如“先搜索金价，再生成 Excel 图表”；
- 检查前端分类标签、执行计划、工具选择、产物文件。
