# 🖥️ Koto 本地集成全面提升方案

## 📊 现状分析

### ❌ 当前问题
- Koto 不知道用户的系统信息（CPU、内存、磁盘等）
- 不了解用户当前运行的应用
- 不知道文件系统的实际状态
- 成为一个孤立的 AI，而不是真正的本地助手
- 用户和 Koto 对机器的认知 **不同步**

### ✅ 目标
- Koto 能实时感知系统状态
- Koto 了解用户的应用环境
- Koto 能做出符合本地环境的建议
- **用户和 Koto 对机器的理解保持同频**

---

## 🎯 分层改进方案

### 第一层：系统信息收集 (基础)
Koto 需要实时了解的系统信息：

#### 1. 系统硬件信息
```
📊 CPU
  - 型号（Intel i7 12700K）
  - 使用率（45%）
  - 核心数（12核）
  - 温度（62°C）

🧠 内存
  - 总容量（32GB）
  - 已用（18GB）
  - 可用（14GB）
  - 使用率（56%）

💿 磁盘
  - C盘：450GB/1TB (使用45%)
  - D盘：280GB/500GB (使用56%)
  - 剩余空间告警？

🌡️ 系统
  - 系统版本（Windows 11 23H2）
  - 当前用户名
  - 主机名
  - 运行时间（15天5小时）
```

#### 2. 应用环境信息
```
🔧 已安装的关键软件
  - Python（3.11.5）
  - Node.js（20.10.0）
  - Git（2.43.0）
  - VS Code（1.86.0）
  - ...

📦 Python 环境
  - 虚拟环境激活状态
  - 已安装包数量
  - 关键依赖版本

🌐 网络
  - 联网状态
  - IP 地址
  - 代理设置
  - DNS
```

#### 3. 进程和服务信息
```
🚀 运行中的进程
  - Python（koto_app.py）
  - VS Code
  - Chrome 浏览器
  - ...

⚙️ 关键服务
  - Node.js 服务状态
  - Flask 应用状态
  - 数据库连接状态
```

#### 4. 文件系统快照
```
📁 项目结构
  - Koto 项目大小
  - 日志文件
  - 缓存大小
  - 临时文件

🔐 重要文件
  - 配置文件完整性
  - 关键路径可访问性
  - 权限设置
```

---

### 第二层：系统感知的系统指令 (强化)

#### 当前系统指令包含：
- ✅ 日期时间

#### 应该添加的内容：
```python
系统指令应该包含：

## 当前时间信息
🕒 系统时间: 2026年2月15日 周日 23:18:32

## 当前系统状态
📊 运行环境：
  - 操作系统: Windows 11 (23H2)
  - CPU使用率: 45%
  - 内存使用: 18GB/32GB (56%)
  - 磁盘剩余: C盘 550GB

🚀 当前应用：
  - VS Code (已打开)
  - Koto 应用 (运行中)
  - Chrome 浏览器 (已打开)

💻 开发环境：
  - Python 3.11.5 (当前激活)
  - Node.js 20.10.0
  - Flask 服务: http://localhost:5000

📁 项目路径：
  - 项目目录: c:\Users\12524\Desktop\Koto
  - 工作目录: c:\Users\12524\Desktop\Koto\workspace
  - 临时文件: 2.3GB (建议清理)

⚠️ 系统状况：
  - 磁盘充足
  - 网络正常
  - 内存充足（还有14GB可用）
  - CPU负载正常

## 用户上下文
  - 当前用户: 12524
  - 主机名: DESKTOP-XXXX
  - 时区: UTC+8
  - 活跃应用: 3个
```

这样 Koto 就能做出更符合本地环境的建议和反馈。

---

### 第三层：智能上下文注入 (核心)

#### 在不同场景下注入不同的系统信息

**场景 1：代码执行请求**
```
用户: "帮我运行个脚本"
Koto 应该知道:
  - 当前 Python 版本
  - 虚拟环境状态
  - 已安装的关键包
  - 磁盘空间（是否足够生成输出）
  - CPU/内存（脚本是否能运行）
```

**场景 2：文件操作**
```
用户: "帮我列出最大的文件"
Koto 应该知道:
  - 当前工作目录
  - 可用磁盘空间
  - 重要目录的位置
  - 文件系统权限
```

**场景 3：应用推荐**
```
用户: "我想编辑图片"
Koto 应该知道:
  - 系统中已安装的图片编辑工具
  - CPU/内存是否足够
  - GPU 可用性
```

**场景 4：性能诊断**
```
用户: "电脑怎么这么卡"
Koto 应该知道:
  - 当前 CPU 使用率
  - 内存使用情况
  - 哪些进程在运行
  - 磁盘 I/O 状态
  - 可以立即给出诊断
```

---

### 第四层：工具化系统访问 (便利)

#### Koto 应该能实时查询：

```python
@koto_tools
def get_system_info():
    """获取系统实时信息"""
    return {
        'cpu_usage': 45,
        'memory_usage': 56,
        'disk_info': {...},
        'processes': [...],
        'python_version': '3.11.5',
        'installed_packages': [...]
    }

@koto_tools
def get_running_apps():
    """获取当前运行的应用列表"""
    return ['VS Code', 'Chrome', 'Koto', ...]

@koto_tools
def check_file_system():
    """检查文件系统状态"""
    return {
        'workspace_size': '5.2GB',
        'cache_size': '2.3GB',
        'free_disk': '550GB',
        'important_files': [...]
    }

@koto_tools
def get_environment_info():
    """获取开发环境信息"""
    return {
        'python_version': '3.11.5',
        'virtual_env': 'active',
        'installed_packages': [...],
        'node_version': '20.10.0',
        'git_status': 'up to date'
    }
```

---

## 🏗️ 实现路线

### 阶段 1：系统信息收集模块 (Week 1)
- [ ] 创建 `SystemInfoCollector` 类
- [ ] 实现 CPU、内存、磁盘监控
- [ ] 实现进程和应用检测
- [ ] 实现网络信息收集
- [ ] 性能优化（缓存 + 定时更新）

### 阶段 2：系统感知系统指令 (Week 2)
- [ ] 修改 `_get_chat_system_instruction()` 包含系统状态
- [ ] 格式化系统信息为 Markdown
- [ ] 包含关键警告信息（磁盘满、内存不足等）
- [ ] 包含项目特定信息

### 阶段 3：智能上下文注入 (Week 3)
- [ ] 分析用户输入，判断需要什么系统信息
- [ ] 根据任务类型注入相关的系统上下文
- [ ] 在系统指令中动态包含相关信息

### 阶段 4：工具集成 (Week 4)
- [ ] 实现 `@koto_tool` 装饰器
- [ ] 将系统信息函数注册为工具
- [ ] Koto 可以在需要时调用这些工具
- [ ] 记录工具的使用情况

---

## 📝 实现细节

### SystemInfoCollector 模块架构

```python
# web/system_info.py

class SystemInfoCollector:
    """系统信息收集器"""
    
    def __init__(self):
        self.cache = {}
        self.cache_timeout = 5  # 5秒更新一次
    
    def get_cpu_info(self):
        """CPU 信息：使用率、温度、型号"""
        
    def get_memory_info(self):
        """内存信息：总数、已用、可用、百分比"""
        
    def get_disk_info(self):
        """磁盘信息：各分区大小、可用空间"""
        
    def get_running_processes(self):
        """运行中的进程：名称、PID、内存占用"""
        
    def get_network_info(self):
        """网络信息：连接状态、IP、代理"""
        
    def get_python_environment(self):
        """Python 环境：版本、虚拟环境、已安装包"""
        
    def get_system_state(self):
        """系统整体状态：摘要信息"""
        
    def get_formatted_info(self):
        """获取格式化的系统信息（用于系统指令）"""

# 使用示例
collector = SystemInfoCollector()
info = collector.get_system_state()
print(f"内存: {info['memory']['used_gb']}GB / {info['memory']['total_gb']}GB")
```

### 系统指令与系统信息的结合

```python
def _get_chat_system_instruction_with_context():
    """生成包含完整系统上下文的系统指令"""
    from datetime import datetime
    from web.system_info import SystemInfoCollector
    
    now = datetime.now()
    collector = SystemInfoCollector()
    sys_info = collector.get_formatted_info()
    
    return f"""你是 Koto (言)，一个与我的电脑深度融合的个人AI助手。

## 📅 当前时间
🕒 系统时间: {now.strftime('%Y年%m月%d日')} {weekday} {now.strftime('%H:%M:%S')}

## 💻 当前系统状态
{sys_info}

## ⚠️ 系统警告
{get_system_warnings(sys_info)}

---
请基于上述系统状态给出建议和回答。充分利用我们共有的系统信息进行判断和决策。
"""
```

---

## 🎯 预期效果

### 修复前 ❌
```
用户: "我想生成一个大文件，如果太大怎么办？"
Koto: "你可以分块生成..."
（不知道用户磁盘还有多少空间）
```

### 修复后 ✅
```
用户: "我想生成一个大文件，如果太大怎么办？"
Koto: "你可以生成。根据当前系统状态：
  - 你的 C 盘还有 550GB 空间
  - 内存还有 14GB 可用
  - 即使生成 50GB 的文件也没问题
  
我建议保存到 D 盘，因为那里空间更充足（280GB 可用）。"
（基于实际系统状况的智能建议）
```

### 根本改善
- **Koto 能理解用户的环境限制**
- **Koto 的建议更贴近现实**
- **用户和 Koto 对机器的认知同步**
- **Koto 能自动检测和警告问题**

---

## 💡 额外思考

### 为什么这很重要

1. **真正的个人助手**
   - 不是泛用 AI，而是你的专属助手
   - 理解你的具体环境

2. **更好的建议**
   - 基于真实的系统状态
   - 而不是假设和通用答案

3. **及时的预警**
   - 磁盘满了？Koto 能提醒
   - 内存不足？Koto 能建议
   - 进程出问题？Koto 能诊断

4. **自动化潜力**
   - 基于系统状态自动执行操作
   - "如果 CPU 低于 30%，那么运行..."
   - "如果磁盘剩余空间少于 10GB，那么清理..."

---

## 🔧 技术选项

### 方案 A: 轮询模式（简单）
- 每 5-10 秒更新一次系统信息
- 在系统指令中包含

### 方案 B: 事件驱动模式（高效）
- 监听系统事件
- 只在有显著变化时更新
- 更省 CPU

### 方案 C: 混合模式（平衡）
- 基础信息定期更新
- 关键信息实时查询
- 缓存热点信息

**推荐：方案 C (混合)**

---

## 📊 优先级排序

### 必须实现
1. ✅ 日期时间（已完成）
2. **CPU 和内存使用率**
3. **磁盘空间信息**
4. **Python 环境信息**
5. **当前工作目录**

### 应该实现
6. **运行中的进程**
7. **网络连接状态**
8. **系统警告和通知**
9. **应用依赖版本**

### 可选实现
10. **GPU 信息**
11. **系统事件日志**
12. **性能历史趋势**

---

## 📈 预计收益

| 指标 | 改善 |
|------|------|
| Koto 的实用性 | 50% → 90% |
| 用户信任度 | 低 → 高 |
| 建议准确性 | 常见 → 针对性 |
| 问题诊断速度 | 慢 → 快 |
| 自动化能力 | 无 → 有 |

---

**这个方向将彻底改变 Koto 的定位，从一个通用 AI 变成真正的个人助手。** 🚀
