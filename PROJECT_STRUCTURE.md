# Koto 项目结构说明

Koto 是一个桌面端 AI 文件助手。当前产品形态已经合并为单一工作台：文件展示、AI 对话、历史会话、Skills、设置和白盒任务流程都从统一前端 `/` 进入。

## 核心目录

```text
Koto/
├── app/                 # Agent、路由、LLM、技能和文件任务运行时
├── web/                 # Flask 应用、模板、静态前端和工作台 BFF
├── src/                 # 桌面启动壳，src/koto_app.py 是桌面入口
├── config/              # 用户设置、模型和技能配置
├── workspace/           # 用户工作区文件
├── chats/               # AI 对话历史
├── logs/                # 启动和运行日志
├── tests/               # 单元、集成、E2E 和评测测试
└── scripts/             # 构建、迁移和测试辅助脚本
```

## 启动文件

| 文件 | 说明 | 推荐场景 |
|------|------|----------|
| `Koto_Start.vbs` | 无控制台启动统一桌面入口 | 日常使用 |
| `Koto_Start.bat` | 调用 PowerShell 启动器并显示日志 | 调试启动 |
| `Koto_Start.ps1` | 主启动器，负责端口、锁文件、重试和进程清理 | 高级调试 |
| `Stop_Koto.bat` | 停止 Koto 进程 | 退出/重启前 |

启动链路：

```text
Koto_Start.vbs / Koto_Start.bat
  -> Koto_Start.ps1
  -> src/koto_app.py
  -> web.app:app
  -> /
```

`/workspace-assistant` 只保留为兼容重定向，不再是独立产品入口。

## 主要运行模块

| 路径 | 说明 |
|------|------|
| `app/core/agent/` | 后台 Agent、文件任务、ReAct 执行、审批和并行子任务 |
| `app/core/routing/` | SmartDispatcher 与任务分类 |
| `app/core/llm/` | Gemini、DeepSeek、本地模型和容错链 |
| `app/core/skills/` | Skills 注册与执行 |
| `web/blueprints/workspace_assistant.py` | 文件工作台 BFF 和文件 API |
| `web/templates/index.html` | 统一前端页面 |
| `web/static/js/workspace-assistant.js` | 文件工作台运行时和兼容桥接 |
| `web/src/` | TypeScript 前端模块源码 |

## 旧命名保留清单

有些仍带 `workspace_assistant` 或 `workspace-assistant` 名字的文件不是独立旧入口，而是当前迁移期必须保留的运行时合同或测试夹具。保留原因、迁移条件和守护测试见 `docs/WORKSPACE_RETAINED_LEGACY.md`。

## 测试建议

日常代码修改后优先运行：

```bash
pytest tests/unit/ tests/integration/ -v --tb=short
```

前端构建后运行：

```bash
cd web
npm run build
```
