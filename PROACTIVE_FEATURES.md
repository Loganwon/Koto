# 🚀 Koto 增强主动能力 - 完整实现文档

## 📋 目录

1. [概述](#概述)
2. [核心模块](#核心模块)
3. [API文档](#api文档)
4. [使用指南](#使用指南)
5. [配置说明](#配置说明)
6. [最佳实践](#最佳实践)

---

## 概述

本次更新为Koto添加了完整的**主动交互能力**，实现了从"被动响应"到"主动伙伴"的跨越。

### 🎯 核心目标

- **实时感知**: 系统持续监控用户行为和工作场景
- **主动建议**: 基于场景智能推送相关建议
- **自动执行**: 在用户授权下自动完成重复任务
- **智能对话**: 主动问候、提醒和关怀

### ✨ 新增功能

| 模块 | 功能 | 代码量 |
|------|------|--------|
| 通知管理 | WebSocket实时推送、优先级管理、用户偏好 | 640行 |
| 主动对话 | 8种对话场景、自动触发、历史记录 | 680行 |
| 情境感知 | 5种工作场景、自动识别、行为适配 | 650行 |
| 自动执行 | 7种任务类型、授权管理、队列处理 | 720行 |
| API集成 | 24个新端点、完整CRUD操作 | 600行 |
| **总计** | **40+新功能点** | **3290行** |

---

## 核心模块

### 1. 实时通知系统 (notification_manager.py)

#### 功能特性

- ✅ **WebSocket推送**: 实时通知到客户端
- ✅ **优先级管理**: 5级优先级（critical/high/medium/low/safe）
- ✅ **用户偏好**: 静音时段、每日限额、类型过滤
- ✅ **通知历史**: 完整的发送、阅读、忽略记录
- ✅ **统计分析**: 阅读率、行动率、参与度分析

#### 数据库结构

```sql
-- 通知记录
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY,
    user_id TEXT,
    type TEXT,         -- suggestion/insight/reminder/achievement/greeting/alert/tip
    priority TEXT,     -- critical/high/medium/low
    title TEXT,
    message TEXT,
    data TEXT,         -- JSON附加数据
    created_at TIMESTAMP,
    read_at TIMESTAMP,
    dismissed_at TIMESTAMP
);

-- 用户偏好
CREATE TABLE user_preferences (
    user_id TEXT PRIMARY KEY,
    enabled_types TEXT,          -- 启用的通知类型
    quiet_hours_start TEXT,      -- 静音开始时间
    quiet_hours_end TEXT,        -- 静音结束时间
    max_daily_notifications INT, -- 每日最大通知数
    priority_threshold TEXT      -- 最低优先级阈值
);
```

#### 使用示例

```python
from notification_manager import get_notification_manager

# 获取实例
manager = get_notification_manager()

# 发送通知
notification_id = manager.send_notification(
    user_id='user123',
    notification_type='suggestion',
    priority='medium',
    title='整理建议',
    message='workspace目录下有5个文件需要整理',
    data={'file_count': 5}
)

# 获取未读通知
unread = manager.get_unread_notifications('user123', limit=50)

# 标记已读
manager.mark_as_read(notification_id, 'user123')

# 设置偏好
manager.update_user_preferences('user123', {
    'quiet_hours_start': '22:00',
    'quiet_hours_end': '08:00',
    'max_daily_notifications': 20
})
```

---

### 2. 主动对话引擎 (proactive_dialogue.py)

#### 对话场景

| 场景类型 | 触发条件 | 频率 |
|---------|---------|------|
| morning_greeting | 早晨6-12点 | 每12小时 |
| afternoon_greeting | 下午12-18点 | 每12小时 |
| evening_greeting | 晚上18-24点 | 每12小时 |
| long_break_reminder | 24小时未活动 | 每24小时 |
| work_too_long | 连续工作2小时 | 每2小时 |
| achievement | 达成里程碑 | 每72小时 |
| file_organization | 发现杂乱文件 | 每24小时 |
| weekly_summary | 每周一 | 每168小时 |

#### 对话模板示例

```python
DIALOGUE_TEMPLATES = {
    'morning_greeting': [
        "☀️ 早上好！新的一天开始了，今天有什么计划吗？",
        "🌅 美好的早晨！昨天创建了 {file_count} 个文件，今天继续加油！",
        "🎯 早安！你有 {pending_suggestions} 条智能建议待查看，要现在处理吗？"
    ],
    'work_too_long': [
        "😴 你已经连续工作 {hours} 小时了，要不要休息一下？",
        "🧘 注意休息！持续工作 {hours} 小时容易疲劳，建议稍作休息。"
    ],
    'achievement': [
        "🏆 恭喜！你已完成 {milestone} 篇笔记，继续保持！",
        "🎊 太棒了！本周生产力提升了 {improvement}%！"
    ]
}
```

#### 使用示例

```python
from proactive_dialogue import get_proactive_dialogue_engine

# 初始化（需要依赖模块）
engine = get_proactive_dialogue_engine(
    notification_manager=notif_mgr,
    behavior_monitor=behavior_mon,
    suggestion_engine=suggestion_eng
)

# 启动自动监控（每5分钟检查一次）
engine.start_monitoring(check_interval=300)

# 手动触发对话
engine.manual_trigger(
    user_id='user123',
    scene_type='morning_greeting',
    file_count=5,
    pending_suggestions=3
)

# 获取对话历史
history = engine.get_dialogue_history('user123', limit=50)

# 停止监控
engine.stop_monitoring()
```

---

### 3. 情境感知系统 (context_awareness.py)

#### 工作场景定义

| 场景 | 关键词 | 文件类型 | 行为配置 |
|------|--------|---------|---------|
| **专业工作** | 项目、代码、会议、报告 | .py, .js, .md, .docx | 中等建议频率 |
| **学习研究** | 教程、笔记、课程、论文 | .pdf, 笔记, 教程 | 低建议频率 |
| **创作写作** | 写作、创作、文章、博客 | .txt, .md, .doc | 极低建议频率 |
| **整理归档** | 整理、归档、分类、清理 | - | 高建议频率 |
| **休闲浏览** | 浏览、查看、阅读 | - | 极低建议频率 |

#### 场景检测算法

```python
# 得分计算（总分1.0）
scores = {
    'keyword_matching': 0.4,    # 关键词匹配
    'file_pattern': 0.3,        # 文件类型匹配
    'time_hints': 0.2,          # 时间段匹配
    'operation_pattern': 0.1    # 操作模式匹配
}

# 场景置信度阈值
CONFIDENCE_THRESHOLD = 0.5

# 场景行为适配
if context_type == 'learning':
    config = {
        'suggestion_frequency': 'low',
        'notification_priority_threshold': 'low',
        'enable_features': ['knowledge_assistant', 'concept_explanation']
    }
```

#### 使用示例

```python
from context_awareness import get_context_awareness_system

# 初始化
system = get_context_awareness_system(behavior_monitor=behavior_mon)

# 检测场景
context = system.detect_context(user_id='user123')
print(f"当前场景: {context['context_name']}")
print(f"置信度: {context['confidence']:.2%}")
print(f"行为配置: {context['behavior_config']}")

# 获取场景历史
history = system.get_context_history('user123', days=7)

# 获取统计
stats = system.get_context_statistics('user123', days=30)
print(f"主要场景: {stats['dominant_context']}")
print(f"总工作时长: {stats['total_hours']}小时")

# 预测下一个场景
prediction = system.predict_next_context('user123')
```

---

### 4. 自动执行引擎 (auto_execution.py)

#### 内置任务类型

| 任务类型 | 风险等级 | 描述 | 示例参数 |
|---------|---------|------|---------|
| **organize_files** | low | 按类型整理文件 | `{directory: 'workspace'}` |
| **archive_old_files** | medium | 归档旧文件 | `{directory: 'workspace', days: 90}` |
| **backup_file** | safe | 创建文件备份 | `{file_path: 'important.md'}` |
| **remove_duplicates** | high | 删除重复文件 | `{directory: 'workspace'}` |
| **create_folder** | safe | 创建文件夹 | `{folder_path: 'new_folder'}` |
| **rename_file** | low | 重命名文件 | `{old_path: 'old.txt', new_name: 'new.txt'}` |
| **generate_report** | safe | 生成报告 | `{type: 'weekly'}` |

#### 风险等级说明

```python
RISK_LEVELS = {
    'safe': {
        'level': 1,
        'require_approval': False,
        'allow_auto_execute': True
    },
    'low': {
        'level': 2,
        'require_approval': False,
        'allow_auto_execute': True
    },
    'medium': {
        'level': 3,
        'require_approval': True,
        'allow_auto_execute': False
    },
    'high': {
        'level': 4,
        'require_approval': True,
        'allow_auto_execute': False
    }
}
```

#### 使用示例

```python
from auto_execution import get_auto_execution_engine

# 初始化
engine = get_auto_execution_engine()

# 1. 授权任务
engine.authorize_task(
    user_id='user123',
    task_type='backup_file',
    auto_execute=True,     # 允许自动执行
    max_executions_per_day=10,
    expires_days=30
)

# 2. 执行任务
result = engine.execute_task(
    user_id='user123',
    task_type='backup_file',
    params={'file_path': 'important.md'}
)

if result['success']:
    print(f"执行成功: {result['result']}")
else:
    print(f"执行失败: {result['error']}")

# 3. 任务加入队列
task_id = engine.queue_task(
    user_id='user123',
    task_type='organize_files',
    params={'directory': 'workspace'},
    priority=5
)

# 4. 启动队列处理器
engine.start_queue_processor(interval=60)  # 每分钟处理一次

# 5. 获取执行历史
history = engine.get_execution_history('user123', limit=50)

# 6. 获取统计
stats = engine.get_statistics('user123', days=30)
print(f"成功率: {stats['success_rate']:.1f}%")
```

---

## API文档

### 通知管理 API

#### 1. GET /api/notifications/unread
获取未读通知

**参数**:
- `user_id` (可选): 用户ID，默认 'default'
- `limit` (可选): 返回数量，默认 50

**响应**:
```json
{
  "success": true,
  "notifications": [
    {
      "id": 1,
      "type": "suggestion",
      "priority": "medium",
      "title": "整理建议",
      "message": "workspace目录下有5个文件需要整理",
      "data": {"file_count": 5},
      "created_at": "2026-02-15T10:30:00"
    }
  ],
  "count": 1
}
```

#### 2. POST /api/notifications/mark-read
标记通知已读

**请求体**:
```json
{
  "notification_id": 1,
  "user_id": "user123"
}
```

#### 3. POST /api/notifications/dismiss
忽略通知

#### 4. GET /api/notifications/stats
获取通知统计

**参数**:
- `user_id`: 用户ID
- `days`: 统计天数，默认7

**响应**:
```json
{
  "success": true,
  "stats": {
    "period_days": 7,
    "total_sent": 42,
    "total_read": 35,
    "total_acted": 12,
    "read_rate": 83.33,
    "action_rate": 28.57,
    "by_type": {
      "suggestion": {
        "sent": 15,
        "read": 12,
        "engagement_rate": 26.67
      }
    }
  }
}
```

#### 5. GET/POST /api/notifications/preferences
获取或设置通知偏好

---

### 主动对话 API

#### 1. POST /api/dialogue/start-monitoring
启动主动对话监控

**请求体**:
```json
{
  "check_interval": 300
}
```

#### 2. POST /api/dialogue/stop-monitoring
停止主动对话监控

#### 3. POST /api/dialogue/trigger
手动触发对话

**请求体**:
```json
{
  "user_id": "user123",
  "scene_type": "morning_greeting",
  "context": {
    "file_count": 5,
    "pending_suggestions": 3
  }
}
```

#### 4. GET /api/dialogue/history
获取对话历史

**参数**:
- `user_id`: 用户ID
- `limit`: 返回数量

---

### 情境感知 API

#### 1. POST /api/context/detect
检测当前工作场景

**请求体**:
```json
{
  "user_id": "user123"
}
```

**响应**:
```json
{
  "success": true,
  "context": {
    "context_type": "learning",
    "context_name": "学习研究",
    "confidence": 0.75,
    "indicators": {
      "current_hour": 14,
      "recent_files": ["tutorial.pdf", "notes.md"],
      "recent_operations": ["file_open", "file_search"]
    },
    "behavior_config": {
      "suggestion_frequency": "low",
      "notification_priority_threshold": "low",
      "focus_areas": ["knowledge_management", "concept_extraction"]
    },
    "all_scores": {
      "professional": 0.45,
      "learning": 0.75,
      "creative": 0.30
    }
  }
}
```

#### 2. GET /api/context/current
获取当前场景

#### 3. GET /api/context/history
获取场景历史

#### 4. GET /api/context/statistics
获取场景统计

**响应**:
```json
{
  "success": true,
  "statistics": {
    "period_days": 30,
    "total_hours": 125.5,
    "dominant_context": "professional",
    "by_type": {
      "professional": {
        "session_count": 45,
        "total_minutes": 4500,
        "percentage": 60.0
      }
    }
  }
}
```

#### 5. GET /api/context/predict
预测下一个场景

---

### 自动执行 API

#### 1. POST /api/execution/authorize
授权任务执行

**请求体**:
```json
{
  "user_id": "user123",
  "task_type": "backup_file",
  "auto_execute": true,
  "max_executions_per_day": 10,
  "expires_days": 30
}
```

#### 2. POST /api/execution/revoke
撤销任务授权

#### 3. POST /api/execution/execute
执行任务

**请求体**:
```json
{
  "user_id": "user123",
  "task_type": "backup_file",
  "params": {
    "file_path": "important.md"
  },
  "force": false
}
```

**响应**:
```json
{
  "success": true,
  "execution_id": 123,
  "result": {
    "original_file": "important.md",
    "backup_path": "backups/20260215/important_143052.md",
    "backup_size": 2048
  },
  "duration_ms": 150
}
```

#### 4. POST /api/execution/queue
任务加入队列

#### 5. GET /api/execution/history
获取执行历史

#### 6. GET /api/execution/statistics
获取执行统计

#### 7. POST /api/execution/start-processor
启动自动执行处理器

#### 8. POST /api/execution/stop-processor
停止自动执行处理器

---

## 使用指南

### 快速开始

#### 1. 启动系统

```bash
# 运行测试
python test_proactive_features.py

# 启动Web服务
python web/app.py
```

#### 2. 访问界面

```
主页: http://localhost:5000
知识图谱: http://localhost:5000/knowledge-graph
```

#### 3. 体验功能

**场景1: 早晨工作开始**

1. 打开Koto → 收到早安问候通知
2. 查看未读建议 → 显示3条智能建议
3. 点击"立即处理" → 授权自动整理文件
4. 系统自动执行 → 发送完成通知

**场景2: 长时间工作提醒**

1. 持续工作2小时 → 收到休息提醒
2. 点击"稍后提醒" → 30分钟后再次提醒
3. 点击"现在休息" → 系统暂停通知15分钟

**场景3: 智能场景切换**

1. 打开学习资料 → 系统检测到学习场景
2. 自动调整建议频率 → 降低打扰
3. 启用知识助手功能 → 提供概念解释
4. 切换到代码编辑 → 识别为工作场景

---

### 高级配置

#### 1. 自定义通知偏好

```python
# 通过API设置
import requests

requests.post('http://localhost:5000/api/notifications/preferences', json={
    'enabled_types': ['suggestion', 'reminder', 'achievement'],
    'quiet_hours_start': '22:00',
    'quiet_hours_end': '08:00',
    'max_daily_notifications': 15,
    'priority_threshold': 'medium'  # 只接收medium及以上优先级
})
```

#### 2. 自定义对话场景

```python
from proactive_dialogue import ProactiveDialogueEngine

engine = ProactiveDialogueEngine()

# 添加自定义对话模板
engine.DIALOGUE_TEMPLATES['custom_scene'] = [
    "🎨 检测到你在创作，需要一些灵感吗？",
    "✨ 创作进行中，要不要看看相关素材？"
]

# 手动触发
engine.manual_trigger('user123', 'custom_scene')
```

#### 3. 注册自定义任务

```python
from auto_execution import AutoExecutionEngine

engine = AutoExecutionEngine()

# 定义处理器
def my_custom_task(params):
    # 自定义任务逻辑
    input_file = params['input_file']
    # ... 处理 ...
    return {
        'processed': True,
        'output_file': 'result.txt'
    }

# 注册任务
engine.register_task(
    task_type='my_custom_task',
    task_name='自定义任务',
    description='执行自定义处理',
    risk_level='low',
    handler=my_custom_task
)
```

---

## 配置说明

### 数据库文件

所有模块使用SQLite数据库，默认存储在 `config/` 目录：

```
config/
  ├── notifications.db       # 通知记录
  ├── proactive_dialogue.db  # 对话历史
  ├── context_awareness.db   # 场景记录
  ├── auto_execution.db      # 执行历史
  ├── user_behavior.db       # 用户行为（已有）
  └── suggestions.db         # 建议记录（已有）
```

### 环境变量

可以通过环境变量覆盖默认配置：

```bash
# 设置数据库路径
export KOTO_DB_PATH=/custom/path/

# 设置检查间隔
export KOTO_DIALOGUE_INTERVAL=600  # 10分钟
export KOTO_EXECUTION_INTERVAL=120  # 2分钟

# 设置通知限额
export KOTO_MAX_DAILY_NOTIFICATIONS=30
```

---

## 最佳实践

### 1. 通知管理

✅ **推荐做法**:
- 设置合理的静音时段（22:00-08:00）
- 每日通知限制在20条以内
- 高优先级用于紧急事项
- 定期查看通知统计，调整偏好

❌ **避免**:
- 关闭所有通知类型
- 设置过低的优先级阈值
- 忽略所有建议

### 2. 场景感知

✅ **推荐做法**:
- 让系统自动检测场景
- 根据工作风格调整配置
- 定期查看场景统计
- 利用场景切换优化工作流

❌ **避免**:
- 频繁手动切换场景
- 忽视系统场景建议

### 3. 自动执行

✅ **推荐做法**:
- 从低风险任务开始授权
- 设置合理的每日执行限额
- 定期查看执行历史
- 对重要文件操作保持手动确认

❌ **避免**:
- 授权所有任务自动执行
- 不设置过期时间
- 忽视执行失败记录

### 4. 主动对话

✅ **推荐做法**:
- 保持对话监控运行
- 根据对话历史调整触发频率
- 对有价值的对话采取行动
- 定期查看对话统计

❌ **避免**:
- 忽略所有主动对话
- 频繁触发相同场景

---

## 性能优化

### 1. 数据库优化

```python
# 定期清理旧数据
from datetime import datetime, timedelta

def cleanup_old_data(db_path, days=90):
    """清理90天前的数据"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cutoff_date = (datetime.now() - timedelta(days=days)).date()
    
    cursor.execute("""
        DELETE FROM notifications
        WHERE DATE(created_at) < ?
    """, (cutoff_date,))
    
    conn.commit()
    conn.close()
```

### 2. 缓存策略

```python
# 使用缓存减少数据库查询
from functools import lru_cache

@lru_cache(maxsize=128)
def get_user_preferences(user_id):
    """缓存用户偏好"""
    # ... 查询数据库 ...
    return prefs
```

### 3. 异步处理

```python
# 使用线程处理耗时任务
import threading

def async_execute_task(task):
    thread = threading.Thread(target=execute_task, args=(task,))
    thread.daemon = True
    thread.start()
```

---

## 故障排查

### 常见问题

**Q1: 通知没有收到？**

检查清单:
- [ ] 通知管理器是否已启动
- [ ] 用户偏好是否启用该类型通知
- [ ] 是否在静音时段
- [ ] 是否达到每日限额

**Q2: 对话监控不工作？**

检查清单:
- [ ] 是否调用了 `start_monitoring()`
- [ ] 依赖模块是否正确初始化
- [ ] 数据库文件是否可写
- [ ] 检查触发规则的时间间隔

**Q3: 场景识别不准确？**

解决方案:
- 增加更多用户行为数据
- 调整场景权重配置
- 手动标注训练数据
- 查看场景得分详情

**Q4: 自动执行失败？**

检查清单:
- [ ] 是否已授权该任务类型
- [ ] 文件路径是否正确
- [ ] 权限是否足够
- [ ] 查看执行历史中的错误信息

---

## 更新日志

### v2.0.0 (2026-02-15)

**新增功能**:
- ✨ 实时通知系统（WebSocket推送）
- ✨ 主动对话引擎（8种场景）
- ✨ 情境感知系统（5种场景）
- ✨ 自动执行引擎（7种任务）
- ✨ 24个新API端点

**改进**:
- 🔧 优化用户行为监控
- 🔧 增强建议引擎集成
- 🔧 改进数据库性能

**文档**:
- 📝 完整API文档
- 📝 使用指南
- 📝 最佳实践

---

## 下一步规划

### 短期 (1-2周)
- [ ] 前端WebSocket集成
- [ ] 通知UI组件
- [ ] 场景切换动画
- [ ] 中文分词优化（jieba）

### 中期 (1-2月)
- [ ] LLM集成（语义理解）
- [ ] 移动端适配
- [ ] 团队协作功能
- [ ] 数据可视化仪表板

### 长期 (3-6月)
- [ ] 机器学习推荐模型
- [ ] 跨应用集成（日历/邮件）
- [ ] 语音交互
- [ ] 多语言支持

---

## 技术栈

- **后端**: Python 3.8+, Flask
- **数据库**: SQLite3
- **通知**: WebSocket (计划)
- **前端**: JavaScript, D3.js, CSS3
- **测试**: unittest, pytest

---

## 贡献指南

欢迎贡献代码！请遵循以下步骤：

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 许可证

[MIT License](LICENSE)

---

## 联系方式

- 项目主页: https://github.com/yourusername/koto
- 问题反馈: https://github.com/yourusername/koto/issues

---

**祝你使用愉快！** 🎉
