# Koto (言) — 项目全量总结

> 生成时间：2026-03-27 | 版本：**1.6.6**

---

## 1. 项目概述

Koto（言）是一个基于**多模型 AI** 的桌面 / 云端智能助手，支持多轮对话、长期记忆、知识库、文件分析、语音交互和工作流自动化。它可运行为：

- **本地桌面应用**（pywebview 独立窗口）
- **本地浏览器模式**（`python server.py` → `http://localhost:5000`）
- **云端 SaaS**（Docker，部署到 Railway / Render / Fly.io 等平台）

许可证：专有（`LicenseRef-Koto-Proprietary`），GitHub CI/CD 全套自动化。

---

## 2. 目录结构

```
Koto/
├── app/                    # 核心业务逻辑（Python 包）
│   ├── api/                # API 路由蓝图（agent, skill, task, job, shadow…）
│   └── core/               # 核心领域模块
│       ├── agent/          # AI 代理（Unified, LangGraph, Background, DeepResearch…）
│       ├── analytics/      # 行为分析
│       ├── config/         # 配置管理
│       ├── context/        # 上下文注入
│       ├── db/             # 数据库工具 & 迁移
│       ├── file/           # 文件注册表
│       ├── goal/           # 目标规划
│       ├── hooks/          # 生命周期钩子
│       ├── jobs/           # 后台作业
│       ├── learning/       # 用户行为学习
│       ├── llm/            # LLM 提供商（Gemini/OpenAI/Anthropic/Ollama）
│       ├── memory/         # 记忆系统
│       ├── monitoring/     # 系统监控
│       ├── ops/            # 运维接口
│       ├── remediation/    # 故障自愈
│       ├── routing/        # 智能路由 & 任务分解
│       ├── security/       # 安全 & PII 过滤
│       ├── services/       # 后台服务（MorningBrief…）
│       ├── skills/         # Skill 执行引擎
│       ├── tasks/          # 任务调度 & TaskLedger
│       ├── tools/          # 工具注册表
│       └── workflow/       # 工作流运行时
├── web/                    # Flask 应用层
│   ├── app.py              # Flask 应用入口（~500 行，已拆分蓝图）
│   ├── auth.py             # JWT 认证
│   ├── blueprints/         # Flask 蓝图（16 个）
│   ├── routes/             # 轻量路由（health…）
│   ├── templates/          # Jinja2 HTML 模板（15 个页面）
│   ├── static/             # 静态资源
│   │   ├── css/            # 样式表
│   │   ├── js/             # 前端脚本
│   │   └── univer-dist/    # 文件助手编译产物（Univer canvas）
│   └── univer-editor/      # 文件助手前端源码（esbuild 构建）
├── config/                 # 配置文件（skills, hooks, workflows, 环境变量…）
├── tests/                  # 测试套件（161 个文件，4000+ 用例）
├── src/                    # 安装向导 & 打包工具
├── scripts/                # 开发辅助脚本
├── docs/                   # 市场官网（静态 HTML）
├── launcher/               # 桌面启动器
├── chats/                  # 会话持久化目录
├── workspace/              # 用户工作区文件
└── logs/                   # 运行日志
```

---

## 3. 技术栈

### 后端
| 层次 | 技术 |
|------|------|
| Web 框架 | **Flask** + Flask-CORS + Flask-Sock（WebSocket）|
| WSGI | **Gunicorn**（生产）/ Flask dev server（本地）|
| 异步 | `asyncio` + `threading`（混合模型）|
| 数据库 | **SQLite**（TaskLedger, KnowledgeGraph, 行为库）|
| 缓存 | 内存 LRU + TTL（各模块自实现）|
| 消息总线 | 进程内 `ProgressBus`（SSE 推送）|
| 认证 | JWT（`PyJWT`），可选关闭（本地模式）|
| API 文档 | **Swagger / OpenAPI**（flasgger，`/apidocs`）|
| 打包 | **PyInstaller**（`koto.spec`），含 Cython 扩展选项 |
| 容器 | **Docker** + `docker-compose.yml` |

### 前端
| 层次 | 技术 |
|------|------|
| 模板引擎 | **Jinja2**（服务端渲染）|
| 样式 | 纯 CSS（CSS 变量主题系统，亮色 / 暗色）|
| 脚本 | **原生 JavaScript**（无前端框架）|
| 实时通信 | **Server-Sent Events (SSE)**（流式对话）、**Socket.IO**（文件协作）|
| 文件编辑器 | **Univer 0.5.5**（Canvas 渲染，文档 / 表格）|
| 构建工具 | **esbuild** 独立二进制（不依赖 Node.js 环境）|
| 富文本 | marked.js（Markdown 渲染）、highlight.js（代码高亮）|
| 图表 | Mermaid（流程图）、Canvas（数据图表）|

### AI 提供商
| 提供商 | 模型 | 备注 |
|--------|------|------|
| **Google Gemini** | gemini-2.5-flash, gemini-2.5-pro（默认主力）| 每用户独立 API Key，指数退避重试 |
| **OpenAI** | GPT 系列 | 通过 `openai_provider.py` |
| **Anthropic** | Claude 系列 | 通过 `anthropic_provider.py` |
| **Ollama** | 本地模型 | 通过 `ollama_provider.py`，支持离线运行 |

统一通过 **`provider_factory.py`** 路由，支持 **`model_fallback.py`** 自动熔断 / 降级。

---

## 4. 核心模块架构

### 4.1 依赖注入容器 — `AppContext`

`app/core/app_context.py` — 全局单例 `ctx`，替代了 48 个散落模块级全局变量。

- 线程安全双重检查锁，延迟初始化
- `ctx.override("name", mock)` / `ctx.reset()` 供测试使用
- 注册 12 个核心服务：`config_manager`, `settings_manager`, `memory_manager`, `knowledge_base`, `file_registry`, `task_ledger`, `system_monitor`, `notification_manager`, `checkpointer`, `model_manager`, `agent`, `token_tracker`

### 4.2 智能路由 — `SmartDispatcher`

`app/core/routing/` 负责将用户输入分类并路由：

```
用户输入
  └─ TaskDecomposer（任务分解）
  └─ SmartDispatcher.analyze()
       ├─ task_type: CHAT / WEB_SEARCH / FILE_ANALYSIS / DOC_ANNOTATE / PPT_GEN / ...
       ├─ route_method: local / gemini / agent / multiagent
       └─ context_info: { skill_prompt, multiagent_preset, ... }
```

支持 **MultiAgent 编排**（`parallel_roles`、`preset_analysis_pipeline`）。

### 4.3 AI 代理系统

| 模块 | 说明 |
|------|------|
| `UnifiedAgent` | ReAct 循环代理，最多 15 步，含 PII 过滤 & 输出验证 |
| `LangGraphAgent` | StateGraph 版代理（优先使用）|
| `BackgroundAgent` | 异步后台任务执行，含作业队列 |
| `DeepResearch` | 多步研究 pipeline（搜索 → 综合）|
| `MultiAgentOrchestrator` | 并行多角色协作 |
| `TreeOfThought` | 思维树推理 |
| `MCPAdapter` | Model Context Protocol 集成 |
| `ProactiveAgent` | 主动触发，冷却状态跨重启持久化 |
| `ReasoningBudget` | Token 预算管理 |

### 4.4 记忆系统

三层架构：

```
对话历史（JSON文件，按会话）
  ↓
SmartMemoryFilter（memory_router.py）
  ├─ 检索 8 候选
  ├─ 评分（语义 × 时效 × 分类）
  ├─ 去重（字符 bigram Jaccard > 0.6）
  └─ TopK(4) 注入 prompt
  ↓
ContextWindowManager（context_window_manager.py）
  └─ 智能页入，最多 3 条相关记忆
```

持久化：`config/memory.json` + RAG 向量索引（`config/memory_rag_index/`）。

### 4.5 Skill（技能）系统

- **76 个内置 Skill**（`config/skills/*.json`），涵盖：写作、分析、翻译、财务、法律、PPT、代码、卜卦、提示优化等
- **SkillManager**：加载 / 启用 / 禁用 / 编辑 Skill，支持用户自定义
- **SkillAutoMatcher**：根据用户输入自动匹配并激活 Skill
- **SkillTriggerBinding**：意图匹配，将 Skill 注入特定任务类型的 prompt
- **SkillAffinityTracker**：用户偏好学习（指数衰减，30 天半衰期），个性化推荐
- **SkillSuggester**：结合对话历史的 5 层打分推荐（含亲和度 +1.5 加权）
- **SkillPipeline**：技能执行链（验证 → 路由 → 回退）
- **SkillPermissions**：访问控制（授权 / 撤销 / 检查）

---

## 5. 主要功能模块

### 5.1 对话与会话

- 多会话管理（`session_manager`），JSON 持久化到 `chats/`
- 流式输出（SSE Server-Sent Events）
- 中断控制（`InterruptManager`）
- 语音输入 / 输出（`voice_engine.py`，支持本地 Vosk STT + TTS）
- 迷你模式（`/mini`，轻量桌面悬浮窗）
- 移动端适配（`/mobile`，响应式布局）

### 5.2 文件处理

| 能力 | 模块 |
|------|------|
| 解析（DOCX/PDF/PPTX/XLSX/TXT…）| `file_parser.py` |
| AI 分析 | `file_analyzer.py`, `intelligent_document_analyzer.py` |
| 文档注释 | `document_annotator.py` |
| 文档对比 | `document_comparator.py`（N 路 diff）|
| 文档生成 | `document_generator.py` |
| 文档翻译 | `docx_translator_module.py` |
| 文档反馈迭代 | `document_feedback.py` |
| 文档直接编辑 | `document_direct_edit.py` + `track_changes_editor.py` |
| 文件组织 / 清理 | `file_organizer.py`, `organize_cleanup.py` |
| 批量操作 | `batch_file_ops.py`, `batch_processor.py` |
| 文件网络可视化 | `processed_file_network.py` + `/file-network` 页面 |
| 文件监控 | `file_watcher.py`, `auto_catalog_scheduler.py` |

### 5.3 文件助手（Univer 编辑器）

基于 **Univer 0.5.5** (Canvas) 构建的在线文档 / 表格编辑器：

- 入口：侧边栏"文件助手"→ 全屏覆盖层（iframe `position:fixed`）
- 架构：4 个解耦模块 — `DocController.js`, `AIPanel.js`, `SocketBridge.js`, `socket_handler.py`
- 后端通信：Flask-SocketIO，命名空间 `/doc`
- AI 面板：实时选区同步 → AI 辅助写作 / 解释 / 改写

### 5.4 知识库

- `knowledge_base.py`：文件向量化（sentence-transformers），RAG 检索
- `knowledge_graph.py`：基于 SQLite 的知识图谱，含可视化页面（D3.js）
- `concept_extractor.py`：自动概念抽取

### 5.5 PPT 生成

完整 PPT 生产流水线：

```
用户需求 → DocPlanner → PPTMaster（结构规划）
  → PPTPipeline（内容生成）→ PPTSynthesizer（排版合成）
  → PPTQuality（质量检查）→ 下载 / 在线编辑（/edit-ppt）
```

支持自定义主题（`ppt_themes.py`），会话管理（`ppt_session_manager.py`）。

### 5.6 工作流自动化

- `workflow_manager.py` / `workflow_runtime.py`：可视化 DAG 工作流（`/static/workflow_dag.html`）
- `job_runner.py`：后台任务执行器
- `macro_routes.py`：宏录制 / 回放
- `browser_automation.py`：浏览器自动化（Playwright）
- `auto_execution.py`：自动执行决策

### 5.7 系统监控

- `monitoring/`：系统指标采集（CPU/RAM/Disk）
- `/monitoring-dashboard`：实时监控仪表盘（静态 HTML + WebSocket 推送）
- `notification_manager.py`：桌面通知（Windows Toast）
- `behavior_monitor.py`：用户行为记录 & 学习

### 5.8 其他功能

| 功能 | 模块 |
|------|------|
| 网页搜索（Grounding）| `web_searcher.py`（Gemini Grounding API）|
| 邮件管理 | `email_manager.py` |
| 日历 / 提醒 | `calendar_manager.py`, `reminder_manager.py` |
| 剪贴板 OCR | `clipboard_ocr_assistant.py` |
| 图片生成 | `image_generator.py` |
| Telegram Bot | `telegram_bot.py`（621 行，含用户白名单）|
| 笔记管理 | `note_manager.py` |
| 代码生成 | `code_generator.py` |
| 本地脚本执行 | `local_executor.py` |
| 晨报 | `app/core/services/morning_brief.py` |
| ShadowWatcher | 用户行为隐式观察，批量 I/O（每 5 次交换写一次）|
| 音频概述 | `audio_overview.py` |

---

## 6. Flask 蓝图架构

`web/app.py` 已从 ~20800 行精简至 **~500 行**，路由全部迁移至 16 个蓝图：

| 蓝图 | 文件 | 主要功能 |
|------|------|----------|
| `pages_bp` | `blueprints/pages.py` | 页面渲染（/, /mini, /editor…）|
| `chat_bp` | `blueprints/chat.py` | 对话中断 / 迷你模式 API |
| `sessions_bp` | `blueprints/sessions.py` | 会话 CRUD |
| `analytics_bp` | `blueprints/analytics.py` | 统计 & 反馈 |
| `proactive_bp` | `blueprints/proactive.py` | 主动触发 |
| `execution_bp` | `blueprints/execution.py` | 工作流执行 |
| `knowledge_bp` | `blueprints/knowledge.py` | 知识库管理 |
| `file_editor_bp` | `blueprints/file_editor.py` | 文件编辑 |
| `file_organize_bp` | `blueprints/file_organize.py` | 文件整理 |
| `document_bp` | `blueprints/document.py` | 文档操作 |
| `voice_bp` | `blueprints/voice.py` | 语音 API |
| `workspace_bp` | `blueprints/workspace.py` | 工作区 |
| `workspace_assistant_bp` | `blueprints/workspace_assistant.py` | Workspace 助手 |
| `settings_bp` | `blueprints/settings.py` | 系统设置 |
| `misc_api_bp` | `blueprints/misc_api.py` | 杂项 API |
| `dev_bp` | `blueprints/dev.py` | 开发工具 |
| `editor_docs_bp` | `blueprints/editor_docs.py` | 编辑器文档 |

此外，`app/api/` 下还有 11 个独立蓝图（agent, skill, task, job, shadow, macro, ops, file_hub, distill, skill_marketplace, telegram_bot）。

---

## 7. UI / 前端

### 7.1 主界面（`web/templates/index.html` + `web/static/css/style.css`）

三栏布局（左侧边栏 + 中央内容区 + 隐藏面板）：

```
┌─────────────────────────────────────────────────────┐
│  侧边栏（固定宽度）         中央内容区               │
│  ┌───────────┐   ┌─────────────────────────────┐   │
│  │ Koto 言   │   │  Welcome / Chat 界面         │   │
│  │ ─────────  │   │  ─────────────────────────  │   │
│  │ 搜索会话  │   │  消息气泡（用户 / AI）        │   │
│  │ 会话列表  │   │  Markdown 渲染 + 代码高亮    │   │
│  │ ─────────  │   │  流程图 (Mermaid)            │   │
│  │ 文件助手  │   │  ─────────────────────────  │   │
│  │ Workspace │   │  聊天输入框                  │   │
│  │ 技能市场  │   │  Active Skills Pill Bar       │   │
│  │ 设置      │   │  文件拖拽上传                 │   │
│  │ ─────────  │   └─────────────────────────────┘   │
│  │ 系统状态  │                                       │
│  └───────────┘                                       │
└─────────────────────────────────────────────────────┘
```

**主题系统**：CSS 变量（`--bg-primary`, `--accent`, `--text-primary`…），支持亮色 / 暗色动态切换，无刷新。

**视图切换**：
- `#chatView`（默认）→ 对话界面
- `#editorView`（全屏覆盖，`position:fixed`）→ 文件助手（Univer iframe）

### 7.2 Skill UI

- 侧边栏 Skill 面板：分类 Tab（写作 / 分析 / 工具 / 全部）→ Skill 卡片列表
- `skill-card.active`：激活状态，蓝色边框 + 半透明背景
- **Active Skills Pill Bar**：输入框上方实时显示已激活 Skill（带关闭按钮）
- **Skill Editor Modal**：暗色面板，可编辑名称 / Prompt / 触发词 / 输出格式
- **Bindings & Triggers UI**：关键词绑定管理，带类型徽章

### 7.3 独立页面

| 页面 | 路由 | 说明 |
|------|------|------|
| 技能市场 | `/skill-marketplace` | GitHub Marketplace 风格，含搜索 / 安装 / 创作工坊 / 统计 / 社区 Tab |
| Skill 社区 | `/skill-community` | 精选社区 Skill，一键安装 |
| 文件网络 | `/file-network` | 关系图谱可视化（Canvas）|
| 知识图谱 | `/knowledge-graph` | D3.js 力导向图 |
| 文件助手 | `/editor` | Univer 文档编辑器 |
| 监控仪表盘 | `/monitoring-dashboard` | 实时系统指标 |
| PPT 编辑 | `/edit-ppt/<id>` | PPT 生成后在线编辑 |
| 迷你模式 | `/mini` | 轻量悬浮窗 |
| 移动端 | `/mobile` / `/m` | 手机响应式界面 |
| NotebookLM 风格 | `/notebook` | 音频概述 UI |
| Workspace 助手 | `/workspace_assistant.html` | 工作区文件管理助手 |
| 落地页 | `/`（云部署未认证）| 营销落地页（中英双语）|

### 7.4 前端脚本

| 文件 | 说明 |
|------|------|
| `app.js` | 主应用逻辑（会话管理、聊天发送、SSE 接收、视图切换）|
| `app-framework.js` | 组件框架基础类 |
| `auth.js` | 前端认证流程 |
| `skill-ui.js` | Skill 面板交互 |
| `skill-ui-extensions.js` | Skill 编辑器 / Binding UI 扩展 |
| `tarot-picker.js` | 占卜 Skill 专用选牌 UI |
| `skill_marketplace.js` | 技能市场 SPA 逻辑 |
| `skill_community.js` | 社区页逻辑 |
| `workspace-assistant.js` | 工作区助手 |

---

## 8. 配置 & 持久化

| 文件 / 目录 | 内容 |
|-------------|------|
| `config/gemini_config.env` | AI API Key（Gemini 主力）|
| `config/user_settings.json` | 用户偏好（主题 / 语音 / 模型 / Skill 状态…）|
| `config/memory.json` | 长期记忆条目 |
| `config/skills/*.json` | 76 个 Skill 定义 |
| `config/skill_affinity.json` | 用户 Skill 偏好学习数据 |
| `config/triggers.json` | 全局触发规则 |
| `config/skill_bindings.json` | Skill 关键词绑定 |
| `config/user_profile.json` | 用户画像（PersonalityMatrix 基础）|
| `config/personality_matrix.json` | 个性化矩阵（4 层上下文注入）|
| `config/shadow_observations.json` | ShadowWatcher 行为观察 |
| `config/knowledge_graph.db` | 知识图谱 SQLite |
| `config/koto_checkpoints.sqlite` | Agent 断点续传 |
| `chats/*.json` | 所有对话会话记录 |
| `workspace/` | 用户上传 / 生成文件 |

---

## 9. 安全

- **认证**：JWT（`PyJWT`），`KOTO_AUTH_ENABLED` 环境变量控制，本地模式默认关闭
- **授权**：`@require_auth` 装饰器，云模式强制
- **PII 过滤**：`UnifiedAgent` 内置 PII 掩码 → 输出时还原
- **输出验证**：`OutputValidator` 清洗 Agent 输出（防 XSS/注入）
- **文件名净化**：`_secure_filename()` 保留 Unicode CJK 同时过滤危险字符
- **路径遍历防护**：`file_converter` 输出目录白名单
- **XSS 防护**：`showNotification` / `md_to_html` 使用 `escapeHtml`
- **速率限制**：滑动窗口 `_rate_buckets`，每用户每日请求上限（可配置）
- **Bandit** 静态扫描 + `pip-audit` CVE 扫描（CI Pipeline）
- **系统 API Key**：XOR 混淆（种子 `0xA7`），仅激活码验证后解密注入

---

## 10. 测试

| 类别 | 数量 | 说明 |
|------|------|------|
| 测试文件总数 | **161 个** | 覆盖 unit / integration / e2e / load / installer |
| 测试用例 | **4000+** | 含属性测试（hypothesis）|
| 单元测试 | `tests/unit/` | 各模块独立测试 |
| 集成测试 | `tests/integration/` | 蓝图路由 + 系统集成 |
| E2E 测试 | `tests/e2e/` | Playwright 浏览器自动化（63 用例）|
| 压力测试 | `tests/load/` | 并发 + 大负载场景 |
| 安装程序测试 | `tests/installer/` | Windows MSI 全流程 |
| CI 持续集成 | GitHub Actions | black + isort + bandit + pytest + Docker build |

**已知问题**：pytest 全量运行时有 vosk 本地库 `__del__` segfault（预存在 bug，不影响功能），建议使用定向测试运行。

---

## 11. 部署

### 本地运行
```bash
python -m venv .venv
.venv\Scripts\pip install -r config/requirements.txt
python server.py          # 浏览器模式
python koto_app.py        # 桌面应用模式 (pywebview)
```

### Docker
```bash
cp config/deploy/.env.example .env  # 填写 API Key
docker compose up -d
```

### 打包（Windows 可执行文件）
```powershell
.\Build_Release.ps1  # PyInstaller → dist/Koto.exe
```
包含：所有 `web.blueprints.*` + `web.routes.*` 隐式导入，`koto.spec` 管理。

### 云部署（Railway / Render / Fly.io）
Fork → 连接 GitHub → 选择 `config/deploy/Dockerfile` → 设置环境变量。

---

## 12. 当前版本的关键修复（v1.6.x）

| 版本 | 关键修复 |
|------|----------|
| v1.6.6 | 当前版本 |
| v1.6.5 | 系统 API Key 安全修复（从 Git 移除，XOR 混淆），激活码验证流程修复 |
| v1.6.4 | AppContext DI 容器；智能记忆过滤（~50% Token 节省）；Skill Affinity 偏好学习 |
| v1.6.1 | Skill 社区页；落地页改版；构建管道修复（蓝图 hiddenimports）|
| v1.6.0 | Skill 市场全功能；chat.py 蓝图拆分（web/app.py 6600→500 行）；6 个新 Skill |
| v1.5.1 | 每用户 Gemini API Key；速率限制重构；ShadowWatcher 数据不丢失修复 |
| v1.5.0 | UnifiedAgent / LangGraph / BackgroundAgent / DeepResearch；LLM Provider 工厂；Skill 权限；LangGraph |
| v1.4.0 | Telegram Bot；Memory API；Document Comparator；ShadowWatcher |
| v1.3.0 | Playwright E2E；Blueprint 拆分（206 路由）；Skill Pipeline；PersonalityMatrix；Swagger |

---

## 13. 开发工具

```bash
make dev      # 启动开发服务器
make test     # pytest + 覆盖率
make lint     # flake8 + bandit
make format   # isort + black
make build    # PyInstaller 打包
make audit    # pip-audit CVE 扫描
```

Pre-commit hooks：black, isort, flake8, bandit

---

*本文档由 GitHub Copilot 根据代码库自动汇总生成，版本截止 2026-03-27。*
