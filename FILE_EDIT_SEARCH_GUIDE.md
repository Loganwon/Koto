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

## 📡 API 调用

### 文件编辑 API

#### 读取文件
```bash
POST /api/file-editor/read
{
  "file_path": "workspace/test.txt"
}
```

#### 替换文本
```bash
POST /api/file-editor/replace
{
  "file_path": "workspace/test.txt",
  "old_text": "旧文本",
  "new_text": "新文本",
  "use_regex": false
}
```

#### 智能编辑
```bash
POST /api/file-editor/smart-edit
{
  "file_path": "workspace/test.txt",
  "instruction": "把所有的 TODO 改成 DONE"
}
```

### 文件搜索 API

#### 搜索文件
```bash
POST /api/file-search/search
{
  "query": "python",
  "limit": 20,
  "file_types": [".py", ".txt"]
}
```

#### 内容查找
```bash
POST /api/file-search/find-by-content
{
  "content": "import flask\nfrom flask import Flask",
  "min_similarity": 0.3
}
```

#### 手动索引
```bash
POST /api/file-search/index
{
  "path": "workspace/documents",
  "is_directory": true
}
```

## 🔧 技术细节

### FileEditor 类
- **位置**: `web/file_editor.py`
- **核心方法**:
  - `read_file()` - 读取文件
  - `write_file()` - 写入文件
  - `replace_text()` - 替换文本
  - `insert_line()` - 插入行
  - `delete_lines()` - 删除行
  - `smart_edit()` - 智能编辑

### FileIndexer 类
- **位置**: `web/file_indexer.py`
- **核心方法**:
  - `index_file()` - 索引单个文件
  - `index_directory()` - 批量索引
  - `search()` - 全文搜索
  - `find_by_content()` - 相似度搜索
  - `list_indexed_files()` - 列出所有文件

### SmartDispatcher 路由
自动识别用户意图：
- **FILE_EDIT**: 修改、编辑、替换、删除行、插入
- **FILE_SEARCH**: 找文件、搜索、包含、哪个文件

## 📊 测试结果

运行 `python test_file_features.py`:

```
✅ 文件编辑测试
   - 创建文件: 成功
   - 文本替换: 1 处替换
   - 插入行: 成功
   - 智能编辑: 成功
   - 自动备份: 1 个备份文件

✅ 文件搜索测试
   - 索引文件: 99 个文件，39 个已索引
   - 搜索测试: 成功
   - 相似度查找: 100% 匹配
   - 统计信息: 3 种文件类型
```

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
