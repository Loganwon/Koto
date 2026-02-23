# P0 实施快速参考指南

## 🎯 核心功能速查表

### 1️⃣ 前端 PPT 按钮

**显示条件**:
```javascript
if (meta.ppt_session_id && role === 'assistant' && meta.task === 'FILE_GEN')
```

**按钮样式**:
- 容器: `.ppt-actions` - 蓝色左边框
- 编辑按钮: `.ppt-edit-btn` - 蓝色，链接式
- 下载按钮: `.ppt-download-btn` - 绿色，按钮式

**关键代码位置**:
- HTML: [web/static/js/app.js](web/static/js/app.js#L800)
- CSS: [web/static/css/style.css](web/static/css/style.css#L2830)
- JS 函数: [downloadPPT()](web/static/js/app.js#L668)

---

### 2️⃣ 后端 API 端点

#### POST /api/ppt/download
```bash
curl -X POST http://localhost:5000/api/ppt/download \
  -H "Content-Type: application/json" \
  -d '{"session_id": "058b46c3-66ec-4e50-857c-f483cf7c61d3"}'
```

**响应**: PPTX 文件 (Blob)

**位置**: [web/app.py](web/app.py#L8168)

#### GET /api/ppt/session/<session_id>
```bash
curl http://localhost:5000/api/ppt/session/058b46c3-66ec-4e50-857c-f483cf7c61d3
```

**响应**:
```json
{
  "session_id": "058b46c3-66ec-4e50-857c-f483cf7c61d3",
  "title": "项目提案 PPT",
  "status": "completed",
  "created_at": "2025-02-19T10:30:00Z",
  "ppt_file_path": "workspace/ppt_sessions/058b46c3.../generated_document.pptx"
}
```

**位置**: [web/app.py](web/app.py#L8190)

---

### 3️⃣ 会话管理

**创建会话**:
```python
from web.ppt_session_manager import PPTSessionManager

manager = PPTSessionManager('workspace/ppt_sessions')
session_id = manager.create_session(
    title="我的 PPT",
    user_input="生成演示文稿",
    theme="business"
)
```

**加载会话**:
```python
session = manager.load_session(session_id)
print(session['ppt_file_path'])
```

**保存数据**:
```python
manager.save_generation_data(
    session_id=session_id,
    ppt_data=pptx_object,
    ppt_file_path="/path/to/file.pptx"
)
```

---

### 4️⃣ 文件处理

**支持的格式**:
- 文本: `.txt`, `.md`
- 文档: `.pdf`, `.docx`  
- 图像: `.jpg`, `.png`

**处理单个文件**:
```python
from web.file_processor import FileProcessor

processor = FileProcessor()
result = processor.process_file('/path/to/file.txt')
if result['success']:
    content = result['text_content']
```

**多文件处理（文件融合）**:
```python
files = ['doc1.txt', 'doc2.pdf', 'doc3.docx']
fused_content = processor.fuse_files(files)
# 输出带来源标记的融合内容
```

---

### 5️⃣ 错误处理

**常见错误码**:

| 状态码 | 含义 | 处理 |
|--------|------|------|
| 400 | 缺少参数 | 检查请求体 |
| 404 | 未找到 | 会话或文件过期 |
| 500 | 服务器错误 | 查看日志 |

**捕获和处理**:
```python
try:
    session = manager.load_session(session_id)
except SessionNotFoundError:
    return jsonify({'error': 'Session not found'}), 404
except Exception as e:
    logger.error(f"Error: {e}")
    return jsonify({'error': str(e)}), 500
```

---

## 📊 完整流程图

```
用户上传文件
    ↓
前端: /api/chat/file (POST)
    ↓
后端: FileProcessor.process_file()
    ↙ (提取文本内容)
提交给 Gemini API
    ↙ (生成 PPTX)
PPTSessionManager.create_session()
    ↙ (保存文件和元数据)
返回 ppt_session_id
    ↙ (到前端)
前端: renderMessage() 检测 ppt_session_id
    ↙ (显示按钮)
用户点击下载
    ↓
前端: downloadPPT(session_id)
    ↙ (POST /api/ppt/download)
后端: get_ppt_file_path(session_id)
    ↙ (使用 send_file())
下载 PPTX 文件到本地
```

---

## 🧪 测试和验证

**运行全部测试**:
```bash
cd c:\Users\12524\Desktop\Koto
python tests/test_p0_comprehensive.py
```

**预期输出**:
```
测试总数: 11
通过: 11 ✅
成功率: 100%
```

**测试覆盖的场景**:
1. ✅ 前端 PPT 按钮 HTML 和 CSS
2. ✅ 后端会话创建
3. ✅ 下载 API 功能
4. ✅ 会话查询 API
5. ✅ 多文件处理
6. ✅ 文件来源标记
7. ✅ 错误处理
8. ✅ 完整用户流程

---

## 🚀 部署清单

- [ ] 更新 [web/app.py](web/app.py) - 添加新 API 端点
- [ ] 更新 [web/static/js/app.js](web/static/js/app.js) - 前端逻辑
- [ ] 更新 [web/static/css/style.css](web/static/css/style.css) - 样式
- [ ] 创建会话目录: `workspace/ppt_sessions/`
- [ ] 运行测试: `python tests/test_p0_comprehensive.py`
- [ ] 清除浏览器缓存
- [ ] 重启 Flask 服务器
- [ ] 验证按钮显示
- [ ] 验证下载功能
- [ ] 检查日志中的错误

---

## 📍 重要文件位置

| 功能 | 文件 | 行号 |
|------|------|------|
| 前端按钮 HTML | app.js | L800+ |
| 下载函数 | app.js | L668+ |
| 样式定义 | style.css | L2830+ |
| 下载 API | app.py | L8168+ |
| 会话查询 API | app.py | L8190+ |
| send_file 导入 | app.py | L20 |
| 会话管理 | ppt_session_manager.py | - |
| 文件处理 | file_processor.py | - |
| 全部测试 | test_p0_comprehensive.py | - |

---

## 💡 常见问题 FAQ

**Q: 如何禁用下载按钮？**
A: 在 renderMessage() 中注释掉 PPT 按钮的 HTML 生成代码

**Q: 如何自定义按钮样式？**
A: 编辑 `.ppt-btn`, `.ppt-edit-btn`, `.ppt-download-btn` 的 CSS

**Q: 支持的最大文件单个大小？**
A: 目前限制为 100MB（可在 FileProcessor 中配置）

**Q: 如何修改下载文件名？**
A: 在 downloadPPT() 中修改 `download_name` 参数

**Q: PPT 会话保留多久？**
A: 默认 30 天（可在 PPTSessionManager 中配置）

---

## 📞 调试技巧

**在浏览器控制台调试**:
```javascript
// 检查是否接收到 session_id
console.log(message.meta.ppt_session_id);

// 手动调用下载
downloadPPT('your-session-id');

// 检查网络请求
// 打开 DevTools → Network 标签 → 点下载
```

**查看服务器日志**:
```bash
# 对于 Flask 开发服务器
# 启用调试模式看详细日志
```

**验证文件存在**:
```bash
# Windows
dir "workspace\ppt_sessions\<session_id>"

# Linux/Mac
ls -la workspace/ppt_sessions/<session_id>
```

---

## ✨ 功能完成状态

| 功能 | 状态 | 备注 |
|------|------|------|
| 前端按钮显示 | ✅ 完成 | 经过验证 |
| 下载功能 | ✅ 完成 | 经过验证 |
| 会话管理 | ✅ 完成 | 经过验证 |
| 错误处理 | ✅ 完成 | 经过验证 |
| 单元测试 | ✅ 完成 | 11/11 通过 |
| 集成测试 | ✅ 完成 | 完整流程通过 |

**整体完成度**: 100% ✅

---

**最后更新**: 2025-02-19
**版本**: 1.0 (最终版)
**状态**: ✅ 生产就绪
