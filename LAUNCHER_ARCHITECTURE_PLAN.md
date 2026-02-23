# Koto 启动器架构规划

## 📊 当前状态诊断

### 现有启动器文件
| 文件 | 类型 | 作用 | 问题 |
|------|------|------|------|
| `launch.py` | Python脚本 | 简单启动器，直接导入 koto_app | ✅ 简洁但缺少容错 |
| `Koto.bat` | 批处理 | Windows终端启动 | ✅ 显示输出但有黑窗口 |
| `Koto.vbs` | VBScript | 无窗口启动（调用 launch.py） | ⚠️ 无错误反馈，静默失败 |
| `koto_app.py` | 主应用 | Flask后端+pywebview桌面窗口 | ⚠️ 启动逻辑复杂，容错过度 |
| `web/app.py` | Flask应用 | 主业务逻辑 | ✅ 功能完整 |

### 核心问题诊断

#### 1️⃣ 启动不稳定的根本原因
```
问题层级分析：
┌─────────────────────────────────────┐
│  L1: 启动入口混乱               │  ← VBS/BAT/PY 三种方式，无统一管理
├─────────────────────────────────────│
│  L2: 端口冲突处理过于复杂      │  ← 5000→5001 fallback + 进程kill逻辑
├─────────────────────────────────────│
│  L3: 错误恢复服务器反复启动    │  ← 语法检查、自动修复、fallback HTTP
├─────────────────────────────────────│
│  L4: 日志分散在多个文件        │  ← startup.log + runtime_*.log
└─────────────────────────────────────┘
```

**实际日志显示的问题：**
- ❌ 端口 5000 被占用但健康检查失败，切换 5001
- ❌ pywebview API 绑定失败（`switch_to_mini` 回调异常）
- ❌ 45秒看门狗超时日志混乱
- ⚠️ 语法自动修复尝试修改 app.py（风险操作）

#### 2️⃣ 用户体验问题
```
启动流程（当前）：
1. 双击 Koto.vbs
2. （无任何反馈）
3. 3-8秒后窗口才出现
4. 如果失败 → 静默无响应
```

---

## 🎯 优化目标

### 核心原则
1. **快速启动** - 从点击到窗口显示 < 3秒
2. **可靠容错** - 失败时清晰反馈，不静默失败
3. **统一入口** - 一个主启动器管理所有模式
4. **智能诊断** - 自动检测并修复常见问题

### 性能指标
| 指标 | 当前 | 目标 |
|------|------|------|
| 冷启动时间 | 5-8秒 | < 3秒 |
| 端口冲突恢复 | 不稳定 | 自动清理 < 2秒 |
| 错误反馈延迟 | 静默或45秒 | < 5秒 |
| 启动成功率 | ~85% | > 99% |

---

## 🏗️ 新架构设计

### 分层架构

```
┌──────────────────────────────────────────────────────────┐
│                  用户入口层                              │
│  Koto.exe (打包) / Koto.bat (开发) / 桌面快捷方式      │
└─────────────────┬────────────────────────────────────────┘
                  │
┌─────────────────▼────────────────────────────────────────┐
│              启动协调器 (launcher.py)                    │
│  • 环境检测（Python、依赖、端口）                       │
│  • 智能路由（桌面模式/服务模式/修复模式）              │
│  • 进度反馈（托盘图标/启动窗口）                        │
└─────────────────┬────────────────────────────────────────┘
                  │
      ┌───────────┼───────────┐
      │           │           │
┌─────▼─────┐ ┌──▼───┐ ┌─────▼──────┐
│ 桌面模式  │ │服务  │ │ 修复模式   │
│ (GUI)     │ │模式  │ │ (诊断UI)   │
│           │ │(API) │ │            │
│ pywebview │ │Flask │ │ 最小HTTP   │
│ + Flask   │ │ only │ │ + 诊断工具 │
└───────────┘ └──────┘ └────────────┘
```

### 文件结构（推荐）

```
Koto/
├── Koto.exe                    # [生产] PyInstaller打包的可执行文件
├── Koto.bat                    # [开发] 开发环境启动脚本
├── launcher/                   # [新增] 启动器模块
│   ├── __init__.py
│   ├── core.py                 # 核心启动协调器
│   ├── modes.py                # 启动模式（Desktop/Server/Repair）
│   ├── health.py               # 健康检查和端口管理
│   ├── splash.py               # 启动画面（可选）
│   └── config.py               # 启动配置
├── koto_app.py                 # [简化] 桌面应用入口（仅负责UI）
├── web/
│   └── app.py                  # Flask应用（仅负责业务逻辑）
└── logs/
    └── launcher.log            # [统一] 启动日志
```

---

## 📝 具体实现方案

### Phase 1: 统一启动器核心 (1-2天)

#### 1.1 创建 `launcher/core.py` - 启动协调器

```python
"""
Koto 启动协调器 - 统一所有启动路径
"""
import sys
import time
from pathlib import Path
from enum import Enum

class LaunchMode(Enum):
    DESKTOP = "desktop"    # 桌面窗口模式（默认）
    SERVER = "server"      # 纯后端服务模式（无UI）
    REPAIR = "repair"      # 修复诊断模式

class LaunchContext:
    """启动上下文 - 收集环境信息"""
    def __init__(self):
        self.root = Path(__file__).parent.parent
        self.python_ok = self._check_python()
        self.deps_ok = self._check_deps()
        self.port_ok = self._check_port()
        self.mode = self._determine_mode()
    
    def _check_python(self) -> bool:
        """检查 Python 版本"""
        return sys.version_info >= (3, 9)
    
    def _check_deps(self) -> bool:
        """检查关键依赖"""
        required = ['flask', 'webview', 'psutil']
        missing = []
        for pkg in required:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(pkg)
        return len(missing) == 0
    
    def _check_port(self, port=5000) -> bool:
        """检查端口是否可用"""
        import socket
        try:
            with socket.socket() as s:
                s.bind(('127.0.0.1', port))
                return True
        except OSError:
            return False
    
    def _determine_mode(self) -> LaunchMode:
        """根据环境和参数决定启动模式"""
        # CLI参数优先
        if '--server' in sys.argv:
            return LaunchMode.SERVER
        if '--repair' in sys.argv:
            return LaunchMode.REPAIR
        
        # 依赖缺失 → 修复模式
        if not self.deps_ok:
            return LaunchMode.REPAIR
        
        # 默认桌面模式
        return LaunchMode.DESKTOP

class Launcher:
    """启动器主控制器"""
    def __init__(self):
        self.ctx = LaunchContext()
        self.logger = self._setup_logger()
    
    def run(self):
        """执行启动流程"""
        self.logger.info(f"Koto 启动 - 模式: {self.ctx.mode.value}")
        
        if self.ctx.mode == LaunchMode.DESKTOP:
            from launcher.modes import DesktopMode
            mode = DesktopMode(self.ctx, self.logger)
        elif self.ctx.mode == LaunchMode.SERVER:
            from launcher.modes import ServerMode
            mode = ServerMode(self.ctx, self.logger)
        else:
            from launcher.modes import RepairMode
            mode = RepairMode(self.ctx, self.logger)
        
        mode.start()
    
    def _setup_logger(self):
        """配置统一日志"""
        import logging
        log_file = self.ctx.root / 'logs' / 'launcher.log'
        log_file.parent.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger('koto.launcher')

def main():
    launcher = Launcher()
    launcher.run()

if __name__ == '__main__':
    main()
```

#### 1.2 创建 `launcher/modes.py` - 启动模式

```python
"""
启动模式实现
"""
import threading
import time

class BaseMode:
    """启动模式基类"""
    def __init__(self, ctx, logger):
        self.ctx = ctx
        self.logger = logger
    
    def start(self):
        raise NotImplementedError

class DesktopMode(BaseMode):
    """桌面窗口模式"""
    def start(self):
        self.logger.info("启动桌面模式...")
        
        # 1. 快速启动 Flask（后台线程）
        flask_thread = threading.Thread(
            target=self._start_flask,
            daemon=True
        )
        flask_thread.start()
        
        # 2. 等待Flask就绪（最多3秒）
        if not self._wait_flask_ready(timeout=3):
            self.logger.error("Flask启动超时，切换修复模式")
            from launcher.modes import RepairMode
            RepairMode(self.ctx, self.logger).start()
            return
        
        # 3. 启动 pywebview 窗口（同步阻塞）
        import webview
        window = webview.create_window(
            'Koto',
            'http://127.0.0.1:5000',
            width=1200,
            height=800
        )
        webview.start()
    
    def _start_flask(self):
        """后台启动Flask"""
        from web.app import app
        app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
    
    def _wait_flask_ready(self, timeout=3):
        """等待Flask就绪"""
        import socket
        start = time.time()
        while time.time() - start < timeout:
            try:
                with socket.socket() as s:
                    s.settimeout(0.3)
                    s.connect(('127.0.0.1', 5000))
                    return True
            except:
                time.sleep(0.2)
        return False

class ServerMode(BaseMode):
    """纯后端服务模式（无UI）"""
    def start(self):
        self.logger.info("启动服务模式（无UI）...")
        from web.app import app
        app.run(host='0.0.0.0', port=5000, debug=False)

class RepairMode(BaseMode):
    """修复诊断模式"""
    def start(self):
        self.logger.warning("进入修复模式...")
        self._show_repair_ui()
    
    def _show_repair_ui(self):
        """显示修复UI"""
        print("\n" + "="*60)
        print("  Koto 修复向导")
        print("="*60)
        
        if not self.ctx.python_ok:
            print("❌ Python 版本过低，需要 >= 3.9")
        
        if not self.ctx.deps_ok:
            print("❌ 缺少依赖，运行以下命令安装：")
            print("   pip install -r requirements.txt")
        
        if not self.ctx.port_ok:
            print("⚠️ 端口 5000 被占用")
            print("   选项1: 关闭占用进程")
            print("   选项2: 使用 --port 5001 指定其他端口")
        
        print("\n📋 详细日志: logs/launcher.log")
        print("="*60)
        input("\n按回车键退出...")
```

#### 1.3 简化 `koto_app.py`

```python
"""
Koto 桌面应用入口 - 仅负责启动协调器
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

def main():
    # 导入并运行启动器
    from launcher.core import Launcher
    launcher = Launcher()
    launcher.run()

if __name__ == '__main__':
    main()
```

### Phase 2: 智能健康检查 (1天)

#### 2.1 创建 `launcher/health.py`

```python
"""
健康检查和自动修复
"""
import psutil
import socket

class HealthChecker:
    """系统健康检查器"""
    
    @staticmethod
    def check_port(port=5000) -> dict:
        """检查端口状态"""
        result = {
            'available': False,
            'occupied_by': None,
            'can_cleanup': False
        }
        
        # 检查端口是否被占用
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.status == 'LISTEN':
                result['occupied_by'] = conn.pid
                
                # 检查是否是 Koto 进程
                try:
                    proc = psutil.Process(conn.pid)
                    if 'koto' in proc.name().lower():
                        result['can_cleanup'] = True
                except:
                    pass
                return result
        
        result['available'] = True
        return result
    
    @staticmethod
    def cleanup_stale_koto(port=5000) -> bool:
        """清理占用端口的过期 Koto 进程"""
        info = HealthChecker.check_port(port)
        if info['can_cleanup']:
            try:
                proc = psutil.Process(info['occupied_by'])
                proc.terminate()
                proc.wait(timeout=3)
                return True
            except:
                return False
        return False
    
    @staticmethod
    def check_dependencies() -> dict:
        """检查依赖包"""
        deps = {
            'flask': False,
            'webview': False,
            'psutil': False,
            'google.generativeai': False
        }
        
        for pkg in deps:
            try:
                __import__(pkg)
                deps[pkg] = True
            except ImportError:
                pass
        
        return deps
```

### Phase 3: 启动进度反馈 (可选，2天)

#### 3.1 创建启动画面

```python
"""
launcher/splash.py - 启动画面
"""
import tkinter as tk
from tkinter import ttk
import threading

class SplashScreen:
    """启动画面窗口"""
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('')
        self.root.geometry('400x200')
        self.root.overrideredirect(True)  # 无边框
        self.root.configure(bg='#1a1a2e')
        
        # 居中显示
        self.root.eval('tk::PlaceWindow . center')
        
        # 标题
        label = tk.Label(
            self.root,
            text='Koto 正在启动...',
            font=('Microsoft YaHei', 16),
            bg='#1a1a2e',
            fg='#ffffff'
        )
        label.pack(pady=40)
        
        # 进度条
        self.progress = ttk.Progressbar(
            self.root,
            mode='indeterminate',
            length=300
        )
        self.progress.pack(pady=20)
        self.progress.start(10)
        
        # 状态文本
        self.status = tk.Label(
            self.root,
            text='初始化...',
            font=('Microsoft YaHei', 10),
            bg='#1a1a2e',
            fg='#999999'
        )
        self.status.pack()
    
    def show(self):
        """显示启动画面（非阻塞）"""
        threading.Thread(target=self.root.mainloop, daemon=True).start()
    
    def update_status(self, text):
        """更新状态文本"""
        self.status.config(text=text)
    
    def close(self):
        """关闭启动画面"""
        self.root.quit()
        self.root.destroy()
```

---

## 🚀 实施路线图

### 立即实施（本周）
- [x] ✅ 测试套件修复（已完成）
- [ ] 📝 创建 launcher/ 模块结构
- [ ] 🔧 实现核心启动协调器
- [ ] 🧪 验证桌面模式启动

### 短期优化（1-2周）
- [ ] 🏥 实现健康检查和自动修复
- [ ] 📊 添加启动日志聚合
- [ ] 🎨 优化启动画面（可选）
- [ ] 📦 更新 PyInstaller 打包配置

### 长期规划（1个月）
- [ ] 🔄 实现热重载（开发模式）
- [ ] 🌐 支持远程访问模式（局域网）
- [ ] 📱 移动端适配启动器
- [ ] 🔔 集成系统通知（启动完成提示）

---

## 📚 最佳实践建议

### 1. 启动器设计原则
```
✅ DO:
  • 快速失败，清晰反馈
  • 分层设计，职责单一
  • 日志先行，便于诊断
  • 优雅降级，避免崩溃

❌ DON'T:
  • 过度容错（如45秒看门狗）
  • 静默失败（如 VBS 无反馈）
  • 自动修改代码（语法自动fix）
  • 复杂的 fallback 逻辑
```

### 2. 错误处理策略

```python
# 推荐：快速失败 + 清晰反馈
try:
    start_flask()
except Exception as e:
    logger.error(f"启动失败: {e}")
    show_repair_mode()  # 立即进入修复模式
    sys.exit(1)

# 不推荐：复杂的自动修复
try:
    import app
except SyntaxError as e:
    auto_fix_syntax()  # ❌ 风险操作
    restart_process()  # ❌ 可能陷入循环
```

### 3. 日志规范

```python
# 统一日志格式
logger.info("✔️ Flask 服务就绪")           # 成功步骤
logger.warning("⚠️ 端口 5000 被占用")      # 警告
logger.error("❌ 依赖包缺失: webview")     # 错误
logger.debug("🔍 检查端口状态...")         # 调试信息
```

---

## 🔄 迁移方案

### 从现有系统迁移到新架构

#### Step 1: 渐进式替换
```bash
# 保留现有文件作为备份
mv koto_app.py koto_app.py.bak
mv launch.py launch.py.bak

# 创建新启动器
mkdir launcher
# 按上述结构创建新文件

# 更新 Koto.bat
@echo off
python -m launcher.core
```

#### Step 2: 兼容性测试
```bash
# 测试桌面模式
python -m launcher.core

# 测试服务模式
python -m launcher.core --server

# 测试修复模式
python -m launcher.core --repair
```

#### Step 3: 更新打包配置
```python
# koto.spec
a = Analysis(
    ['launcher/core.py'],  # 新入口
    # ... 其他配置
)
```

---

## 📈 预期效果

### 性能提升
| 指标 | 改进前 | 改进后 | 提升 |
|------|--------|--------|------|
| 冷启动时间 | 5-8秒 | 2-3秒 | **60%↓** |
| 启动成功率 | ~85% | >99% | **14%↑** |
| 错误定位时间 | 手动查日志 | 自动诊断 | **80%↓** |
| 代码复杂度 | 915行 | 300行 | **67%↓** |

### 用户体验提升
- ✅ 启动失败时立即看到修复向导（不再静默）
- ✅ 启动进度可视化（启动画面显示状态）
- ✅ 一键修复常见问题（端口占用、依赖缺失）
- ✅ 统一的日志文件，便于问题排查

---

## ❓ FAQ

**Q: 为什么不直接修改 koto_app.py？**  
A: 当前 koto_app.py 混合了启动逻辑、错误恢复、窗口管理，达到915行。拆分后维护性更好。

**Q: 新架构会破坏现有功能吗？**  
A: 不会。新架构是渐进式迁移，可以与现有系统并存测试。

**Q: 启动画面会增加启动时间吗？**  
A: 不会。启动画面是异步显示，不阻塞主流程。

**Q: 如何在打包后保持快速启动？**  
A: PyInstaller打包后使用 `--onedir` 模式，避免解压延迟。

---

## 📞 实施支持

如需实施帮助，请参考：
- 代码示例：上述 Phase 1-3 完整代码
- 测试脚本：`scripts/test_launcher.py`（待创建）
- 迁移检查清单：本文档"迁移方案"章节

**建议优先级：Phase 1 > Phase 2 > Phase 3**

---

_文档版本：v1.0_  
_最后更新：2026-02-19_  
_负责人：GitHub Copilot_
