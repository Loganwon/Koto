# 触发器阈值可编辑功能文档

## 概述

Koto 智能助手现已支持**动态阈值参数编辑**功能。用户可以直接在触发器面板中修改每个触发器的具体阈值，而无需修改源代码。所有更改会自动保存到数据库，并在应用重启后持久化。

## 核心功能

### 1. 参数定义

每个触发器都定义了一组可配置的参数，包括：

#### 工作时长触发器 (`threshold_work_too_long`)
```python
{
    "work_duration_hours": 2,        # 触发的小时数阈值
    "urgency_per_hour": 0.1,         # 每小时增加的紧急度
    "max_urgency": 1.0               # 最大紧急度限制
}
```
- **工作时长阈值**: 默认 2 小时，超过此时长将触发休息提醒
- **紧急度递增率**: 每增加 1 小时增加 0.1 的紧急度（可调，使提醒更加及时）
- **最大紧急度**: 防止紧急度无限增长

#### 编辑次数触发器 (`threshold_edit_count`)
```python
{
    "edit_count_threshold": 10,       # 编辑次数阈值
    "check_recent_events": 100        # 检查最近多少条事件
}
```
- **编辑次数阈值**: 文件被编辑达到此次数时触发备份建议
- **检查事件数**: 从最近多少条事件中统计编辑次数

#### 搜索模式触发器 (`pattern_repeated_search`)
```python
{
    "search_threshold": 3,            # 搜索次数触发阈值
    "check_recent_searches": 50       # 检查最近搜索数
}
```
- **搜索阈值**: 重复搜索达到此次数时触发优化建议
- **检查范围**: 从最近搜索记录中查找

#### 早晨问候触发器 (`periodic_morning_greeting`)
```python
{
    "morning_start_hour": 6,          # 早晨开始时刻（小时）
    "morning_end_hour": 10            # 早晨结束时刻（小时）
}
```
- **开始时刻**: 早晨问候可能触发的最早小时数（0-23）
- **结束时刻**: 早晨问候可能触发的最晚小时数（0-23）

#### 休息后回归触发器 (`event_return_after_break`)
```python
{
    "break_timeout_hours": 4          # 超过多少小时无活动后触发
}
```

#### 场景切换触发器 (`event_context_switch`)
```python
{
    "context_change_timeout_minutes": 30  # 多少分钟内的切换视为新场景
}
```

#### 杂乱文件触发器 (`threshold_unorganized_files`)
```python
{
    "organization_suggestion_threshold": 2  # 多少条建议后触发
}
```

#### 待处理建议触发器 (`periodic_check_suggestions`)
```python
{
    "check_interval_hours": 2,        # 检查间隔（小时）
    "min_suggestions": 1              # 最少多少条建议才触发
}
```

#### 文件丢失风险触发器 (`emergency_file_loss_risk`)
```python
{
    "file_backup_timeout_hours": 24,  # 文件未备份多久后提醒
    "large_delete_threshold": 10      # 大量删除操作的文件数阈值
}
```

#### 效率下降触发器 (`pattern_efficiency_drop`)
```python
{
    "efficiency_threshold": 0.7,      # 效率下降比例阈值
    "comparison_days": 1              # 对比多少天的数据
}
```

### 2. 前端面板

#### UI 交互流程

1. **打开触发器面板**
   - 点击顶部工具栏中的"🧭 触发器"按钮
   - 显示所有已注册的触发器列表

2. **查看触发器信息**
   - 触发器 ID（唯一标识符）
   - 触发器类型（periodic/event/threshold/pattern/emergency）
   - 简短描述
   - 启用/禁用状态

3. **编辑基础配置**
   - **启用状态**: 复选框切换触发器是否活跃
   - **优先级**: 1-10 的数字，数值越大越优先触发
   - **冷却时间**: 分钟为单位，触发后需要等待多久才能再次触发

4. **编辑高级参数**
   - 点击"⚙️ 参数"按钮展开参数编辑区域
   - 每个参数显示为标签+输入框的形式
   - 支持数字、文本等多种输入类型
   - 自动识别数据类型（整数、浮点数、布尔值）

5. **保存更改**
   - 点击"保存"按钮：
     - 提交所有修改的配置和参数
     - 数据库立即存储
     - 实时生效（无需重启应用）
     - 显示成功/失败提示

#### 参数编辑示例

```
工作时长触发器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[✓] 启用  | 优先级: [8] | 冷却(分钟): [60] | [⚙️ 参数] | [保存]

[⚙️ 参数]为收起状态

点击"⚙️ 参数"展开:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┌─ 参数编辑区域
│ work_duration_hours:     [2.0]
│ urgency_per_hour:        [0.1]
│ max_urgency:             [1.0]
└─ 参数编辑区域

修改后点击"保存":
───────────────────────────────────────
1. 前端收集所有修改
2. 发送 POST /api/triggers/update
3. 后端更新数据库
4. 返回成功消息
5. 刷新列表展示最新值
```

### 3. API 接口

#### 获取触发器列表
```
GET /api/triggers/list

响应:
{
  "success": true,
  "triggers": [
    {
      "trigger_id": "threshold_work_too_long",
      "trigger_type": "threshold",
      "priority": 8,
      "cooldown_minutes": 60,
      "enabled": true,
      "threshold_value": null,
      "description": "连续工作时间超过阈值",
      "parameters": {
        "work_duration_hours": 2,
        "urgency_per_hour": 0.1,
        "max_urgency": 1.0
      }
    },
    ...
  ]
}
```

#### 更新触发器配置和参数
```
POST /api/triggers/update

请求:
{
  "trigger_id": "threshold_work_too_long",
  "enabled": true,
  "priority": 8,
  "cooldown_minutes": 60,
  "parameters": {
    "work_duration_hours": 3,
    "urgency_per_hour": 0.15,
    "max_urgency": 0.95
  }
}

响应:
{
  "success": true,
  "message": "触发器配置已更新"
}
```

#### 获取特定触发器参数
```
GET /api/triggers/params/{trigger_id}

响应:
{
  "success": true,
  "trigger_id": "threshold_work_too_long",
  "parameters": {
    "work_duration_hours": 3,
    "urgency_per_hour": 0.15,
    "max_urgency": 0.95
  }
}
```

#### 仅更新参数
```
POST /api/triggers/params/{trigger_id}

请求:
{
  "parameters": {
    "work_duration_hours": 4
  }
}

响应:
{
  "success": true,
  "message": "触发器参数已更新",
  "parameters": {
    "work_duration_hours": 4,
    "urgency_per_hour": 0.15,
    "max_urgency": 0.95
  }
}
```

### 4. 后端实现

#### 数据库结构

新增 `trigger_parameters` 表存储参数配置：

```sql
CREATE TABLE trigger_parameters (
    trigger_id TEXT PRIMARY KEY,
    parameters TEXT NOT NULL,  -- JSON格式存储
    last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trigger_id) REFERENCES trigger_config(trigger_id)
)
```

#### 核心方法

- **`get_trigger_params(trigger_id)`**: 获取触发器的所有参数
- **`update_trigger_params(trigger_id, params)`**: 更新触发器参数（保存到数据库）
- **`_load_trigger_params()`**: 从数据库加载参数配置
- **`_save_trigger_params(trigger_id, params)`**: 将参数保存到数据库

#### 触发器使用参数

所有触发条件检查函数都已更新，使用可配置参数而非硬编码值：

```python
def _check_work_duration(self, user_id: str):
    # 获取参数
    params = self.get_trigger_params("threshold_work_too_long")
    work_duration_threshold = params.get("work_duration_hours", 2)
    urgency_per_hour = params.get("urgency_per_hour", 0.1)
    max_urgency = params.get("max_urgency", 1.0)
    
    # 使用参数计算
    work_hours = ...
    if work_hours >= work_duration_threshold:
        urgency = min(0.5 + (work_hours - work_duration_threshold) * urgency_per_hour, max_urgency)
        ...
```

## 使用场景

### 场景 1: 调整工作时长阈值
**需求**: 用户通常工作 3-4 小时不休息，现有 2 小时阈值过早

**步骤**:
1. 打开触发器面板
2. 找到"threshold_work_too_long"触发器
3. 点击"⚙️ 参数"展开参数区域
4. 修改 `work_duration_hours` 为 4
5. 点击"保存"
6. 提示"触发器已更新" ✓

**结果**: 现在要工作 4 小时才会收到休息提醒

### 场景 2: 提高搜索检测灵敏度
**需求**: 只搜索 2-3 次就给出优化建议

**步骤**:
1. 找到"pattern_repeated_search"触发器
2. 点击"⚙️ 参数"
3. 修改 `search_threshold` 为 2
4. 保存

**结果**: 搜索 2 次就会触发优化提示

### 场景 3: 调整早晨问候时间
**需求**: 改为 7-9 点显示早晨问候（原为 6-10 点）

**步骤**:
1. 找到"periodic_morning_greeting"
2. 参数编辑：
   - `morning_start_hour`: 7
   - `morning_end_hour`: 9
3. 保存

**结果**: 7-9 点时才会收到早晨问候

## 技术特性

### ✅ 优势
- **无需重启**: 参数修改立即生效
- **可视化编辑**: 不用接触代码，完全 UI 操作
- **持久化存储**: 数据保存到数据库，永久有效
- **类型智能化**: 自动识别参数类型（数字、布尔等）
- **实时反馈**: 修改即时保存，状态同步
- **版本继承**: 应用更新不会重置用户设置

### 🔧 扩展性
- 易于为新触发器添加新参数
- 支持任意数据类型（数字、字符串、布尔、JSON）
- 支持参数组合修改
- UI 自动适应不同参数数量

## 测试验证

运行参数测试脚本：
```bash
python test_trigger_params.py
```

验证内容：
- ✅ 参数能否正确读取
- ✅ 参数能否成功更新
- ✅ 更新的参数能否正确保存到数据库
- ✅ 重新加载时参数能否恢复

## 故障排查

### 参数未保存
- 检查数据库连接是否正常
- 验证 `trigger_parameters` 表是否存在
- 检查触发器 ID 是否正确

### 参数修改无效
- 确保点击了"保存"按钮
- 检查浏览器控制台是否有错误
- 重新打开触发器面板，验证值是否已更新

### API 返回错误
- 检查 `/api/triggers/update` 端点是否可访问
- 验证请求 JSON 格式是否正确
- 查看应用日志获取详细错误信息

## 未来改进

1. **参数验证**: 添加参数值范围验证（如优先级 1-10）
2. **参数预设**: 提供"保守"、"平衡"、"激进"等预设配置
3. **参数历史**: 记录参数变更历史，支持回滚
4. **参数导出/导入**: 支持配置备份和恢复
5. **参数分组**: 按触发器类型分组显示参数
6. **参数说明**: 鼠标悬停显示各参数详细说明

## 相关文件

| 文件 | 功能 |
|------|------|
| `web/proactive_trigger.py` | 触发器核心逻辑（参数管理） |
| `web/app.py` | API 端点（参数更新接口） |
| `web/static/js/app.js` | 前端 JavaScript（参数编辑UI） |
| `web/static/css/style.css` | 参数编辑区域样式 |
| `web/templates/index.html` | 触发器面板 HTML |
| `test_trigger_params.py` | 参数功能测试脚本 |

---

**更新时间**: 2025年2月14日  
**功能状态**: ✅ 生产就绪
