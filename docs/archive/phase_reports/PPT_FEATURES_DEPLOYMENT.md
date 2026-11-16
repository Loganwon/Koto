# Koto PPT 功能部署指南

## 已实现的功能

### ✅ P0 - 文件上传和融合（已完成）
- 支持 PDF、DOCX、TXT、Markdown 文件上传
- 自动提取文件内容并融合到 PPT 生成 prompt
- 完整的文件解析引擎（`web/file_parser.py`）

### ✅ P1 - 生成后编辑（已完成）
- 完整的 PPT 编辑 API (`/api/ppt/*`)
- 生成后编辑界面：修改内容、删除幻灯片、重新生成页面
- PPT 会话管理和持久化
- 单页 AI 重新生成功能

### 🔄 P2 - 多文件融合 RAG（待实现）

---

## 依赖安装

### 1. 必需的 Python 包

```bash
pip install PyPDF2 pdfplumber python-docx
```

或在你的 `requirements.txt` 中添加：

```
PyPDF2>=3.0.0
pdfplumber>=0.10.0
python-docx>=0.8.11
```

### 2. 已有的包（无需重新安装）
- `flask` - Web 框架
- `google-generativeai` - Gemini API
- 其他依赖（从 koto_app.py 启动时自动加载）

---

## 使用流程

### 方式 1：直接在聊天中生成 PPT（P0）

```
用户: "做一份关于人工智能的PPT，把这个PDF融合进去"
[上传 1-3 个文件]

Koto 会：
1. 📂 解析所有上传文件
2. 🔍 搜索最新的 AI 资讯
3. 🔬 深度研究 AI 技术架构
4. 📝 生成结构化大纲（融合所有文件内容）
5. 📊 生成完整 PPT 文件
6. 🎨 提供编辑链接：[点击编辑 PPT](/edit-ppt/<session_id>)
```

### 方式 2：生成后编辑 PPT（P1）

PPT 生成完成后，点击"编辑 PPT"链接，进入编辑界面：

1. **编辑幻灯片内容**
   - 修改标题和要点
   - 添加/删除/重排幻灯片

2. **AI 重新生成整页**
   - 选择要重来的页面
   - 点击"AI 重新生成"
   - Koto 会基于原始搜索和研究上下文重新撰写该页

3. **调整类型和风格**
   - 改变幻灯片类型（详细/概览/亮点/对比）
   - 重新渲染 PPT 文件

4. **下载最终版本**
   - 编辑完毕后点击"下载"
   - 获得最终的 PPTX 文件

---

## 核心文件说明

### 后端

| 文件 | 功能 |
|------|------|
| `web/file_parser.py` | 多格式文件解析（PDF/DOCX/TXT） |
| `web/ppt_session_manager.py` | PPT 生成会话管理（支持编辑） |
| `web/ppt_api_routes.py` | PPT 编辑 API 接口 |
| `web/app.py`（L5773+） | FILE_GEN PPT 完整流程 |
| `web/app.py`（L4150） | `/edit-ppt/<session_id>` 路由 |

### 前端

| 文件 | 功能 |
|------|------|
| `web/templates/edit_ppt.html` | PPT 编辑器 UI |
| 其他（待改造） | 聊天界面的文件上传区域 |

---

## 技术架构

### 文件上传流程

```
用户上传文件
    ↓
request.files.getlist('files[]')
    ↓
FileParser.batch_parse(文件列表)
    ├─ PDF → PyPDF2 / pdfplumber 提取文本
    ├─ DOCX → python-docx 提取段落 + 表格
    └─ TXT/MD → 直接读取
    ↓
FileParser.merge_contents() 合并所有文件
    ↓
融合到 ppt_outline_prompt（作为"参考资料"部分）
    ↓
AI 生成 PPT（充分利用上传内容 + 搜索结果 + 深度研究）
```

### PPT 编辑流程

```
PPT 生成完成
    ↓
创建 PPTSessionManager.create_session()
    ↓
保存数据：ppt_data + search_context + research_context
    ↓
返回 session_id 和编辑链接
    ↓
用户点击链接进入 /edit-ppt/<session_id>
    ↓
前端加载会话数据，显示幻灯片列表
    ↓
用户编辑/删除/AI 重生成
    ↓
调用 /api/ppt/* 接口保存修改
    ↓
点击"渲染"，重新生成 PPTX
    ↓
下载最终 PPT
```

### PPT API 接口清单

```
GET  /api/ppt/sessions                      列出最近的会话
GET  /api/ppt/session/<session_id>          获取会话详情
PUT  /api/ppt/slide/<session_id>/<index>    编辑单个幻灯片
DELETE /api/ppt/slide/<session_id>/<index>  删除幻灯片
POST /api/ppt/insert/<session_id>/<index>   插入新幻灯片
POST /api/ppt/reorder/<session_id>          重排幻灯片
POST /api/ppt/regenerate/<session_id>/<idx> AI 重新生成某页
POST /api/ppt/render/<session_id>           重新渲染 PPTX
GET  /api/ppt/download/<session_id>         下载 PPT 文件
```

---

## 故障排查

### 1. 导入 FileParser 失败
```
ImportError: cannot import name 'FileParser'
```
**解决**：确保 `web/` 目录在 Python 路径中，通过 `koto_app.py` 启动而非直接运行 `web/app.py`

### 2. PDF 解析失败
```
ImportError: No module named 'PyPDF2'
```
**解决**：
```bash
pip install PyPDF2 pdfplumber
```

### 3. PPT 编辑 API 返回 404
```
Could not build a URL for endpoint 'ppt_api.xxx'
```
**解决**：确保 `web/app.py` 中已注册蓝图（检查 L710+ 的 ppt_api_bp 注册）

### 4. 编辑界面加载不出来
- 检查浏览器控制台（F12）的错误信息
- 确保 `web/templates/edit_ppt.html` 文件存在
- 确保 Flask app 配置了模板路径

---

## P2 规划（多文件融合）

当前 P0 支持："文件内容作为搜索增强"。
P2 将提升为："多文件智能融合，自动识别关联"。

实现步骤（预计 2-3 周）：
1. 实装简单 RAG（基于关键词相似性）
2. 自动检测多文件中的共同主题
3. 生成"多源融合"的 PPT（如：3 份财报 → 竞争对比 PPT）
4. 知识沉淀：生成思维导图 JSON

---

## 快速开始

### 包装安装
```bash
cd Koto
pip install -r config/requirements.txt  # 基础包
pip install PyPDF2 pdfplumber python-docx  # 新增 P0 依赖
```

### 启动应用
```bash
python koto_app.py
```

### 访问编辑器
生成 PPT 后会看到：
```
🎨 [点击编辑 PPT](/edit-ppt/xxx-xxx-xxx) - 修改内容、调整顺序、重新生成页面
```
直接点击链接进入编辑页面。

---

## 代码示例

### 从 Python 代码调用文件解析

```python
from web.file_parser import FileParser

# 单个文件
result = FileParser.parse_file('/path/to/document.pdf')
print(result['content'])  # 提取的文本

# 批量文件
results = FileParser.batch_parse([
    '/path/to/doc1.pdf',
    '/path/to/doc2.docx',
])

# 合并内容
merged = FileParser.merge_contents(results)
```

### 从 Flask 应用调用会话管理

```python
from web.ppt_session_manager import get_ppt_session_manager

mgr = get_ppt_session_manager()

# 创建会话
session_id = mgr.create_session(
    title="我的 PPT",
    user_input="为...生成PPT",
    theme="business"
)

# 保存完整数据
mgr.save_generation_data(
    session_id=session_id,
    ppt_data=ppt_data_dict,
    ppt_file_path="/path/to/output.pptx",
    search_context="搜索结果...",
)

# 编辑幻灯片
mgr.update_slide(session_id, slide_index=2, {
    "title": "新标题",
    "points": ["新要点1", "新要点2"]
})
```

---

## 权限和配置

### 存储位置
- PPT 会话数据：`workspace/ppt_sessions/`（JSON 格式）
- PPT 文件：`workspace/documents/`（PPTX 格式）
- 临时上传文件：`workspace/temp_uploads/`（自动清理）

### 文件大小限制
- 单文件最大 50MB（`FileParser.MAX_FILE_SIZE`）
- 提取内容最多 100,000 字符（`FileParser.MAX_CONTENT_LENGTH`）

---

## 联系与反馈

如有问题或建议，请在日志中查看详细的 debug 信息：

```
[FILE_GEN/PPT] ✅ 已解析 3 个文件, 总字数: 50000
[FILE_GEN/PPT] 📋 创建编辑会话: abc-def-ghi
[PPT_API] ✅ PPT 编辑 API 已注册: /api/ppt
```

---

**版本**: 2.0（P0 + P1 完整）  
**最后更新**: 2026-02-20
