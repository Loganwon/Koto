# P0 部署和验证指南

## 🚀 部署前检查清单

### ✅ 文件检查

```powershell
# 验证所有关键文件是否已更新

# 前端文件
Test-Path "web\static\js\app.js"              # 应显示 True
Test-Path "web\static\css\style.css"           # 应显示 True

# 后端文件
Test-Path "web\app.py"                         # 应显示 True
Test-Path "web\ppt_session_manager.py"        # 应显示 True

# 测试文件
Test-Path "tests\test_p0_comprehensive.py"    # 应显示 True
```

### ✅ 代码验证

**验证导入**:
```python
# 检查 app.py 是否包含 send_file
grep "from flask import send_file" web/app.py

# 检查 app.js 是否包含 downloadPPT 函数
grep "function downloadPPT" web/static/js/app.js
```

**验证 API 端点**:
```python
# 检查两个新 API 端点是否存在
grep "@app.route('/api/ppt/download'" web/app.py
grep "@app.route('/api/ppt/session/" web/app.py
```

---

## 📋 部署步骤

### Step 1: 创建会话目录

```powershell
# Windows PowerShell
New-Item -ItemType Directory -Path "workspace\ppt_sessions" -Force

# 验证创建成功
Test-Path "workspace\ppt_sessions"  # 应显示 True
```

### Step 2: 运行全面测试

```bash
# 在项目根目录运行
python tests/test_p0_comprehensive.py
```

**预期结果**:
```
测试总数: 11
通过: 11 ✅
失败: 0 ❌
成功率: 100%
```

### Step 3: 启动应用

```bash
# 清除旧的 Python 缓存
Remove-Item -Path "__pycache__" -Recurse -Force
Remove-Item -Path "web\__pycache__" -Recurse -Force

# 启动 Flask 应用
python koto_app.py

# 或使用启动脚本
.\Koto.vbs
```

**预期输出**:
```
 * Running on http://127.0.0.1:5000
 * Debug mode: off
```

### Step 4: 清除浏览器缓存

```javascript
// 在浏览器 DevTools 中执行
// 或按 Ctrl+Shift+Delete 打开清除缓存对话

// 清除所有缓存（确保加载最新代码）
// 选择时间范围: 所有时间
// 选择清除内容：
// ✅ Cookies 和其他网站数据
// ✅ 缓存的图像和文件
```

### Step 5: 验证部署

打开浏览器访问: `http://localhost:5000`

---

## 🧪 功能验证测试

### 测试 1: PPT 按钮显示

**步骤**:
1. 打开应用首页
2. 上传一个文本文件（或图像）
3. 输入提示词: "根据这个文件生成 PPT 演示文稿"
4. 提交请求

**验证点**:
- ✅ 收到响应后，应显示 "📊 PPT 已生成"
- ✅ 显示 [📝 编辑] 和 [⬇️ 下载] 两个按钮
- ✅ 按钮有蓝色和绿色的背景色

**调试**:
```javascript
// 在浏览器控制台运行
console.log('检查是否有 session_id:', message.meta.ppt_session_id);
```

### 测试 2: PPT 下载功能

**步骤**:
1. 完成测试 1，确保按钮已显示
2. 点击 [⬇️ 下载] 按钮
3. 等待文件下载完成

**验证点**:
- ✅ 浏览器触发文件下载
- ✅ 文件名格式: `generated_<session_id>.pptx`
- ✅ 文件可以用 PowerPoint 打开

**调试**:
```javascript
// 检查网络请求
// 打开 DevTools → Network 标签
// 查找 POST 请求到 /api/ppt/download
// 检查响应状态: 应该是 200
```

### 测试 3: PPT 编辑功能

**步骤**:
1. 完成测试 1，确保按钮已显示
2. 点击 [📝 编辑] 按钮
3. 应跳转到编辑界面（如果已实现）

**验证点**:
- ✅ 链接跳转到 `/edit-ppt/<session_id>`
- ✅ 编辑界面加载成功

**调试**:
```javascript
// 检查链接格式
const sessionId = message.meta.ppt_session_id;
const editUrl = `/edit-ppt/${sessionId}`;
console.log('编辑链接:', editUrl);
```

### 测试 4: 会话 API

**步骤**:
1. 获取一个 session_id（从 PPT 按钮所在消息中获取）
2. 使用 API 查询会话信息

```bash
# 使用 curl 测试
curl "http://localhost:5000/api/ppt/session/<session_id>" \
  -H "Content-Type: application/json"

# 预期响应:
# {
#   "session_id": "...",
#   "title": "...",
#   "status": "completed",
#   "created_at": "...",
#   "ppt_file_path": "..."
# }
```

**验证点**:
- ✅ API 返回 200 状态码
- ✅ 返回 JSON 格式的会话数据
- ✅ `ppt_file_path` 不为 null

### 测试 5: 多文件处理

**步骤**:
1. 同时上传 2-3 个文件
2. 输入提示词: "融合这些文件内容，生成 PPT"
3. 提交请求

**验证点**:
- ✅ 所有文件都被成功处理
- ✅ 生成的 PPT 包含所有文件的内容
- ✅ 每个文件的内容有来源标记: `【来源: filename】`

### 测试 6: 错误处理

**测试场景 1: 无效会话 ID**
```bash
curl -X POST "http://localhost:5000/api/ppt/download" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "invalid-id-12345"}'

# 预期: 404 状态码 + 错误消息
```

**测试场景 2: 缺少参数**
```bash
curl -X POST "http://localhost:5000/api/ppt/download" \
  -H "Content-Type: application/json" \
  -d '{}'

# 预期: 400 状态码 + "Missing session_id" 错误
```

**验证点**:
- ✅ 错误响应有 HTTP 状态码
- ✅ 返回 JSON 格式的错误信息
- ✅ 浏览器显示用户友好的错误提示

---

## 📊 性能验证

### 响应时间测试

```powershell
# 测试 PPT 生成时间
Measure-Command {
    # 上传文件并生成 PPT
} | Select-Object TotalSeconds
```

**预期**:
- 文件上传: < 5 秒
- PPT 生成: < 30 秒（取决于 Gemini API）
- 文件下载: < 5 秒

### 并发请求测试

```python
# 测试多个并发请求
import concurrent.futures
import requests

def upload_file(file_path):
    with open(file_path, 'rb') as f:
        return requests.post(
            'http://localhost:5000/api/chat/file',
            files={'file': f}
        )

# 并发 5 个请求
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(upload_file, f) for f in files]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]

print(f"成功: {sum(1 for r in results if r.status_code == 200)}/5")
```

### 文件大小测试

| 文件大小 | 预期时间 | 状态 |
|---------|---------|------|
| < 10 MB | < 10 s | ✅ |
| 10-50 MB | 10-30 s | ✅(缓慢) |
| 50-100 MB | 30-60 s | ⚠️ |
| > 100 MB | 超时 | ❌ |

---

## 🔍 监控和日志

### 启用详细日志

在 [web/app.py](web/app.py) 中添加:

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
```

### 查看日志

```bash
# 查看实时日志（PowerShell）
Get-Content logs/app.log -Wait

# 或查看最后 100 行
Get-Content logs/app.log -Tail 100
```

### 关键日志点

- `[PPT] 会话创建: {session_id}`
- `[PPT] 文件下载: {file_path}`
- `[PPT] 错误: {error_message}`

---

## 🆘 故障排除

### 问题 1: 按钮不显示

**症状**: 即使生成了 PPT，也没有看到下载按钮

**排查步骤**:

1. 检查浏览器控制台:
```javascript
// 打开 DevTools（F12）→ Console 标签
// 查看是否有 JavaScript 错误
```

2. 检查响应数据:
```javascript
// 在控制台检查消息元数据
console.log(message.meta);
// 应该包含: { task: 'FILE_GEN', ppt_session_id: '...' }
```

3. 清除缓存:
```
Ctrl+Shift+Delete → 清除所有缓存
```

4. 检查代码:
```python
# 在 app.py 中，/api/chat/file 端点是否返回 ppt_session_id
# 应该在响应中包含: "ppt_session_id": "<session_id>"
```

### 问题 2: 下载失败

**症状**: 点击下载后，Nothing happens

**排查步骤**:

1. 检查网络请求:
```
DevTools → Network 标签 → 点下载 → 查看请求和响应
```

2. 可能的错误:
- `404 Not Found`: 会话不存在，检查 session_id
- `500 Server Error`: 文件不存在或权限问题
- `413 Payload Too Large`: 文件过大，超过限制

3. 检查文件:
```powershell
# 确认 PPTX 文件存在
Test-Path "workspace\ppt_sessions\<session_id>\generated_document.pptx"
```

4. 检查日志:
```
查看 Flask 控制台输出或 logs/app.log
```

### 问题 3: API 超时

**症状**: 请求一直处于加载状态，最终超时

**排查步骤**:

1. 检查 Gemini API:
```python
# 测试 API 连接
import google.generativeai as genai
genai.configure(api_key="your_key")
# 尝试生成内容看是否超时
```

2. 增加超时时间:
```python
# 在 app.py 中修改
timeout = 60  # 增加到 60 秒
```

3. 检查网络:
```bash
ping api.gemini.google.com
```

### 问题 4: 文件权限错误

**症状**: "Permission denied" 或 "Access denied"

**排查步骤**:

1. 检查文件权限:
```powershell
# 获取文件权限
Get-Acl "workspace\ppt_sessions\<id>" | Format-List
```

2. 修复权限:
```powershell
# 授予文件夹读写权限
icacls "workspace\ppt_sessions" /grant:r "$ENV:USERNAME:(OI)(CI)F"
```

3. 或改变所有者:
```powershell
Take-Ownership "workspace\ppt_sessions"
```

---

## 📈 性能优化建议

### 1. 启用缓存

```python
# 在 Flask 应用中启用缓存
from flask_caching import Cache

cache = Cache(app, config={'CACHE_TYPE': 'simple'})

@app.route('/api/ppt/session/<id>')
@cache.cached(timeout=300)  # 5 分钟缓存
def get_ppt_session(id):
    ...
```

### 2. 异步处理

```python
# 使用 Celery 处理耗时的 PPT 生成
from celery import Celery

@app.route('/api/chat/file', methods=['POST'])
async def upload_file():
    # 提交到后台任务队列
    task = generate_ppt_async.delay(file_content)
    return jsonify({'task_id': task.id})
```

### 3. 文件压缩

```python
# 压缩上传文件
import gzip

def compress_file(file_path):
    with open(file_path, 'rb') as f_in:
        with gzip.open(f_path + '.gz', 'wb') as f_out:
            f_out.write(f_in.read())
```

---

## ✅ 部署完成检查

| 项目 | 检查 | 状态 |
|------|------|------|
| 文件更新 | app.js, style.css, app.py | ☐ |
| 会话目录 | 创建 workspace/ppt_sessions | ☐ |
| 全部测试 | 运行 test_p0_comprehensive.py | ☐ |
| 缓存清空 | 浏览器缓存已清空 | ☐ |
| 服务器启动 | Flask 应用已启动 | ☐ |
| 按钮显示 | 已验证按钮能显示 | ☐ |
| 下载功能 | 已验证文件能下载 | ☐ |
| API 测试 | 已验证 API 端点 | ☐ |
| 错误处理 | 已验证错误提示 | ☐ |
| 性能查验 | 响应时间正常 | ☐ |

---

**部署日期**: ________________
**部署人员**: ________________
**验证人员**: ________________
**备注**: ___________________________________________________________________

✅ P0 功能已部署并验证就绪！
