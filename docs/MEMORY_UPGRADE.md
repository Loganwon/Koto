# 增强记忆系统升级文档

## 🎯 升级概述

已完成 **Phase 1: 自动提取 + 用户画像** 的实现。

## ✨ 新功能

### 1. **用户画像系统** (`UserProfile`)
自动建立和维护用户特征模型：

**包含维度：**
- 🗣️ **沟通风格**
  - 详细程度偏好（简洁/适中/详细）
  - 语言偏好
  - 正式程度（正式/随意/混合）
  - Emoji使用偏好
  - 代码风格（简洁/详细/带解释）

- 💻 **技术背景**
  - 编程语言列表
  - 经验水平（初学者/中级/高级）
  - 技术领域
  - 常用工具

- 📊 **工作模式**
  - 高频话题统计
  - 典型任务类型
  - 活跃时间

- ❤️ **个人偏好**
  - 明确喜欢的内容
  - 明确不喜欢的内容
  - 观察到的使用习惯

**存储位置：** `config/user_profile.json`

### 2. **自动记忆提取**
从对话中自动学习，无需手动添加：

**提取内容：**
- 编程语言和工具使用
- 技术领域和项目信息
- 明确表达的偏好和厌恶
- 沟通风格偏好

**触发条件（智能判断）：**
- 包含偏好信号词（喜欢、不喜欢、倾向等）
- 包含技术内容
- 较长的对话（可能包含有价值信息）
- 排除简单问候语

### 3. **增强的记忆检索**
改进的搜索算法：
- 分类加权（user_preference权重最高）
- 完全匹配优先
- 关键词匹配
- 使用计数追踪（衡量记忆重要性）

### 4. **上下文增强**
自动将用户画像和相关记忆注入LLM上下文：

```python
[用户画像]
• 回复风格：moderate详细度，casual语气
• 编程语言：Python, JavaScript
• 经验水平：intermediate
• 喜欢：简洁的代码
• 不喜欢：冗长的解释
• 常见话题：Web开发, AI

[相关记忆]
• 用户喜欢简洁的代码，不要太多注释
• 项目名称：Koto AI助手
```

## 📁 文件结构

```
app/core/services/
└── memory_manager.py             # 增强记忆管理器
web/
└── app.py                        # 主应用

config/
├── memory.json                    # 记忆存储
└── user_profile.json              # 用户画像（新）
```

## 🔌 API端点

### 获取用户画像
```http
GET /api/memory/profile
```

**响应：**
```json
{
  "success": true,
  "profile": {
    "communication_style": { ... },
    "technical_background": { ... },
    "preferences": { ... }
  },
  "summary": "intermediate级别开发者，熟悉Python/JavaScript"
}
```

### 更新用户画像
```http
POST /api/memory/profile
Content-Type: application/json

{
  "communication_style": {
    "preferred_detail_level": "brief"
  }
}
```

### 触发自动学习（测试用）
```http
POST /api/memory/auto-learn
Content-Type: application/json

{
  "user_message": "我喜欢简洁的Python代码",
  "ai_message": "好的，我会为你生成简洁的代码"
}
```

### 获取记忆统计
```http
GET /api/memory/stats
```

**响应：**
```json
{
  "success": true,
  "stats": {
    "total_memories": 15,
    "by_category": {
      "user_preference": 8,
      "project_info": 5,
      "fact": 2
    },
    "by_source": {
      "user": 10,
      "extraction": 5
    },
    "most_used": [...],
    "profile_stats": {
      "total_interactions": 42,
      "programming_languages": 3,
      "tools": 5,
      "preferences_count": 6
    }
  }
}
```

## 🧪 测试

运行测试脚本：
```bash
python app/core/services/memory_manager.py
```

## 🚀 使用方法

### 1. 自动学习（已集成，自动运行）
系统会在对话过程中自动学习用户特征。

### 2. 手动添加记忆
```python
memory_mgr = get_memory_manager()
memory_mgr.add_memory(
    "用户喜欢简洁的代码",
    category="user_preference"
)
```

### 3. 查看用户画像
在Koto界面中（未来可添加UI界面）：
- 访问 `/api/memory/profile` 查看完整画像
- 访问 `/api/memory/stats` 查看统计信息

### 4. 体验个性化回复
系统会根据你的画像自动调整：
- 回复的详细程度
- 代码风格
- 技术术语的解释深度
- 沟通语气

## 📋 下一步计划（Phase 2）

### 🔮 向量检索系统
- 集成 FAISS 或 ChromaDB
- 语义相似度匹配
- 更准确的记忆检索

### 🎨 回复风格调整器
- 根据用户画像自动调整回复
- 动态详细程度控制
- 个性化代码风格

### 🔄 主动学习
- 周期性分析对话历史
- 主动询问确认偏好
- 持续优化画像准确性

## ⚙️ 配置

在 `config/user_profile.json` 中可以手动调整画像：

```json
{
  "communication_style": {
    "preferred_detail_level": "brief",  // brief/moderate/detailed
    "formality": "casual",              // formal/casual/mixed
    "emoji_usage": true,
    "code_style": "concise"             // concise/detailed/explained
  },
  "technical_background": {
    "experience_level": "intermediate"   // beginner/intermediate/advanced
  }
}
```

## 🐛 故障排除

### 增强记忆系统未加载
检查日志输出：
```
[INIT] ✅ 增强记忆管理器已初始化   # 成功
[INIT] ⚠️  使用基础记忆管理器      # 降级到基础版
```

如果记忆服务加载失败，检查文件是否存在：
- `app/core/services/memory_manager.py`
- `web/blueprints/memory_api.py`

### API端点404
确保 `memory_api_routes.py` 被正确导入：
```
🧠 增强记忆系统API已加载      # 成功
⚠️  增强记忆系统API未找到     # 失败
```

## 📚 代码示例

### 在对话中使用
```python
# 在 app.py 的 chat_stream 函数中
memory_mgr = get_memory_manager()

# 获取增强的上下文
memory_context = memory_mgr.get_context_string(user_input)
use_instruction += f"\n\n{memory_context}"

# 对话结束后，自动学习
if hasattr(memory_mgr, 'auto_extract_from_conversation'):
    memory_mgr.auto_extract_from_conversation(
        user_input, 
        ai_response
    )
```

---

**升级完成时间:** 2026-02-13  
**版本:** Enhanced Memory v1.0 (Phase 1)  
**下一版本预计:** Phase 2 - 语义检索 🔮
