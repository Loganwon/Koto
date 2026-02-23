# 🔌 新功能集成指南

**集成日期**: 2026-02-14  
**集成难度**: ⭐⭐ 中等 (约4小时)  
**影响范围**: 核心API + 认证 + 数据库结构

---

## 📋 集成清单

### 步骤1: 导入新模块 (app.py 顶部)

```python
# 新的企业功能模块
from archive_search_engine import get_search_engine
from permission_manager import get_permission_manager, Permission
from audit_logger import get_audit_logger, AuditActionType
from data_encryption import get_encryption_manager, DataProtectionPolicy
```

### 步骤2: 初始化全局单例 (app启动时)

```python
# app.py 中的 create_app() 函数内，添加:

def create_app():
    app = Flask(__name__)
    # ... 现有代码 ...
    
    # 初始化新的企业模块
    with app.app_context():
        search_engine = get_search_engine()
        permission_mgr = get_permission_manager()
        audit_logger = get_audit_logger()
        encryption_mgr = get_encryption_manager()
        
        # 如果是首次运行，索引归档文件
        index_status = search_engine.get_index_status()
        if index_status["indexed_files"] == 0:
            print("⏳ 第一次运行，正在索引归档文件...")
            result = search_engine.index_archive(full_rebuild=True)
            print(f"✅ 索引完成: {result['indexed_count']} 个文件")
    
    return app
```

### 步骤3: 全文搜索API (添加到app.py)

```python
# ================= 全文搜索API =================

@app.route('/api/search/query', methods=['POST'])
def search_archive():
    """搜索归档文件 (全文搜索)"""
    data = request.json
    user_id = session.get('user_id', 'system')
    
    try:
        search_engine = get_search_engine()
        
        results = search_engine.search(
            query=data.get('q', ''),
            search_type=data.get('type', 'hybrid'),
            file_type=data.get('file_type'),
            date_range=data.get('date_range'),
            limit=data.get('limit', 20),
            offset=data.get('offset', 0),
            user_id=user_id
        )
        
        return jsonify(results)
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/search/index/rebuild', methods=['POST'])
@require_admin  # 仅管理员
def rebuild_search_index():
    """重建搜索索引 (后台任务)"""
    search_engine = get_search_engine()
    
    # 异步后台任务
    def rebuild():
        result = search_engine.index_archive(full_rebuild=True)
        return result
    
    # 返回任务ID供轮询
    task_id = str(uuid.uuid4())
    # TODO: 使用Celery或threading
    
    return jsonify({
        "task_id": task_id,
        "status": "rebuilding"
    })


@app.route('/api/search/suggestions', methods=['GET'])
def search_suggestions():
    """获取搜索建议"""
    prefix = request.args.get('q', '')
    
    search_engine = get_search_engine()
    suggestions = search_engine.get_search_suggestions(prefix, limit=5)
    
    return jsonify({"suggestions": suggestions})


@app.route('/api/search/status', methods=['GET'])
def search_status():
    """获取搜索索引状态"""
    search_engine = get_search_engine()
    status = search_engine.get_index_status()
    
    return jsonify(status)
```

### 步骤4: 权限管理API (添加到app.py)

```python
# ================= 权限管理API =================

@app.route('/api/permissions/check', methods=['POST'])
def check_permission():
    """检查权限 (前端/微服务可调用)"""
    data = request.json
    user_id = session.get('user_id')
    
    perm_mgr = get_permission_manager()
    has_perm = perm_mgr.check_permission(
        user_id=user_id,
        file_id=data['file_id'],
        action=data['action']
    )
    
    return jsonify({"allowed": has_perm})


@app.route('/api/permissions/grant', methods=['POST'])
@require_admin
def grant_permission():
    """授予权限"""
    data = request.json
    user_id = session.get('user_id')
    
    perm_mgr = get_permission_manager()
    success = perm_mgr.grant_permission(
        file_id=data['file_id'],
        grantee_id=data['grantee_id'],
        grantee_type=data.get('grantee_type', 'user'),
        permissions=data['permissions'],
        granted_by=user_id,
        organization_id=session.get('organization_id', 'default')
    )
    
    # 记录审计日志
    audit_logger = get_audit_logger()
    audit_logger.log_permission_granted(
        organization_id=session.get('organization_id', 'default'),
        user_id=user_id,
        file_id=data['file_id'],
        grantee_id=data['grantee_id'],
        permissions=data['permissions']
    )
    
    return jsonify({"success": success})


@app.route('/api/permissions/revoke', methods=['POST'])
@require_admin
def revoke_permission():
    """撤销权限"""
    data = request.json
    user_id = session.get('user_id')
    
    perm_mgr = get_permission_manager()
    success = perm_mgr.revoke_permission(
        file_id=data['file_id'],
        grantee_id=data['grantee_id'],
        revoked_by=user_id,
        organization_id=session.get('organization_id', 'default')
    )
    
    return jsonify({"success": success})


@app.route('/api/share/create-link', methods=['POST'])
def create_share_link():
    """创建分享链接"""
    data = request.json
    user_id = session.get('user_id')
    
    perm_mgr = get_permission_manager()
    token = perm_mgr.create_share_link(
        file_id=data['file_id'],
        created_by=user_id,
        permissions=data.get('permissions', ['view', 'download']),
        password=data.get('password'),
        expires_in_days=data.get('expires_in_days'),
        organization_id=session.get('organization_id', 'default')
    )
    
    if token:
        share_url = f"https://koto.example.com/shared/{token}"
        return jsonify({
            "share_link": share_url,
            "token": token,
            "expires_in": data.get('expires_in_days', 'Never')
        })
    
    return jsonify({"error": "Failed to create share link"}), 500


@app.route('/api/permissions/list', methods=['GET'])
def list_file_permissions():
    """获取文件的所有权限"""
    file_id = request.args.get('file_id')
    
    perm_mgr = get_permission_manager()
    permissions = perm_mgr.get_file_permissions(file_id)
    
    return jsonify({"permissions": permissions})
```

### 步骤5: 审计日志API (添加到app.py)

```python
# ================= 审计日志API =================

@app.route('/api/audit/logs', methods=['POST'])
@require_admin
def query_audit_logs():
    """查询审计日志"""
    data = request.json
    org_id = session.get('organization_id', 'default')
    
    audit_logger = get_audit_logger()
    logs, total = audit_logger.query_logs(
        organization_id=org_id,
        filters=data.get('filters'),
        limit=data.get('limit', 100),
        offset=data.get('offset', 0)
    )
    
    return jsonify({
        "logs": logs,
        "total_count": total
    })


@app.route('/api/audit/report', methods=['POST'])
@require_admin
def generate_audit_report():
    """生成审计报告 (合规性)"""
    data = request.json
    org_id = session.get('organization_id', 'default')
    
    audit_logger = get_audit_logger()
    report = audit_logger.generate_audit_report(
        organization_id=org_id,
        start_date=data['start_date'],
        end_date=data['end_date'],
        format=data.get('format', 'json')
    )
    
    return jsonify(report)


@app.route('/api/audit/export', methods=['POST'])
@require_admin
def export_audit_logs():
    """导出审计日志 (CSV/JSON)"""
    data = request.json
    org_id = session.get('organization_id', 'default')
    
    audit_logger = get_audit_logger()
    content = audit_logger.export_audit_logs(
        organization_id=org_id,
        start_date=data['start_date'],
        end_date=data['end_date'],
        format=data.get('format', 'csv')
    )
    
    # 返回可下载的文件
    if data.get('format') == 'csv':
        return Response(
            content,
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment;filename=audit_logs_{org_id}.csv"
            }
        )
    else:
        return Response(
            content,
            mimetype="application/json",
            headers={
                "Content-Disposition": f"attachment;filename=audit_logs_{org_id}.json"
            }
        )
```

### 步骤6: 数据加密API (添加到app.py)

```python
# ================= 数据加密API =================

@app.route('/api/encryption/enable-e2e', methods=['POST'])
@require_authentication
def enable_e2e_encryption():
    """为用户启用端到端加密"""
    user_id = session.get('user_id')
    
    encryption_mgr = get_encryption_manager()
    keys = encryption_mgr.enable_e2e_encryption(user_id)
    
    # 将公钥保存到用户profile
    # user_obj.e2e_public_key = keys['public_key']
    # user_obj.save()
    
    return jsonify({
        "key_id": keys['key_id'],
        "public_key": keys['public_key'],
        "algorithm": keys['algorithm']
    })


@app.route('/api/encryption/rotate-keys', methods=['POST'])
@require_admin
def rotate_encryption_keys():
    """密钥轮转 (管理员只)"""
    encryption_mgr = get_encryption_manager()
    success = encryption_mgr.rotate_keys()
    
    # 记录审计日志
    audit_logger = get_audit_logger()
    audit_logger.log_action(
        organization_id=session.get('organization_id', 'default'),
        user_id=session.get('user_id'),
        action=AuditActionType.ENCRYPTION_KEY_ROTATED,
        resource_type="system",
        resource_id="encryption",
        resource_name="Key Rotation",
        status="success" if success else "failure"
    )
    
    return jsonify({
        "success": success,
        "status": encryption_mgr.get_key_rotation_status()
    })


@app.route('/api/encryption/whitepaper', methods=['GET'])
def get_security_whitepaper():
    """获取安全白皮书 (公开)"""
    encryption_mgr = get_encryption_manager()
    whitepaper = encryption_mgr.generate_security_whitepaper()
    
    return jsonify(whitepaper)


@app.route('/api/compliance/dpa', methods=['GET'])
def get_dpa():
    """获取数据处理协议 (GDPR)"""
    dpa = DataProtectionPolicy.create_processing_agreement("Koto")
    
    return jsonify(dpa)
```

### 步骤7: 权限检查中间件 (修改现有API)

```python
# 在所有需要权限检查的路由中添加

@app.before_request
def check_request_permissions():
    """请求前检查权限 (对于文件操作)"""
    user_id = session.get('user_id')
    
    # 判断是否是文件操作API
    if request.path.startswith('/api/chat/file') or \
       request.path.startswith('/api/files/'):
        
        perm_mgr = get_permission_manager()
        
        # 从请求中提取文件ID
        file_id = request.json.get('file_id') if request.is_json else \
                  request.args.get('file_id')
        
        if file_id and user_id:
            # 检查权限
            action = 'view'  # 默认查看
            if request.method in ['POST', 'PUT']:
                action = 'edit'
            elif request.method == 'DELETE':
                action = 'delete'
            
            if not perm_mgr.check_permission(user_id, file_id, action):
                audit_logger = get_audit_logger()
                audit_logger.log_action(
                    organization_id=session.get('organization_id', 'default'),
                    user_id=user_id,
                    action=AuditActionType.FILE_VIEWED,
                    resource_type="file",
                    resource_id=file_id,
                    resource_name="",
                    status="failure",
                    error_message=f"Permission denied: {action}"
                )
                return jsonify({"error": "Permission denied"}), 403
```

### 步骤8: 修改现有文件操作API

```python
# 例如: chat_with_file() 函数，添加审计日志

def chat_with_file():
    """原有的上传文件API"""
    user_id = session.get('user_id')
    org_id = session.get('organization_id', 'default')
    
    # ... 现有代码 ...
    
    # 添加审计日志
    audit_logger = get_audit_logger()
    audit_logger.log_file_created(
        organization_id=org_id,
        user_id=user_id,
        file_id=file_id,
        file_name=file_name,
        file_size=file_size
    )
    
    # 如果需要加密存储
    encryption_mgr = get_encryption_manager()
    if user_has_e2e_enabled:
        file_content_encrypted = encryption_mgr.encrypt_data(
            file_content,
            associated_data=user_id
        )
        # 存储加密内容
    
    return jsonify({...})
```

### 步骤9: 前端integration (javascript/templates)

```html
<!-- 在主页面添加搜索面板 -->

<div id="searchPanel" class="search-panel">
  <input type="text" 
         id="searchInput" 
         placeholder="搜索归档文件..." 
         autocomplete="off">
  <ul id="searchResults" class="search-results"></ul>
</div>

<script>
// 搜索功能
const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');

searchInput.addEventListener('input', async (e) => {
  const query = e.target.value;
  
  if (query.length < 2) {
    searchResults.innerHTML = '';
    return;
  }
  
  try {
    const response = await fetch('/api/search/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q: query })
    });
    
    const data = await response.json();
    
    // 渲染结果
    searchResults.innerHTML = data.results.map(r => `
      <li>
        <a href="/archive/${r.file_id}">
          <strong>${r.name}</strong>
          <small>${r.summary.substring(0, 50)}...</small>
        </a>
      </li>
    `).join('');
  } catch (error) {
    console.error('Search error:', error);
  }
});
</script>
```

---

## 🧪 测试清单

```bash
# 单元测试
pytest web/tests/test_search_engine.py -v
pytest web/tests/test_permission_manager.py -v
pytest web/tests/test_audit_logger.py -v
pytest web/tests/test_encryption.py -v

# 集成测试
curl -X POST http://localhost:5000/api/search/query \
  -H "Content-Type: application/json" \
  -d '{"q":"黄金价格"}'

curl -X POST http://localhost:5000/api/permissions/grant \
  -H "Content-Type: application/json" \
  -d '{"file_id":"file123","grantee_id":"user456","permissions":["view","edit"]}'

# 性能测试
ab -n 1000 -c 10 http://localhost:5000/api/search/query

# 安全测试
# - SQL注入
# - 权限绕过
# - 加密强度验证
```

---

## 📚 依赖包

```
# requirements.txt 添加

# 搜索与加密
cryptography>=41.0.0
PyPDF2>=4.0.1
python-docx>=0.8.11
openpyxl>=3.1.0
pillow>=10.0.0
pytesseract>=0.3.10

# 数据库
sqlcipher3>=3.12.2  # 可选，用于数据库层加密

# API文档
flasgger>=0.9.7.1
```

---

## 🚀 部署检查

```
部署前验证:
☐ 所有新模块导入成功
☐ 数据库初始化完成
☐ 搜索索引构建成功
☐ 权限检查生效
☐ 审计日志记录正常
☐ 加密密钥安全存储

环境变量设置:
KOTO_ENCRYPTION_KEY_FILE=".koto_master_key"
KOTO_ARCHIVE_ROOT="workspace/_archive"  
KOTO_DB_SEARCH=".koto_search.db"
KOTO_DB_PERMISSIONS=".koto_permissions.db"
KOTO_DB_AUDIT=".koto_audit.db"
```

---

## ⏱️ 预期集成时间

- 代码集成: 2小时
- 测试与调试: 1.5小时
- 文档与部署: 0.5小时
- **总计**: 4小时

---

**需要帮助？** 我已经为你完整实现了4个核心模块，现在可以直接集成到app.py中。
