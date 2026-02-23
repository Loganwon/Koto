# Koto 项目结构说明

## 📁 目录结构（已优化）

### 核心目录 - 直接影响运行

```
Koto/
├── web/                    # 核心Web应用代码
│   ├── app.py             # Flask主应用
│   ├── tool_registry.py   # Agent工具注册系统
│   ├── excel_analyzer.py  # Excel数据分析器 🆕
│   ├── document_reader.py # 文档读取器
│   ├── file_processor.py  # 文件处理器
│   ├── adaptive_agent.py  # 自适应Agent
│   ├── static/            # 前端静态资源
│   │   ├── js/app.js     # 前端JavaScript (3800+ 行)
│   │   └── css/style.css  # 样式表
│   └── templates/         # HTML模板
│       └── index.html     # 主界面
│
├── config/                # 配置文件
│   ├── user_settings.json # 用户设置
│   └── gemini_config.env  # API配置
│
├── workspace/             # 工作区（用户文件）
│   ├── code/             # 生成的代码文件
│   ├── documents/        # 生成的文档
│   └── [用户上传的文件]
│
├── models/               # AI模型缓存
├── chats/                # 聊天历史（JSON格式）
├── logs/                 # 运行日志
└── assets/               # 静态资源（图标、图片等）
```

### 辅助目录 - 开发和调试

```
├── archive/              # 归档文件 🆕
│   ├── reports/         # 项目报告和文档 (37个文件)
│   ├── test_scripts/    # 测试脚本 (21个文件)
│   ├── tests/           # 单元测试 (8个文件)
│   ├── scripts/         # 辅助脚本 (1个文件)
│   ├── docs/            # 历史文档 (3个文件)
│   └── build_logs/      # 构建日志 (3个文件)
│
└── installer/            # 安装包构建文件和资源
```

## 🚀 启动文件（根目录）

| 文件 | 说明 | 推荐使用 |
|------|------|----------|
| `Koto.exe` | Windows桌面应用（打包版） | ⭐⭐⭐ 最简单 |
| `RunSource.bat` | 快速启动脚本 | ⭐⭐ 开发人员 |
| `run_desktop.bat` / `.ps1` | 桌面版启动脚本 | ⭐ 高级用户 |
| `koto_app.py` | 独立窗口应用（Python源码） | 开发调试 |
| `koto_desktop.py` | 桌面应用核心模块 | 库文件 |
| `launch_desktop.py` | 启动器模块 | 库文件 |

## 📚 文档文件

| 文件 | 说明 |
|------|------|
| `README.md` | 项目总览和功能介绍 |
| `QUICKSTART.md` | 快速开始指南 |
| `EXCEL_FEATURE.md` | Excel分析功能文档 🆕 |
| `PROJECT_STRUCTURE.md` | 本文档 - 项目结构说明 |
| `COMPLETION_REPORT.md` | Excel功能添加报告 |
| `requirements.txt` | Python依赖列表 |

## 🗂️ 归档说明

所有历史文档、测试脚本、构建日志都已整理到 `archive/` 目录：

- **archive/reports/** - 各种项目报告、总结、清单（37个文件）
- **archive/test_scripts/** - 测试脚本和输出文件（21个文件）
- **archive/tests/** - 单元测试和集成测试（8个文件）
- **archive/scripts/** - 辅助脚本（1个文件）
- **archive/docs/** - 历史文档（3个文件）
- **archive/build_logs/** - 构建日志和配置（3个文件）

这些文件仍然保留，但**不影响日常使用**。

## 🆕 最新更新 (2026-02-12)

### 新增功能
1. **表格和代码复制按钮** ✨
   - 代码块顶部有"复制"按钮
   - 表格顶部有"复制"按钮
   - 一键复制到剪贴板
   - 表格复制为制表符分隔格式（可直接粘贴到Excel）

2. **Excel数据分析器** (`web/excel_analyzer.py`)
   - 前N名客户分析
   - 分组聚合分析
   - 统计分析
   - 智能分析

3. **工具集成** 
   - 在 `tool_registry.py` 中注册 `analyze_excel_data` 工具
   - Agent可直接调用Excel分析功能

### 目录结构优化
- ✅ 合并 test 和 tests 文件夹
- ✅ 移动 tests 到 archive/
- ✅ 移动 scripts 到 archive/
- ✅ 移动 docs 到 archive/
- ✅ 精简根目录，只保留核心运行文件和启动器
- ✅ **根目录现在只有7个核心文件夹 + 2个辅助文件夹**

### 新的目录布局优势
- 🎯 **更清晰**：核心运行目录一目了然
- 🧹 **更整洁**：历史文件统一归档
- 🚀 **更易用**：新用户更容易理解项目结构
- 📦 **更专业**：符合生产项目标准

## 💡 使用建议

### 日常开发
- 核心代码在 `web/` 目录
- 配置文件在 `config/` 目录
- 用户文件在 `workspace/` 目录

### 查找历史资料
- 查看 `archive/` 目录
- 所有历史文档和报告都在里面

### 新功能测试
- Excel功能测试：直接上传Excel到Koto
- 工具测试：运行 `web/excel_analyzer.py`

## 📦 依赖管理

安装所有依赖：
```bash
pip install -r requirements.txt
```

主要依赖：
- Flask - Web框架
- google-genai - AI模型
- pandas - 数据分析 🆕
- openpyxl - Excel处理 🆕
- PySide6 - 桌面GUI

---

**清理完成日期**: 2026-02-12
**项目状态**: ✅ 生产就绪
