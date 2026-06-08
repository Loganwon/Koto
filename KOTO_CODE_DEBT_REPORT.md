# Koto 代码债务分析报告

> 生成日期：2026-06-08
> 范围：全栈（Python 后端 + JavaScript/CSS 前端）

---

## 2026-06-08 清理进展与校正

- 已删除 `web/interactions_api.py` 和 `web/proxy_config.py`：静态引用复核后确认只在本报告中出现，运行代码已有 `web/app.py` 内部实现。
- 已删除 `.wa-proposal-edit-original` 相关 CSS 残留：复核 JS、CSS、测试后未发现 DOM 生成或测试引用。
- 已把 DOCX 批注旧桥接进一步收口：生产代码现在只允许 `file_task_doc_annotate_boundary.py` 直接接触 `file_task_doc_annotate_bridge.py`；runtime 的桥接事件适配已迁移到 `file_task_doc_annotate_runner.py`。
- 已从旧 bridge 中继续拆出 `file_task_doc_annotate_intent.py` 和 `file_task_doc_annotate_events.py`：路由意图判断、清理/直写排除规则、进度 payload、tool 结果转换不再混在执行流里。
- 已把财务 XLSX -> DOCX 多文件报告链路从 runtime 主体迁移到 `file_task_financial_report_runner.py`，并补充“销售台账”跟随上一轮财务报告任务的路由测试。
- 暂不删除 `data-review-action`：它仍由 `workspace-assistant.js` 生成，并被 e2e/unit 测试覆盖。
- 暂不删除 `/api/document/analyze-annotations`、`WA.extractTopics`、PPT legacy：这些项需要先迁移或调整测试与前端入口，不能按“零风险删除”处理。

---

## 目录

1. [死代码（可安全删除）](#1-死代码可安全删除)
2. [已弃用/被取代的代码](#2-已弃用被取代的代码)
3. [仅被测试引用的生产模块](#3-仅被测试引用的生产模块)
4. [并行实现/功能重叠](#4-并行实现功能重叠)
5. [配置与安全](#5-配置与安全)
6. [命名与维护性](#6-命名与维护性)
7. [体积优化](#7-体积优化)
8. [建议行动顺序](#8-建议行动顺序)

---

## 1. 死代码（可安全删除）

这些文件或代码块在生产中完全没有被引用，移除风险为零。

### 1.1 `web/interactions_api.py` — 零引用

- **文件**: `web/interactions_api.py`
- **问题**: 全项目范围内（包括测试）没有任何 import 语句引用这个文件。属于完全死文件。
- **建议**: 直接删除。

### 1.2 `web/proxy_config.py` — 零引用

- **文件**: `web/proxy_config.py`
- **问题**: 同上，没有任何 import。
- **建议**: 直接删除。

### 1.3 CSS 死类 — `.wa-proposal-edit-original`

- **文件**: `web/static/css/workspace.css`
- **行号**: 5631, 5640, 6074
- **问题**: 对应 HTML 已在之前修改中删除（修订编辑时不再展示原文），但 CSS 规则残留。这些类不再匹配任何 DOM 元素。
- **建议**: 删除这 3 条 CSS 规则。

### 1.4 `_handleToolCall()` 死 else 分支

- **文件**: `web/static/js/workspace-assistant.js`
- **行号**: 11955-11977
- **问题**: 函数入口处 `aiOutputMode` 被硬锁定为 `'inline'`（第 265 行），导致处理 `set_html`/`insert_text`/`insert_image` 的 `else` 分支永远不可达。约 20 行死代码。
- **建议**: 删除 else 分支，或保留为注释待将来恢复多模式输出时参考。

### 1.5 `WA.extractTopics` 退休存根

- **文件**: `web/static/js/workspace-assistant.js`
- **行号**: 30-32
- **问题**: 函数体只剩 `showToast("文件助手 AI 对话任务流已移除；请使用快捷功能键。")`，不再执行任何实际功能。
- **建议**: 删除函数及其所有调用点。

---

## 2. 已弃用/被取代的代码

这些代码虽然可能仍被调用，但已有明确的新实现取代。

### 2.1 `ppt_legacy` 蓝图

- **文件**: `web/blueprints/ppt_legacy.py` + `web/app_blueprints.py:52`
- **注册方式**:
  ```python
  ("web.blueprints.ppt_legacy", "ppt_legacy_bp", None, "PptLegacy"),
  ```
- **提供路由**: `/api/ppt/download`, `/api/ppt/generate`
- **问题**: 新版 `ppt_api_routes.py` 提供了更完善的 `/api/ppt` 路由集，`ppt_legacy` 的功能已被完全覆盖。两个蓝图注册在同一前缀下造成路由重复。
- **建议**:
  - 验证新版 `ppt_api_routes.py` 是否覆盖了旧版两个路由的功能
  - 确认无前端代码调用旧路由后，删除 `ppt_legacy.py` 及其蓝图注册

### 2.2 `/api/document/analyze-annotations` 路由

- **文件**: `web/blueprints/document.py:451-478`
- **问题**: docstring 明确标注 `已弃用，请使用 /api/document/batch-annotate-stream`
- **建议**: 删除该路由处理函数。

### 2.3 Legacy `data-review-action` 事件处理器

- **文件**: `web/static/js/workspace-assistant.js:3767-3796`
- **问题**: 代码注释标明 `legacy data-review-action buttons`。新的 `data-action` 机制已经提供了相同的处理逻辑。两套事件处理机制并行运行。
- **建议**: 确认所有按钮模板都已使用 `data-action` 后，删除 legacy handler。

### 2.4 `_legacyToRich` PPTX 数据格式转换

- **文件**: `web/static/js/workspace-assistant.js:9431-9446`
- **调用点**: 第 7371 行 `this.data = this._legacyToRich(richData)`
- **问题**: 将旧格式 PPTX 数据转换为当前 rich 格式。如果所有用户数据已在迁移过程中完成格式转换，此函数不再需要。
- **建议**: 审计是否还有旧格式数据存在，确认后移除。

---

## 3. 仅被测试引用的生产模块

这些文件位于生产代码目录（`web/`），但只在测试用例中被 import。建议先检查对应测试是否仍然需要，再决定处理方式。

| 文件 | 仅被引用位置 | 用途 |
|------|------------|------|
| `web/feedback_loop.py` | `test_web_modules_batch8.py` | 反馈循环逻辑 |
| `web/clipboard_manager.py` | `test_web_modules_batch8.py` | 剪贴板管理 |
| `web/ppt_quality.py` | `test_web_modules_batch7.py` | PPT 质量评估 |
| `web/ppt_pipeline.py` | `test_web_modules_batch7.py` | PPT 处理流水线 |
| `web/ppt_synthesizer.py` | 测试 + `ppt_pipeline.py`（本身为测试引用） | PPT 合成 |
| `web/workflow_manager.py` | `test_web_modules_batch7.py` | 工作流管理 |
| `web/quality_evaluator.py` | `test_web_modules_batch4.py` | 质量评估 |
| `web/search_engine.py` | `test_web_modules_batch5.py` | 搜索引擎 |
| `web/intelligent_document_analyzer.py` | `test_full_paper_processing.py`, `test_output_modes.py`, `test_intelligent_analyzer.py` | 智能文档分析 |
| `web/docx_translator_module.py` | 测试 + `scripts/test_docx_*.py` | DOCX 翻译 |

**行动建议**：
1. 检查每个测试的实际内容和重要性
2. 如果测试有价值 → 模块保留，但考虑将其与调用方一起移出 `web/` 目录
3. 如果测试无价值 → 删除模块 + 对应测试

---

## 4. 并行实现/功能重叠

### 4.1 三套 PPT 系统

| 系统 | 蓝图/注册 | 路由前缀 | 文件位置 |
|------|----------|---------|---------|
| **旧版 PPT** | `ppt_legacy_bp` | `/api/ppt/download`, `/api/ppt/generate` | `web/blueprints/ppt_legacy.py` |
| **新版 PPT API** | `ppt_api_bp` | `/api/ppt`（更多路由） | `web/ppt_api_routes.py` |
| **PPTX 编辑器** | `pptx_editor_bp` | `/api/pptx` | `web/blueprints/pptx_editor.py` |

**问题**：三套系统功能重叠，`ppt_legacy` 和 `ppt_api_routes` 共享 `/api/ppt` 前缀。

**建议**：合并为一个统一的 PPT 服务层，保持 `pptx_editor` 作为编辑器独立。

### 4.2 两个 Workspace 蓝图

| 系统 | 路由数 | 文件 |
|------|-------|------|
| `workspace_bp` | 4 个 | `web/blueprints/workspace.py` |
| `workspace_assistant_bp` | 大量 | `web/blueprints/workspace_assistant.py` |

**问题**：`workspace_bp` 功能薄弱（仅文件列表/服务），完全被功能更完善的 `workspace_assistant_bp` 覆盖。

**建议**：确认 `workspace_bp` 的路由是否仍被前端使用，确认后合并到 `workspace_assistant_bp`。

### 4.3 Review Rail 分散在 4 个 JS 文件

| 文件 | 职责 |
|------|------|
| `docx-review-state.js` | 状态管理 |
| `docx-review-geometry.js` | 布局测量/几何计算 |
| `docx-review-layout.js` | DOM 布局引擎（碰撞检测、定位、连线绘制） |
| `workspace-assistant.js` | UI 集成层（薄封装代理） |

**问题**：`workspace-assistant.js` 中大量 `_getDocxReviewLayout()` / `_getDocxReviewState()` 双重重定向。函数被薄封装代理，增加认知负荷。

**建议**：将代理函数改为直接引用，或通过解构赋值减少中间层。

---

## 5. 配置与安全

### 5.1 `dev_bp` 在生产环境注册

- **文件**: `web/app_blueprints.py:43`
- **问题**: 调试/开发路由在生产环境中可用。
- **建议**: 加条件注册，仅 `app.debug` 为 True 时注册。

### 5.2 使用已弃用 Google SDK

- **文件**: `web/knowledge_base.py:27`
- **代码**: `import google.generativeai as genai  # Fallback to deprecated SDK`
- **问题**: 依赖已标记为弃用的 SDK 版本。
- **建议**: 升级到最新 SDK 或确认是否需要这个 fallback 路径。

---

## 6. 命名与维护性

### 6.1 `_legacy_safe_sse` 命名误导

- **文件**: `web/app.py:1739`
- **问题**: 函数名含 `legacy` 但实际上在 27 个调用点活跃使用（主流任务流的核心 SSE 发送函数）。
- **建议**: 重命名为 `_safe_sse` 或 `_send_sse_event`。

### 6.2 `aiOutputMode` 状态冗余

- **文件**: `web/static/js/workspace-assistant.js:265, 12178`
- **问题**: 变量存在但 `aiOutputMode = 'inline'` 被硬编码覆盖。多模式输出能力已从 UI 中移除。
- **建议**: 移除状态变量，或添加注释说明保留以备将来扩展。

### 6.3 空 `__init__.py` 文件

- **文件**: `web/routes/__init__.py`, `web/blueprints/__init__.py`
- **问题**: 仅含空行或版权头，无实际作用。
- **建议**: 保留（Python 需要它们使目录成为包）但清理多余内容。

---

## 7. 体积优化

### 7.1 `workspace.css` 膨胀

- **文件**: `web/static/css/workspace.css`
- **大小**: ~305KB / 9300 行
- **问题**: 大量 `.wa-*`、`.koto-*`、`.wa-review-*` CSS 类可能已不再被使用。CSS 覆盖率审计缺失。
- **建议**: 使用 Puppeteer/Playwright 运行 CSS 覆盖率分析，移除未使用的规则。

### 7.2 `workspace-assistant.js` 持续膨胀

- **文件**: `web/static/js/workspace-assistant.js`
- **大小**: ~738KB / 16600 行
- **问题**: 单体文件，包含 PPT 编辑器、DOCX 审阅、文件管理等多模块功能。拆分为独立模块可以提高可维护性。
- **建议**: 按功能域拆分为独立文件（部分工作已在做，如 `docx-review-*.js`）。

---

## 8. 建议行动顺序

```
优先级    行动                       风险     预估工作量
──────────────────────────────────────────────────────────
P0    删除 web/interactions_api.py   无       < 1 分钟
P0    删除 web/proxy_config.py       无       < 1 分钟
P0    删除 CSS 死类                  无       5 分钟
P1    删除 ppt_legacy 蓝图           低       2 小时（含验证）
P1    删除已弃用 analyze-annotations  低       1 小时
P1    删除死 else 分支               低       15 分钟
P1    删除 WA.extractTopics 存根     低       30 分钟
P2    审计 #7 测试引用模块           中       4 小时
P2    确认 data-review-action 去留   中       2 小时
P3    dev_bp 条件注册                低       30 分钟
P3    重命名 _legacy_safe_sse        低       15 分钟
P4    PPT 系统合并                   高       一周
P4    Workspace 蓝图合并             中       2 天
P4    CSS/JS 体积优化                中       2 天
```

> **说明**：
> - P0：可以立即执行，零风险
> - P1：需要简单验证，风险很低
> - P2：需要功能确认，可能有依赖影响
> - P3：低风险但收益也低，可选
> - P4：架构级重构，需要充分测试
