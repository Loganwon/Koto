# Koto 原版工作台实现与验收记录

日期：2026-11-15  
工程：`C:\Users\12524\Desktop\Koto`  
交付范围：当前工程源码、原版工作台前端生产 bundle、新编译 Windows 本地测试包、回归测试与可重复验收脚本。Office/WPS 绑定及兼容入口保留。没有提交、推送或回退原有未提交修改。

## 已实现功能

| 功能 | 实际行为 |
| --- | --- |
| 请求上下文 | 当前文件、选区、检索证据、调入记忆与写作风格实际传到默认 Kernel；稳定系统指令不重复拼接 |
| 模型增量 | OpenAI/DeepSeek 文本增量逐层透传；工具调用分片完整组装、通过校验后才执行；定稿替换草稿；普通聊天不重复追加累计前缀 |
| 工具进度 | 文件工具执行期间发送真实进度；文件执行流完整消费后提交事务，未完成或异常时回滚；观看连接断开后继续同一生产器 |
| 活文档工具 | 默认 Kernel 可在宿主绑定作用域内读取当前文档、按实际版本修改精确锚点、保存并接收独立读回回执 |
| 保存与冲突 | 服务器源文件使用 SHA-256 检查、共享文件锁、备份、原子替换及读回；浏览器文件句柄执行写前哈希检查、写后独立读回；失败保留编辑稿与 dirty 状态 |
| 另存副本 | 单独导出并核对目标自身版本，保留原文件、原句柄和原编辑状态 |
| 操作去重 | 同请求同操作 ID 不重复执行；不同可信请求独立；存在已投递未确认写操作时禁止换 ID 发起新写 |
| 工作台 | 单输入框与任务会话；按需打开文档/成果区；展示生成增量、工具进度、实际差异、保存回执和明确错误 |
| 格式兼容 | DOCX/text/code 使用活文档工具；XLSX/PPTX/PDF 保留原有文件工具工作流与质量门 |
| 持久事件 | TaskLedger 同库 journal 在发布前分配唯一序号；实时流与回放使用同一身份；高层 UI 不重复编号 |
| 取消 | 先登记持久取消请求，实际退出模型流或到达安全工具边界后才确认终态；断线与取消分开 |
| 断线与刷新 | HTTP 断开时将原生成器交给既有 JobRunner 池继续；按 run_id/after_seq/Last-Event-ID 续看并补传；GET 回放不启动执行 |
| 重启续跑 | 普通 Kernel 与文件专属 Runtime 从原消息、工具结果和提交回执继续；保留原质量门；已提交写入不重复执行 |
| 恢复保护 | 文件适配器核对源文件版本与当前工具准入；未知写入结果不盲目重放；宿主/Addon 授权不能凭检查点自动重建；公开 HTTP 请求不能伪造内部 checkpoint/回执/lease |
| 后台作业 | Agent Job 使用相同台账、取消、检查点和事件投影；完整请求参数持久保存；重试采用新运行身份 |
| 输入预算 | 每轮调用前计算预算并保护当前指令与工具配对；本地预算与实际发送的 num_ctx/输出预留一致 |

模型仍按 token 生成草稿，无需改变 Transformer 结构。完整工具调用经过校验才执行；文件提交和保存以真实回执为准。`message.finished` 结束本轮消息，任务是否成功由最终验收和唯一 `run.finished` 决定，验收阻断或修正耗尽均进入失败终态。

## Windows 测试包

[Koto_Original_LocalTest_2026-11-15.zip](sandbox:/C:/Users/12524/Desktop/Koto/build/standalone-diagnostic-20261115-02/Koto_Original_LocalTest_2026-11-15.zip)

大小：497,428,079 字节，约 474.4 MiB。解压到独立目录后运行 `Start_Koto.bat`，保留全部文件及 `_internal` 目录。ZIP 包含 6,024 个文件，CRC 全检及隐私检查通过；SHA-256 已独立复核：

```text
6d6b195f229344d3c9c802af5636d9a685b85277750188478ce56a9cf08d4de7
```

实际新 EXE 已在独立复制、隔离状态目录中隐藏启动，5.39 秒到达 `backend_import_completed`，没有启动错误；随后停止本次测试进程。这只验证后端导入阶段，没有验证 HTTP 健康、浏览器交互或真实模型。该包为未签名本地测试包。

## 运行方式

Windows 本地测试包的完整目录位于 `build/standalone-diagnostic-20261115-02/dist/Koto/`。运行包内 `Start_Koto.bat`，实际程序为 `Koto.exe`；分发时保留整个目录。包内包含已核验 Microsoft 签名的 WebView2 离线安装器，打包验收未执行安装。模型与个人凭据通过应用设置配置，交付包不携带本机个人配置。

使用当前工程的虚拟环境启动源码，加载本次生成的前端资源：

```powershell
cd C:\Users\12524\Desktop\Koto
.\.venv\Scripts\python.exe -m web.app
```

在浏览器打开 `http://127.0.0.1:5000/`；设置了 `KOTO_PORT` 时使用相应端口。桌面入口仍由现有 `Koto_Start.bat` 和启动清单管理。

验收脚本只使用隔离文档和明确标识的假模型，不修改用户原始材料或模型密钥：

```powershell
.\.venv\Scripts\python.exe scripts\standalone_acceptance.py --http-only
```

## 使用流程

| 目标 | 操作 | 判断完成的依据 |
| --- | --- | --- |
| 问答与读材料 | 新建任务，在同一输入框提问；需要材料时附加文件或打开当前文档 | 回答逐步出现，工具记录能看到实际读取结果 |
| 修改文档 | 打开文本或 DOCX，选中要改的内容，描述修改目标 | 当前文档出现实际变化；草稿、已修改与已保存状态分开显示 |
| 保存或另存 | 使用保存入口；另存副本时选择新目标 | 保存成功回执和读回版本一致；失败时编辑稿仍保留 |
| 生成后继续加工 | 要求读取材料并生成报告，随后在同一任务中追问或打开成果 | 成果卡指向实际文件，后续处理保留同一任务上下文 |
| 断线或取消 | 重开页面后从任务列表恢复；停止时使用取消入口 | 恢复只补看原任务；取消先显示停止中，到真实安全边界后才确认终态 |

## 已验证范围

- 前端全量 Vitest：65 个测试文件、267 项通过；TypeScript、修改文件 ESLint 和生产构建通过。
- 最新工作台 bundle 约 516.2 KiB，符合既有 520 KiB 预算。
- 完整集成测试：686 项通过；白盒模型/文件流及受保护源文件回归另有 111 项通过、23 项既有 retired 跳过。
- 真实 DOCX/XLSX/PPTX/文本文件已通过创建、打开、保存、重开流程。
- 隔离 Flask 验收通过实际请求处理器、生产 Kernel 和文件工具，验证增量先于模型结束、实际读取、实际产物写入、事件回放、取消、DOCX 保存独立读回和保存故障保留源文件。
- 恢复测试在工具提交后及 Kernel 完成后模拟中断，重新打开 SQLite 并认领原任务；真实 DOCX 不重复追加，原文件质量门继续执行；外部修改不会被自动覆盖。
- 上下文预算、累计文本/增量、工具分片、保存冲突、重复操作、未知写入保护与后台作业均有独立回归。
- 实际编译运行时另有 36 项流式、工具、取消、验证失败和本地模型协议测试通过；16 个关键模块均核实加载自新编译 `.pyd`，没有退回 Python 源码。
- 新编译版本的文件恢复/文档工具专项 35 项全部通过，生产 Flask 与编译 Kernel 的 8 项完整 API 流程检查全部通过。Cython 对段落列表错误施加强制注解类型的问题已修复，真实 DOCX 提交后中断、恢复与质量门均完成复测。

最终离线 Python 回归分为后端/通用与工作台两个不重叠分片：5,790 项通过、37 项跳过、6 项环境限制排除，失败与错误均为零。两个分片共执行 5,827 项，与离线 collection 的 5,833 项逐项核对，只差明确列出的 6 项；不存在遗漏或重复计数。合并 JUnit 为 `build/standalone-implementation/verified-regression.xml`，覆盖核对为 `verification-summary.json`。前述较早或专项回归互有重叠，不能另行相加。

## 实际边界

1. 活文档语义修改支持纯文本/code 和 DOCX 单段落精确锚点。跨段落 DOCX 替换明确拒绝，不能据此宣称任意复杂排版已获验收。其他格式继续使用既有格式工具。
2. Ollama 纯文字支持流式；含工具的轮次保留非流式兼容，避免原生适配器丢失工具调用。未配置容量时实际发送 num_ctx=8192，明确配置或环境变量优先。
3. 已投递的浏览器写动作没有回执时，保持未知结果并阻止重复写入。浏览器动作去重记录属于进程内状态；跨进程重启通过 Kernel 检查点、文件/编辑器版本和核实流程保护，不宣称任意浏览器动作透明续跑。
4. 测试环境对 localhost 套接字访问也受到限制，宿主 Chrome 与内置浏览器访问测试服务超时；浏览器 URL 策略又拒绝 file 协议。因此真实浏览器与后端联合视觉验收未完成，无法据此判断用户机器的正常模型连通状态。
5. 隔离 API 验收通过 Flask test client 完成。它确实执行生产处理器、工具和文件写入，但不是实际 TCP/浏览器或真实云模型质量验收。
6. 本次已重新编译 225 个模块并生成 Windows 本地测试包。它没有签名，也没有绕过正式发布的源码分类、工作区状态或签名门禁；真实桌面流程仍属于单独未完成的验收范围。

离线全仓回归单独排除了 6 项当前环境无法执行的用例：4 项 Windows asyncio 创建 socketpair 时阻塞、1 项本地状态服务器端口不可访问、1 项 PowerShell 策略阻止加载证据导出辅助脚本。具体节点及原因保存在 `build/standalone-implementation/environment-exclusions.json`。浏览器 E2E 与真实 API 测试也单独列为未验收范围；这些项目不计入通过数量。

## 主要源码位置

| 职责 | 路径 |
| --- | --- |
| Kernel 流式循环与预算 | `app/core/agent/kernel/runtime.py`、`context_budget.py` |
| 模型流与取消 | `app/core/agent/provider_model_gateway.py`、`app/core/llm/openai_provider.py`、`stream_control.py` |
| HTTP 上下文与事件 | `web/services/chat_stream/orchestrator.py`、`agent_handler.py`、`app/core/agent/kernel_step_events.py` |
| 文档工具和宿主绑定 | `app/core/agent/toolkits/builtin/document_ui_plugin.py`、`frontend_observability.py` |
| 编辑器动作与回执 | `web/src/mcp/frontend-observer.ts`、`frontend-observer-document-actions.ts` |
| 保存原子性与冲突 | `app/core/file_assistant/save_service.py`、`web/blueprints/workspace_assistant.py`、`web/src/workspace/save.ts` |
| journal 与续跑 | `app/core/tasks/task_journal.py`、`task_ledger.py`、`app/core/agent/file_task_checkpoint.py`、`app/core/jobs/` |
| 文件专属 Kernel 适配 | `app/core/agent/file_task_kernel_adapter.py`、`file_task_model.py` |
| 工作台事件与恢复 | `web/src/workspace/task-direct-chat.ts`、`task-stream-*`、`task-run-recovery.ts` |
| 可重复验收 | `scripts/standalone_acceptance.py`、`tests/integration/test_standalone_acceptance.py` |

## 最终门禁

| 检查 | 结果 |
| --- | --- |
| 前端测试、类型与生产资源构建 | 通过；267 项前端测试，244 项工作台 Python 检查，均无失败 |
| 核心改动致命 Python lint | 通过 |
| 离线测试 collection 与覆盖核对 | 通过；5,833 项，逐项匹配两个分片及 6 项环境排除 |
| 全仓离线 Python 回归 | 5,790 通过、37 跳过、6 项环境排除；0 失败、0 错误；合并 JUnit 为 `build/standalone-implementation/verified-regression.xml` |
| 实际编译运行时流式与工具回归 | 36 项通过；16 个关键模块身份核实为新编译 `.pyd` |
| 实际编译文件恢复与完整 API 流程 | 35 项专项通过、8 项 API 流程检查通过；来源校验及 446 文件 overlay 隐私检查通过 |
| Windows 产物与前端一致性 | PyInstaller 成功；225 个模块的原生收录检查通过；108 个前端文件逐字节一致；补齐启动入口与离线 WebView2 后，6,024 个文件的包隐私检查通过 |
| ZIP 与可执行程序导入检查 | ZIP CRC 全检、隐私及独立 SHA-256 复核通过；新 EXE 隔离启动至后端导入完成，无启动错误 |
| 真实模型与浏览器联合验收 | 未完成；浏览器访问本地服务受当前环境限制，真实云模型质量另需实测 |

这一记录区分实现、离线行为验证和真实运行验收；最后一项门禁未完成前，不标记为已完整实机验收的发布版本。
