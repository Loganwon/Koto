# 🎯 Koto Phase 2 使用指南

## 什么是智能上下文注入？

当你提问时，Koto 现在能够：
1. **理解你的意图** → 识别你在问什么类型的问题
2. **选择相关信息** → 只收集需要的系统信息  
3. **动态注入上下文** → 将相关信息注入到系统指令中
4. **更精准回答** → 根据你的实际环境给出建议

---

## 🎯 问题识别示例

### 例 1：代码执行 ❌→ ✅

**你问**: "帮我运行个脚本"

**Koto 识别**: 这是 **代码执行** 问题

**自动收集**:
- ✅ 工作目录
- ✅ 磁盘空间  
- ✅ CPU/内存使用情况
- ✅ Python 版本和已安装包

**Koto 能说**:
- "你的 Python 3.11.9 环境很好，已装 180 个包"
- "当前 CPU 只用 17%，内存还有 32GB 可用，足够运行"
- "工作目录在 `C:\Users\...\Koto`，磁盘还有 1.3TB 空间"

---

### 例 2：系统诊断 ❌→ ✅

**你问**: "电脑最近很卡，怎么回事？"

**Koto 识别**: 这是 **系统诊断** 问题

**自动收集**:
- ✅ CPU/内存使用情况
- ✅ 最耗资源的进程
- ✅ 磁盘使用情况
- ✅ 系统警告信息

**Koto 能说**:
- "当前 CPU 使用 47%（正常范围）"
- "内存使用 60%，还有 25GB 可用（还好）"
- "最耗资源的应用是：Chrome 使用 18%、VS Code 使用 8%"
- "⚠️ C 盘容量 75% 满，建议清理一下"

---

### 例 3：文件操作 ❌→ ✅

**你问**: "最大的文件在哪？"

**Koto 识别**: 这是 **文件操作** 问题

**自动收集**:
- ✅ 工作目录
- ✅ 磁盘信息
- ✅ 文件系统状态

**Koto 能说**:
- "当前工作目录: `C:\Users\...\Koto`"
- "磁盘空间充足（还有 1.3TB）"
- "可以放心创建和移动文件"

---

## 📊 后台如何工作

### 1. 问题分类 (QuestionClassifier)

```
用户问题
  ↓
关键词匹配 (快速筛选)
  + 
正则表达式匹配 (精确识别)
  ↓
任务类型 (7 种)
```

**7 种任务类型**:
- 代码执行 (CODE_EXECUTION)
- 文件操作 (FILE_OPERATION)
- 应用推荐 (APP_RECOMMENDATION)
- 系统诊断 (SYSTEM_DIAGNOSIS)
- 系统管理 (SYSTEM_MANAGEMENT)
- 学习讲解 (LEARNING)
- 通用问题 (GENERAL)

### 2. 上下文选择 (ContextSelector)

```
任务类型 (code_execution)
  ↓
映射表 (预定义的对应关系)
  ↓
选择上下文类型 (working_dir, disk, cpu_memory, python_env)
```

**10 种可用上下文**:
- 📅 时间信息 (TIME)
- 📊 CPU/内存状态 (CPU_MEMORY)
- 💿 磁盘信息 (DISK)
- 🚀 进程信息 (PROCESSES)
- 🐍 Python 环境 (PYTHON_ENV)
- 💻 已安装应用 (INSTALLED_APPS)
- 📁 工作目录 (WORKING_DIR)
- 📂 文件系统 (FILESYSTEM)
- 🌐 网络状态 (NETWORK)
- ⚠️ 系统警告 (WARNINGS)

### 3. 上下文构建 (ContextBuilder)

```
选中的上下文类型
  ↓
收集系统实时信息 (psutil, os module...)
  ↓
格式化为 Markdown
  ↓
合并到系统指令
```

**例**:
```markdown
## 📊 CPU & 内存状态
- **CPU 使用率**: 17.5%（32 核）
- **内存**: 31.0GB / 63.8GB（48.5%）
- **可用内存**: 32.8GB
```

### 4. 系统指令注入 (ContextInjector)

```
用户问题  
  ↓
分类 + 上下文选择 + 构建
  ↓
生成新的系统指令 (动态，包含实时数据)
  ↓
发送给 AI 模型
```

**结果**: 模型获得完整的上下文，能给出更精准的建议

---

## ⚡ 性能

| 操作 | 耗时 |
|------|------|
| 首次生成系统指令 | 101.7ms |
| 第二次生成（缓存） | 0.5ms |
| 加速比 | 203x |

**缓存策略**: 5-30 秒 TTL（Time To Live），确保信息足够新鲜

---

## 🔧 技术细节

### 问题分类的工作原理

```python
# 简单关键词（快速筛选）
simple_keywords = {
    CODE_EXECUTION: ['运行', '脚本', 'python', '代码', ...],
    FILE_OPERATION: ['文件', '目录', '查', '找', ...],
    ...
}

# 复杂正则特征（高精度）
regex_keywords = {
    CODE_EXECUTION: [
        r'(运行|执行).*?(脚本|代码|program)',  # 100% 置信
        r'需要.*?(包|库|pip)',                  # 200% 分数权重
        ...
    ],
    ...
}

# 匹配得分
score = simple_keyword_count * 1 + regex_match_count * 2
confidence = min(score / 5.0, 1.0)  # 最多 100%
```

### 上下文映射表

```python
task_contexts = {
    CODE_EXECUTION: [
        PYTHON_ENV,    # Python 版本、虚拟环境、包
        CPU_MEMORY,    # 是否有足够资源运行
        DISK,          # 磁盘空间
        WORKING_DIR,   # 脚本在哪里
    ],
    
    SYSTEM_DIAGNOSIS: [
        CPU_MEMORY,    # 关键诊断指标
        DISK,          # 磁盘可能是瓶颈
        PROCESSES,     # 什么进程占用资源
        WARNINGS,      # 自动警告
    ],
    
    # ... 等等
}
```

---

## 🚀 启用和使用

### Phase 2 自动启用！

无需任何配置，智能上下文注入已经内置在 Koto 中。

### 查看效果

**方式 1: 直接提问**
```
"帮我运行 Python 脚本"
→ Koto 自动分析并收集代码执行相关信息
```

**方式 2: 查看系统指令生成日志**
```python
from web.context_injector import get_dynamic_system_instruction

# 查看为某个问题生成的系统指令
instruction = get_dynamic_system_instruction("帮我运行脚本")
print(f"系统指令长度: {len(instruction)} 字符")
print(instruction)
```

**方式 3: 运行验证测试**
```bash
python test_phase2_context_injection.py
```

---

## 📈 改进的例子

### Before Phase 2

```
用户: "电脑卡，怎么办？"

Koto: "可能是 CPU 占用过高，也可能是内存不足...
      有很多可能的原因，比如...
      你可以尝试重启..."
```
❌ 泛泛而谈，没用具体数据

### After Phase 2

```
用户: "电脑卡，怎么办？"

Koto: "看一下当前状态：
     - CPU: 47%（中等占用）
     - 内存: 60% 已用，24GB 可用（充足）
     - 最耗资源: Chrome (18%) + VS Code (8%)
     - ⚠️ C盘: 75% 满！

     建议：
     1. 清理 C 盘（删除垃圾文件、缓存）
     2. Chrome 可能有问题，考虑重启
     3. 磁盘满了会严重影响系统速度"
```
✅ 针对具体情况，给出精准建议

---

## 🐛 故障排除

### 如果上下文没有被注入

1. **检查问题分类**:
   ```python
   from web.context_injector import classify_question
   task_type, confidence = classify_question("你的问题")
   print(f"分类: {task_type.value}, 置信度: {confidence:.0%}")
   ```

2. **检查上下文选择**:
   ```python
   from web.context_injector import ContextSelector, TaskType
   selector = ContextSelector()
   contexts = selector.select_contexts(task_type)
   print(f"选中的上下文: {[c.value for c in contexts]}")
   ```

3. **检查系统信息收集**:
   ```python
   from web.system_info import get_system_info_collector
   collector = get_system_info_collector()
   print(collector.get_cpu_info())
   print(collector.get_memory_info())
   ```

---

## 🎓 学习更多

- 📖 完整报告: [`PHASE2_CONTEXT_INJECTION_COMPLETE.md`](PHASE2_CONTEXT_INJECTION_COMPLETE.md)
- 🔬 源代码: [`web/context_injector.py`](web/context_injector.py) (487 行，注释完整)
- 🧪 测试脚本: [`test_phase2_context_injection.py`](test_phase2_context_injection.py)
- 🐛 调试脚本: [`debug_context_injection.py`](debug_context_injection.py)

---

## ❓ FAQ

**Q: Phase 2 会不会让 Koto 变慢？**

A: 不会。虽然首次生成系统指令需要 ~100ms，但这发生在后台，用户不会感觉到。而且有缓存加速（203x），同样问题的第二次响应几乎是瞬间。

**Q: 为什么不是把所有系统信息都注入？**

A: 因为冗杂的信息会：
- 增加模型的处理成本（更多 tokens）
- 降低回答精度（模型被无关信息干扰）
- 减缓响应速度

我们选择了"精量化"策略：只包含最相关的信息。

**Q: 可以自定义上下文映射吗？**

A: 可以！编辑 `web/context_injector.py` 中的 `task_contexts` 字典即可。

**Q: 为什么有时候分类不准？**

A: 中文NLP问题，一些问题确实比较模糊。但我们设计了多层匹配机制，在大多数情况下都能准确分类。如果发现错误模式，欢迎反馈！

---

🎉 **Phase 2 让 Koto 真正理解了你的意图！**

