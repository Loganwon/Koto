# Koto 文件编辑与搜索功能

## ✅ 已实现

### 1. 文件编辑 (FILE_EDIT)

类似 GitHub Copilot 的本地文件编辑能力，支持：

#### 基础操作
- **读取文件**: 支持多种编码（UTF-8, GBK, UTF-16）
- **写入文件**: 自动备份（.bak）
- **替换文本**: 支持正则表达式
- **插入行**: 在指定行前/后插入内容
- **删除行**: 删除单行或行范围
- **追加内容**: 在文件末尾添加

#### 智能编辑
自动理解自然语言指令：
```
修改 config.txt 把 'debug=False' 改成 'debug=True'
把 main.py 的第 15 行改成 'x = 10'
在 test.py 第 20 行之后插入 'import os'
删除 data.txt 第 5-10 行
```

#### 安全保护
- 路径安全检查（防止越界访问）
- 自动备份（修改前创建 .bak）
- 备份目录：`workspace/_backups/`

### 2. 文件搜索 (FILE_SEARCH)

快速定位 Koto 处理过的文件：

#### 全文搜索
基于 SQLite FTS5 全文索引：
```
找包含 'config' 的文件
搜索 'python 代码'
哪个文件里有 'API KEY'
```

#### 内容相似度搜索
根据内容片段查找相似文件：
```
哪个文件包含这段代码: import os, sys
之前生成过关于数据分析的文档
那个配置文件在哪
```

#### 自动索引
- 支持扩展名: `.txt`, `.md`, `.py`, `.js`, `.json`, `.xml`, `.html`, `.css`, `.yaml`, 等
- 索引时机: 文件生成、手动触发
- 索引位置: `workspace/_index/file_index.db`

## 🎯 使用方法

### 对话式编辑

直接在 Koto 对话框输入：

```
修改 workspace/test.txt 把所有的 TODO 改成 DONE

编辑 scripts/run.py 删除第 10-15 行

把 config.json 的 "port": 8080 改成 "port": 9000
```

### 对话式搜索

```
找文件：包含 'flask' 的文件

搜索关于机器学习的代码

哪个文件里写了数据库连接配置
```

## 📡 当前 API

旧的 `/api/file-editor/*` 与 `/api/file-search/*` 路由已经退役。不要重新接入这些入口；
工作区文件读写、Agent 文件任务和知识库检索分别使用下面的唯一生产入口。

### 打开工作区文件

```bash
POST /api/v1/workspace/open_file_by_path
{
  "path": "test.txt"
}
```

### 执行文件 Agent 任务

```bash
POST /api/editor/ai/task-stream
{
  "task": "把 test.txt 中的 TODO 改成 DONE",
  "file_path": "test.txt"
}
```

该接口返回 SSE 任务事件，并通过统一的 `FileTaskRuntime`、任务账本和文件工具完成修改与验证。

### 导出文本修补结果

```bash
POST /api/v1/workspace/patch_file
{
  "path": "test.txt",
  "proposals": [
    {"original_text": "TODO", "proposed_text": "DONE"}
  ]
}
```

该接口支持 `.docx`、`.txt`、`.md`，返回修改后的下载文件，不直接覆盖磁盘原件。

### 知识库搜索

```bash
POST /api/rag/search
{
  "query": "python",
  "k": 20,
  "score_threshold": 0.3
}
```

### 手动索引目录

```bash
POST /api/rag/index-directory
{
  "dir_path": "workspace/documents",
  "extensions": [".pdf", ".docx", ".txt"]
}
```

## 🔧 技术细节

### 生产所有者

- 文件打开/保存：`web/blueprints/workspace_assistant.py`
- Agent 文件任务：`app/core/agent/file_task_runtime.py`
- Agent 文件工具：`app/core/agent/task_tools.py`
- 知识库检索：`web/blueprints/rag_api.py`

### Agent 任务入口

工作区只对明确的文件上下文和白名单系统动作做确定性快路径。其他文件请求统一进入
`FileTaskRuntime`，由模型根据当前文件、目标与可用工具决定读取、检索或修改步骤，不再由
关键词分类器预判 `FILE_EDIT` / `FILE_SEARCH`。

## 📊 验证入口

使用 `tests/integration/test_e2e_user_scenarios.py` 验证文件创建、打开、保存和重开，
使用 `tests/unit/test_file_task_runtime.py` 验证 Agent 文件任务主链。不要在文档中记录会随
本地数据变化的固定文件数量或成功率。

## 🚀 示例场景

### 场景 1: 批量修改配置
```
修改 config/settings.json 把所有的 "localhost" 改成 "127.0.0.1"
```

### 场景 2: 代码重构
```
编辑 main.py 把第 50-60 行删除，然后在第 50 行插入新的实现
```

### 场景 3: 查找历史文件
```
找一下上次生成的数据分析报告
哪个 Python 文件里用了 pandas
```

### 场景 4: 配置修改
```
把所有配置文件的 debug 都改成 False
修改 .env 文件，把 API_KEY 改成新的
```

## 🔐 安全机制

1. **路径限制**: 只能访问 workspace、用户目录、C:/Users、D:/ 下的文件
2. **自动备份**: 每次修改前创建 .bak 备份
3. **编码检测**: 自动尝试 UTF-8, GBK, UTF-16
4. **错误提示**: 清晰的错误消息和使用建议

## 💡 最佳实践

### 文件编辑
1. **明确路径**: 使用相对或绝对路径
2. **小步修改**: 一次改一个内容，便于回滚
3. **查看备份**: 修改出错可从 `_backups/` 恢复

### 文件搜索
1. **先索引**: 新文件需要先索引才能搜索
2. **精确关键词**: 使用具体的技术术语
3. **内容片段**: 提供足够长的内容样本（2-3行）

## 📈 性能指标

- **编辑速度**: < 100ms （小文件）
- **搜索速度**: < 50ms （FTS5 全文索引）
- **索引速度**: ~20 文件/秒
- **支持文件**: 100KB 限制（可调整）

## 🎉 总结

Koto 现在具备了类似 GitHub Copilot 的文件编辑能力，加上强大的文件搜索功能，可以：

✅ **智能修改本地文件** - 自然语言指令，自动理解
✅ **快速定位文件** - 根据内容、关键词快速找到
✅ **安全可靠** - 自动备份、路径限制
✅ **高效索引** - SQLite FTS5 全文搜索

**立即体验**: `python koto_app.py` 启动 Koto，输入 "修改 xxx 文件..." 开始使用！
