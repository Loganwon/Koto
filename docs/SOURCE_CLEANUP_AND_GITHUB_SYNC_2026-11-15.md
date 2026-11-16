# Koto 原版源码清理、运行优化与 GitHub 同步

日期：2026-11-15（America/Los_Angeles）。工程：`C:\Users\12524\Desktop\Koto`。

本轮继续维护原版独立工作台，保留同一个 Kernel、ToolCatalog、TaskLedger 和 Office/WPS 宿主适配器。重点是清掉已无入口的旧实现、补齐干净环境启动与 CI、将经过检查的完整源码同步到 GitHub。

## 实际清理

| 范围 | 已完成的改动 | 保留的能力 |
| --- | --- | --- |
| 后端 | 退休 `web/code_generator.py`、`web/files/filegen_time_context.py`、`app/core/services/feedback_loop.py`、`quality_evaluator.py`、`search_service.py` | 活跃 Kernel 工具、文档验收、真实搜索与宿主适配器 |
| 前端 | 删除无宿主 DOM 的小游戏、20 条无界面消费者的事件映射、旧聊天标题样式及重复滚动实现 | 当前工作台滚动、读者暂停跟随、兼容功能 API |
| 文档与测试 | 移除只服务于上述退役实现的 52 项旧单测，保留混合测试文件中的其它覆盖；更新 AGENTS 实现指标及禁止回流说明 | 真实功能测试、文件保护和架构所有权约束 |
| 代码规范 | 使用现有版本的 Black/isort 对公开 Python 源码归一；Black 检查自身格式化的 AST 等价性，导入排序另经行为回归 | 私有文件不改；没有降低格式和 lint 门槛 |

后端删除前检查了生产导入、注册、配置字符串、脚本及 companion 引用。未将“只有包导出”或“文件很大”直接视为可删依据。仍有真实消费者的 XLSX、文档生成、审阅和兼容实现继续保留。

源码提交还会包含此前已在本地完成、尚未推送的架构迁移及改进，不能将整个提交相对旧 main 的删除量都归为本轮新增清理。

## 前端优化与资源

滚动桥统一使用当前消息容器，监听幂等；普通滚动尊重读者锁，显式查看最新仍可定位到底部。新增双向模板事件检查，既发现缺少 handler 的界面事件，也发现没有消费者的旧映射。

本轮主启动包从 158441 降至 155692 字节，模板事件包从 22895 降至 21375 字节。主工作台包维持 524518 字节，未提高任何既有预算。完整 TypeScript、ESLint、80 个测试文件中的 370 项测试及全部 17 个入口构建预算通过。

`web/static/univer-dist/assets/sheets-main.js` 和 CSS 是当前 XLSX 必需资源，继续发布。21MB 的 `.js.map` 仅提供开发调试源码映射，从 GitHub 源码发布范围排除但保留本地；可由 `web/univer-editor` 源码及 lock 重建。CI 现在也安装并构建该独立编辑器，不能只构建主前端。

## 依赖与部署修复

补齐锁文件缺失的 Flask-WTF、OpenAI、html2docx、EbookLib、send2trash 及对应新增依赖，修正 python-json-logger 的直接需求与锁定版本冲突；清掉已无生产调用的 schedule 直接依赖。新增检查覆盖直接需求、精确版本、平台标记与可选关键导入。

这些检查不等价于所有平台上的全新安装、完整依赖求解或 CVE 扫描。没有批量升级无关包或用版本估计冒充求解结果。

Docker 现在复制真实入口所需的 `src.runtime_bootstrap` 和 `src.config_validator`。无效位置的 ignore 文件移到构建上下文根目录，排除本地环境、Git 历史、私有数据与构建包；保留可复制的环境配置模板。Compose 增加 `/app/data` 持久卷、明确认证及 DeepSeek 环境变量，健康请求增加超时。

5 项隔离入口测试按实际 Dockerfile COPY 构造临时布局，导入真实 server/bootstrap/validator；删除 bootstrap 的旧布局确实无法导入。业务/provider 使用局部替身，未进行网络请求。本环境没有 Docker CLI，因此未声称实际镜像构建、容器联网或生产部署通过。

CI 增加公开源码检查、依赖契约与导入、固定办公任务；干净前端环境会安装主前端、TipTap 和 Univer 子依赖。容器退出或健康请求失败会使 CI 失败。Black 26.5.1、isort 5.9.3、flake8 7.3.0 与 pre-commit 保持一致。CodeQL 不再全局屏蔽 XSS、注入、SSRF 或路径类问题；既有 Bandit advisory 状态及正式签名门禁没有冒充为新通过结果。

## GitHub 与私有数据

已通过带预期 SHA 检查的快进更新，将公开 main 更新到安全清理提交：

`252baf502fdad81b70aec23969cfa5e56e734b0a`

该提交移除远端当前树的 `config/.builtin_key`、`jwt_secret.txt`、`email_accounts.json`、`context/user_background.json`、`memory_summaries.json`、`file_task_plans.json` 和 `file_task_followups.json`，并增加忽略规则。本地现存文件保留。

已确认旧公开 main 中存在非占位凭据及非空用户状态。新提交删除不清除历史暴露，相关凭据仍需撤销或轮换；内置加密材料不能不考虑已有数据就直接删掉。没有尝试撤销用户凭据、强推或重写历史。旧正式构建对这些文件的要求可能 fail-closed，完整优化源码使用修正后的构建规则。

完整源码发布分支：`codex/standalone-cleanup-20261115`。最终提交 SHA、PR 和远端树核对结果见本轮交付记录。本地 `.git` 在本次工具权限中为只读，远端使用已授权 GitHub 连接器提交；本地索引保持原状。

发布使用明确白名单、私有路径拒绝表和高置信度凭据模式检查。没有盲目 `git add -A`，也没有把测试包、工具链、缓存和用户文件一起推送。模式检查不证明不存在所有类型的敏感信息，历史暴露另行保留为未完成事项。

## 回归证据

最终离线收集 6004 项：5961 项通过、37 项既有跳过、6 项明确环境排除，遗漏、重复和意外节点均为零。格式归一使一条按导入排列顺序判断的旧静态断言失效，已改为检查实际 AST 所有权；该模块最终 17 项结果替换同 17 项旧结果，不重复计数。发布策略的小幅收紧也按最终模块重跑结果核对。

| 证据 | 路径 |
| --- | --- |
| 精确收集覆盖与最终 Python JUnit | `build/source-cleanup-20261115/verification-summary.json`、`verified-regression.xml` |
| 公开源码及私有路径拒绝表 | `build/source-publication-20261115/publish-manifest.json`、`publish-denylist.json` |
| 前端清理测试与最终资源哈希 | `build/frontend-cleanup-vitest.txt`、`frontend-cleanup-assets.json` |
| 后端退休专项 | `build/backend-legacy-retirement.xml` |
| 实际容器入口布局验证 | `build/container-entry-layout.xml` |
| 固定源码办公流程 | `build/office-evaluation-final-20261115/fixture-source-v5/evaluation.json` |

固定 24 项办公任务各执行三次，重新读取实际文件核对内容、格式、来源、范围与故障恢复，源码 72/72 通过。它使用脚本模型验证工程流程，不能作为真实模型任务成功率。

## 本地测试包与能力边界

本轮新包目标为 `build/standalone-diagnostic-20261115-06/Koto_Original_LocalTest_2026-11-15.zip`。解压完整目录后运行 `Start_Koto.bat`，在设置中配置自己的模型。包旁 `delivery-summary.json` 和 `SHA256SUMS.txt` 记录实际构建、来源、隐私、资源、启动及 ZIP 核验结果；旧包和本地用户配置保留。

这是未签名本地诊断包。真实模型连接、浏览器视觉/交互、正式签名发行和任意复杂 OOXML/像素版式保真，仍是独立门槛，不能从离线测试或后端导入通过推断已完成。

Docker ignore 位置规则参考：[Docker 官方构建上下文文档](https://docs.docker.com/build/concepts/context/)。
