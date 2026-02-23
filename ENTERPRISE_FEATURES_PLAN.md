# 🏢 Koto 企业级功能规划 (B端 & C端)

**制定日期**: 2026-02-14 | **版本**: 1.0

---

## 📋 目录
1. [全文搜索系统](#全文搜索系统)
2. [权限管理系统](#权限管理系统)
3. [审计日志系统](#审计日志系统)
4. [数据加密方案](#数据加密方案)
5. [C端用户需求](#c端用户需求)

---

## 🔍 全文搜索系统

### 核心需求
- **快速索引** 生成每个文件的内容摘要 (100-200字)
- **结构化存储** SQLite数据库存储元数据 + 内容指纹
- **实时查询** <100ms 响应时间
- **支持格式** PDF, Word, Excel, 图片(OCR), 纯文本, Markdown

### 架构设计

```
归档文件 (archive/)
    ↓
文件监听器 (FileWatcher)
    ↓
并行处理器 (ProcessPool)
    ├─ 文本提取 (extract_text)
    ├─ 内容摘要 (summarize - AI驱动)
    ├─ 关键词提取 (extract_keywords)
    └─ 元数据收集 (metadata)
    ↓
索引数据库 (SQLite)
    ├─ file_index 表 (id, path, name, type, size, created, modified)
    ├─ content_summary 表 (file_id, summary, keywords, entities)
    ├─ full_text 表 (file_id, content, tokens)
    └─ search_history 表 (query, results_count, user_id, timestamp)
    ↓
搜索引擎 (全文 + 语义)
    ├─ 关键词匹配 (BM25)
    ├─ 语义搜索 (向量相似度)
    └─ 混合排序 (相关性评分)
```

### 数据库Schema

```sql
-- 文件索引表
CREATE TABLE file_index (
    id TEXT PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    file_type TEXT,
    size INTEGER,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    indexed_at TIMESTAMP,
    owner_id TEXT,
    organization_id TEXT
);

-- 内容摘要表
CREATE TABLE content_summary (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    summary TEXT,  -- 100-200字摘要
    keywords TEXT,  -- JSON: ["关键词1", "关键词2"]
    entities TEXT,  -- JSON: {组织: ["A公司"], 人名: ["张三"]}
    language TEXT,
    FOREIGN KEY(file_id) REFERENCES file_index(id)
);

-- 全文索引表
CREATE TABLE full_text_index (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    content TEXT,
    tokens_count INTEGER,
    indexed_at TIMESTAMP,
    FOREIGN KEY(file_id) REFERENCES file_index(id)
);

-- 搜索历史表
CREATE TABLE search_history (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    organization_id TEXT,
    query TEXT,
    results_count INTEGER,
    execution_time_ms INTEGER,
    created_at TIMESTAMP
);
```

### 搜索API设计

```python
# 1. 索引管理
GET /api/search/index/status
  → {"indexed_files": 1024, "total_files": 1050, "last_update": "2026-02-14T10:30:00Z"}

POST /api/search/index/rebuild
  → 本地索引，支持后台进度

# 2. 全文搜索
POST /api/search/query
{
    "q": "黄金价格",
    "type": "full_text|semantic|hybrid",  # hybrid默认
    "filters": {
        "file_type": ["pdf", "docx"],
        "date_range": ["2026-01-01", "2026-02-14"],
        "size_range": [0, 10485760]
    },
    "limit": 20,
    "offset": 0
}
→ 返回: [{file_id, name, path, summary, relevance_score, highlight_snippet}]

# 3. 高级搜索
POST /api/search/advanced
{
    "title": "*.docx",
    "content_keyword": "客户合同",
    "created_before": "2026-02-14",
    "owner": "user123"
}

# 4. 搜索建议
GET /api/search/suggestions?q=黄
→ ["黄金", "黄金价格", "黄世康", "黄河流域政策"]
```

### 实现优先级
1. ✅ 基础文本提取 (txt, md)
2. ⚠️ PDF/Word 提取 (需要库)
3. ⚠️ AI摘要 (调用Gemini)
4. ⚠️ 图片OCR (Tesseract)

---

## 🔐 权限管理系统

### 权限模型 (RBAC + 细粒度)

```
组织 (Organization)
├─ 团队 (Team)
│  ├─ 成员 (Member): {user_id, role, permissions}
│  └─ 文件夹 (Folder): {owner_id, shared_with, permissions}
└─ 文件 (File): {owner_id, shared_with, permissions}

角色定义:
├─ admin: 所有权限
├─ editor: 编辑/删除
├─ member: 查看/评论
└─ 自定义角色 (可配置权限)
```

### 权限粒度

```
文件级权限:
├─ view      (查看)
├─ edit      (编辑)
├─ delete    (删除)
├─ share     (分享)
├─ comment   (评论)
└─ download  (下载)

文件夹级权限:
├─ view      (查看文件夹及内容)
├─ create    (创建新文件)
├─ edit      (修改文件)
├─ manage    (管理权限)
└─ archive   (归档)
```

### 数据库Schema

```sql
-- 组织表
CREATE TABLE organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    created_at TIMESTAMP,
    plan TEXT DEFAULT 'free'  -- free, pro, enterprise
);

-- 团队表
CREATE TABLE teams (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP,
    FOREIGN KEY(organization_id) REFERENCES organizations(id)
);

-- 用户表
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    password_hash TEXT,
    organization_id TEXT,
    created_at TIMESTAMP
);

-- 角色定义表
CREATE TABLE roles (
    id TEXT PRIMARY KEY,
    organization_id TEXT,
    name TEXT,  -- admin, editor, member, 或自定义
    permissions TEXT,  -- JSON数组
    is_custom BOOLEAN DEFAULT FALSE
);

-- 用户-团队关系表
CREATE TABLE team_members (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    joined_at TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(team_id) REFERENCES teams(id),
    FOREIGN KEY(role_id) REFERENCES roles(id)
);

-- 文件权限表
CREATE TABLE file_permissions (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    grantee_id TEXT,  -- user_id 或 team_id
    grantee_type TEXT,  -- user, team, public
    permissions TEXT,  -- JSON: ["view", "edit", "delete"]
    granted_by TEXT,
    granted_at TIMESTAMP,
    expires_at TIMESTAMP
);

-- 分享链接表
CREATE TABLE share_links (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    permissions TEXT,  -- JSON: ["view", "download"]
    password_hash TEXT,
    expires_at TIMESTAMP,
    created_at TIMESTAMP
);
```

### API设计

```python
# 权限检查
def check_permission(user_id, file_id, action):
    """
    返回: True/False
    每次操作前调用此函数
    """

# 权限管理API
POST /api/permissions/grant
{
    "file_id": "file123",
    "grantee_id": "user456",
    "permissions": ["view", "edit"]
}

POST /api/permissions/revoke
{
    "file_id": "file123",
    "grantee_id": "user456"
}

# 分享API
POST /api/share/create-link
{
    "file_id": "file123",
    "permissions": ["view", "download"],
    "password": "optional",
    "expires_in_days": 7
}
→ {"share_link": "https://koto.example.com/s/abc123xyz"}
```

---

## 📝 审计日志系统

### 审计事件类型

```
用户操作:
├─ USER_LOGIN
├─ USER_LOGOUT
├─ USER_CREATED
├─ USER_DELETED
└─ PASSWORD_CHANGED

文件操作:
├─ FILE_CREATED
├─ FILE_MODIFIED
├─ FILE_DELETED
├─ FILE_ARCHIVED
├─ FILE_RESTORED
└─ FILE_VIEWED

权限操作:
├─ PERMISSION_GRANTED
├─ PERMISSION_REVOKED
├─ SHARE_LINK_CREATED
└─ SHARE_LINK_DELETED

数据操作:
├─ DATA_EXPORTED
├─ DATA_IMPORTED
├─ BACKUP_CREATED
└─ BACKUP_RESTORED
```

### 数据库Schema

```sql
CREATE TABLE audit_logs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT,  -- file, user, permission, etc
    resource_id TEXT,
    resource_name TEXT,
    old_value TEXT,  -- JSON
    new_value TEXT,  -- JSON
    status TEXT,  -- success, failure
    error_message TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at TIMESTAMP,
    INDEX idx_org_user_date (organization_id, user_id, created_at),
    INDEX idx_resource (resource_type, resource_id)
);
```

### API设计

```python
# 查询审计日志
POST /api/audit/logs
{
    "filters": {
        "user_id": "user123",
        "action": "FILE_MODIFIED",
        "resource_type": "file",
        "date_range": ["2026-02-01", "2026-02-14"]
    },
    "limit": 100,
    "offset": 0
}

# 导出审计报告
POST /api/audit/export
{
    "format": "csv|json|pdf",
    "include": ["all_actions"],
    "date_range": ["2026-01-01", "2026-02-14"]
}
```

### 合规特性
- ✅ 不可篡改 (APPEND-ONLY)
- ✅ 定期导出备份
- ✅ 长期保留 (最少7年)
- ✅ 符合 SOC2/ISO27001 标准

---

## 🔒 数据加密方案 (B端信任)

### 分层加密策略

```
加密层次:
1. 传输层 (Transport)
   ├─ HTTPS/TLS 1.3
   ├─ 证书固定 (Certificate Pinning)
   └─ 强制HSTS头

2. 应用层 (Application)
   ├─ 端到端加密 (E2E)
   ├─ 应用级加密
   └─ 密钥管理

3. 存储层 (Storage)
   ├─ 数据库加密 (SQLCipher)
   ├─ 文件系统加密
   └─ 备份加密
```

### 技术方案

```python
# 方案A: 端到端加密 (用户私钥加密)
客户端:
├─ 生成 RSA-2048 密钥对 (用户独有)
├─ 用公钥加密文件内容
└─ 文件发送到服务器

服务器:
├─ 只存储加密内容
├─ 无法解密数据
└─ 用户用私钥在本地解密

优点: 最高安全性，服务器不存风险
缺点: 无法全文搜索，分享复杂

# 方案B: 混合加密 (推荐B端)
客户端:
├─ 三层加密: 传输TLS + 应用AES256 + 存储SQLCipher
└─ 密钥存储在用户本地/HSM

服务器:
├─ 存储加密数据
├─ 密钥管理服务 (KMS)
└─ 仅授权用户可解密

优点: 支持搜索 + 高安全性
缺点: 需要验证用户身份

# 方案C: 供应商托管密钥 (企业标准, 最安全)
├─ AWS KMS / Azure Key Vault / Google Cloud KMS
├─ 密钥加密密钥 (KEK) 由供应商託管
├─ 数据加密密钥 (DEK) 轮转
└─ 审计所有密钥操作
```

### B端信任建立的关键要素

```
技术层:
✅ 独立安全审计报告 (每年)
✅ 开源加密库审计 (libsodium, NaCl)
✅ 漏洞赏金计划 (HackerOne)
✅ 实时安全日志导出

流程层:
✅ SOC2 Type II 认证
✅ ISO27001 认证
✅ GDPR/HIPAA/PCI合规证明
✅ 变更管理流程

治理层:
✅ 首席信息安全官 (CISO)
✅ 定期安全培训
✅ 安全事件响应计划
✅ 供应商安全审查
```

### 实现优先级

**最快建立信任的3步:**

1. **即刻** (1周)
   - 强制 HTTPS + HSTS
   - 实现应用层 AES256 加密 (存储敏感字段)
   - 生成安全白皮书

2. **短期** (4周)
   - 集成 AWS KMS/Azure KMS
   - 实现密钥轮转政策
   - 发起独立安全审计

3. **中期** (12周)
   - SOC2 Type II 认证
   - 漏洞赏金计划启动
   - 建立 CISO 职位

---

## 👤 C端用户需求规划

### 核心痛点 × 解决方案

| 用户痛点 | C端需求 | 优先级 | 通过什么赚钱 |
|---------|--------|--------|------------|
| 只有电脑能用 | 📱 移动应用 (iOS/Android) | 🔴 高 | 订阅制 |
| 没联网就搞不了 | 🔄 云同步 + 离线编辑 | 🔴 高 | 云存储容量 |
| 不知道自己做了什么 | 📊 周报/月报 (自动生成) | 🟡 中 | 高端分析 |
| 找不到之前的文件 | 🔎 全文搜索 (跨所有设备) | 🟡 中 | 搜索高级功能 |
| 每次都重复操作 | 🤖 快捷模板 (一键生成) | 🟡 中 | 模板库 |
| 无法跨设备协同 | 👥 多设备同步 (Sync) | 🟡 中 | 订阅制 |
| 怕数据丢失 | 💾 自动备份 (3个版本) | 🟢 低 | 基础功能 |
| 想分享给朋友 | 🔗 一键分享 (可设权限) | 🟢 低 | 基础功能 |

### C端商业模式

```
免费版 (Free):
├─ 100MB 存储
├─ 单设备
├─ 基础全文搜索
├─ 无电话支持
└─ 广告 (可选)

专业版 (Pro) - ¥59/月 or ¥499/年:
├─ 100GB 存储
├─ 无限设备
├─ 高级搜索 + 过滤
├─ 自动备份 (7天历史)
├─ 周报生成
├─ 邮件支持
└─ 移除广告

家庭版 (Family) - ¥99/月 or ¥799/年:
├─ 5个账户 × 2TB
├─ 共享图库
├─ 家庭管理界面
└─ 电话支持

企业/团队版 (Pro Business) - 另售:
├─ 团队协作
├─ 权限管理
├─ 审计日志
├─ SSO集成
├─ 专属账户经理
└─ SLA保证
```

### 关键功能 x 时间线

```
Q1 2026 (现在 - 3月):
├─ ✅ 全文搜索 (归档文件)
├─ ✅ 权限管理 (企业基础)
├─ ✅ 审计日志 (合规)
└─ 🚀 移动Web版 (响应式设计)

Q2 2026 (4月 - 6月):
├─ 📱 原生iOS应用 (React Native)
├─ 📱 原生Android应用
├─ 🔄 云同步 (选择: OneDrive/Google Drive)
└─ 📊 周报生成 (自动化)

Q3 2026 (7月 - 9月):
├─ 🤖 AI推荐引擎
├─ 📚 模板库 (社区)
├─ 🎨 自定义工作流
└─ 🔐 端到端加密 (可选)

Q4 2026 (10月 - 12月):
├─ 💬 实时协作编辑
├─ 📞 电话支持
├─ 🌍 国际化 (9种语言)
└─ 💳 支付系统 (Stripe)
```

### C端增长策略

```
用户获取:
├─ 产品猎人 (ProductHunt)
├─ 微博/小红书营销
├─ 技术博客合作
└─ 口碑转介

用户留存:
├─ 推送通知 (每日提示)
├─ 邮件营销 (周报)
├─ 社区建设 (用户论坛)
└─ 免费试用 (14天)

收入增长:
├─ 存储升级引导 (存满时提示)
├─ 功能解锁 (高级搜索)
├─ 订阅转化 (免费到Pro: 3%)
└─ 企业升级 (Pro到Business: 5%)
```

---

## 📊 成本 vs 收益

### 实现成本估算

| 功能 | 工程周数 | 团队规模 | 月度成本 |
|------|--------|--------|---------|
| 全文搜索 + 审计日志 | 4周 | 2人 | $10k |
| 权限管理 | 6周 | 2人 | $15k |
| 数据加密 + KMS集成 | 4周 | 1人 | $8k |
| 移动应用 (React Native) | 12周 | 3人 | $30k |
| 云同步 (OneDrive/Drive) | 8周 | 2人 | $16k |

**总投入**: 24-32周, 年度 $200-280k

### 预期收益 (Year 1)

```
B端 (企业客户):
├─ 客户数: 50家
├─ ARPU: $5,000/年
├─ 年收入: $250k
└─ 毛利: 70% ($175k)

C端 (消费者):
├─ 用户数: 100k
├─ Pro转化率: 3% (3k用户)
├─ ARPU: $400/年
├─ 年收入: $1.2M
└─ 毛利: 80% ($960k)

合计年收入: $1.45M
```

---

## 🎯 Next Steps

1. **本周** : 实现全文搜索 + 审计日志
2. **下周** : 权限管理系统 + 用户认证
3. **第3周**: 数据加密 + KMS集成
4. **第4周**: 移动Web版本 + 云同步选型

---

**准备开始哪个？** 建议从全文搜索开始，因为它最快产生用户价值。
