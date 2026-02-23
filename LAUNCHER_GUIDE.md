# 🚀 Koto 启动器使用说明

## 快速启动（推荐）

### 方法 1：双击 Koto.exe ⭐⭐⭐
**最简单** - 适合所有用户

```
📁 找到 Koto.exe
👆 双击运行
✨ 自动启动桌面应用
```

**特点**：
- ✅ 无需Python环境
- ✅ 一键启动
- ✅ 独立窗口运行
- ✅ 自动处理所有依赖

---

### 方法 2：运行 RunSource.bat ⭐⭐
**推荐开发人员使用**

```
📁 找到 RunSource.bat
👆 双击运行
✨ 启动开发模式
```

**特点**：
- ✅ 使用Python虚拟环境
- ✅ 显示详细日志
- ✅ 适合调试
- ✅ 可以看到控制台输出

**要求**：
- Python 3.8+ 已安装
- 虚拟环境已配置（.venv/）

---

### 方法 3：PowerShell 脚本
**高级用户**

```powershell
# 双击运行
.\run_desktop.ps1

# 或者在PowerShell中执行
powershell -ExecutionPolicy Bypass -File run_desktop.ps1
```

---

## 启动器文件说明

| 文件 | 类型 | 用途 | 推荐场景 |
|------|------|------|----------|
| `Koto.exe` | 可执行文件 | 打包的桌面应用 | 日常使用 ⭐⭐⭐ |
| `RunSource.bat` | 批处理脚本 | 快速启动开发模式 | 开发调试 ⭐⭐ |
| `run_desktop.bat` | 批处理脚本 | 桌面版启动 | 备用方案 ⭐ |
| `run_desktop.ps1` | PowerShell脚本 | PowerShell启动 | 高级用户 ⭐ |
| `koto_app.py` | Python源码 | 主程序入口 | 源码运行 |
| `koto_desktop.py` | Python模块 | 桌面应用核心 | 被调用 |
| `launch_desktop.py` | Python模块 | 启动器模块 | 被调用 |

---

## 首次启动

### 1. 检查环境
```bash
# 检查Python版本（如果使用bat脚本）
python --version
# 应该显示 Python 3.8 或更高版本
```

### 2. 配置API密钥
```
📁 打开 config/gemini_config.env
✏️ 填入你的 Gemini API Key：
   GEMINI_API_KEY=your_api_key_here
💾 保存文件
```

### 3. 启动应用
```
👆 双击 Koto.exe
⏳ 等待几秒启动
🎉 开始使用！
```

---

## 启动流程说明

### Koto.exe 启动流程
```
1. 双击 Koto.exe
   ↓
2. 检查端口（5000/5001）
   ↓
3. 启动 Flask 后端
   ↓
4. 打开桌面窗口
   ↓
5. 加载Web界面
   ↓
6. ✅ 就绪！
```

**启动时间**：约 3-5 秒

### RunSource.bat 启动流程
```
1. 双击 RunSource.bat
   ↓
2. 激活虚拟环境 (.venv)
   ↓
3. 运行 python koto_app.py
   ↓
4. 启动 Flask 后端
   ↓
5. 打开桌面窗口
   ↓
6. ✅ 就绪！
```

**启动时间**：约 5-8 秒

---

## 常见问题

### Q1: 双击Koto.exe没反应？
**解决方案**：
1. 检查是否被杀毒软件拦截
2. 右键 → 以管理员身份运行
3. 查看 logs/ 文件夹的日志文件
4. 确认端口 5000 未被占用

### Q2: RunSource.bat 报错？
**解决方案**：
1. 确认Python已安装：`python --version`
2. 检查虚拟环境：确认 .venv/ 文件夹存在
3. 重新创建虚拟环境：
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

### Q3: 端口被占用？
**解决方案**：
1. Koto会自动尝试备用端口（5001）
2. 手动杀掉占用进程：
   ```powershell
   netstat -ano | findstr :5000
   taskkill /PID <进程ID> /F
   ```

### Q4: 如何查看日志？
**日志位置**：
- **启动日志**：`logs/startup.log`
- **运行日志**：`logs/runtime_YYYYMMDD.log`
- **错误日志**：控制台输出

### Q5: 如何完全退出？
**方法**：
1. 关闭Koto窗口
2. 后端会自动停止
3. 或者在任务管理器中结束进程

---

## 高级配置

### 自定义端口
编辑 `koto_app.py` 或 `koto_desktop.py`：
```python
KOTO_PORT = 5000  # 改为你想要的端口
```

### 日志级别
编辑配置文件，调整日志详细程度：
```python
# 在 koto_app.py 中
import logging
logging.basicConfig(level=logging.DEBUG)  # DEBUG/INFO/WARNING/ERROR
```

### 禁用自动打开浏览器
修改启动参数（如果使用源码）：
```python
# 在 koto_app.py 中
OPEN_BROWSER = False
```

---

## 性能优化

### 启动速度优化
1. **使用SSD**：将Koto安装在SSD上
2. **关闭杀毒实时扫描**：将Koto文件夹加入白名单
3. **使用Koto.exe**：比Python脚本启动更快

### 运行性能
1. **内存**：建议4GB以上可用内存
2. **网络**：稳定的网络连接（调用Gemini API）
3. **磁盘**：确保workspace/有足够空间

---

## 目录结构快速参考

```
Koto/
├── Koto.exe           ← 主启动器 ⭐
├── RunSource.bat      ← 开发启动器
├── web/               ← 核心代码
├── config/            ← 配置文件（API密钥在这里）
├── workspace/         ← 工作文件（代码、文档等）
├── models/            ← AI模型缓存
├── chats/             ← 对话历史
├── logs/              ← 日志文件（排查问题看这里）
└── archive/           ← 历史文件（不用管）
```

---

## 更新和维护

### 更新Koto
1. 备份 config/ 和 workspace/
2. 下载新版本
3. 覆盖除 config/ 和 workspace/ 外的所有文件
4. 重启应用

### 清理缓存
```powershell
# 清理Python缓存
Remove-Item -Recurse -Force web/__pycache__

# 清理日志（保留最近的）
# 手动删除 logs/ 中的旧文件

# 清理模型缓存（如需要）
Remove-Item -Recurse -Force models/*
```

---

## 🎉 开始使用

**推荐启动方式**：

1. 📂 打开 Koto 文件夹
2. 👀 找到 **Koto.exe**
3. 👆 **双击运行**
4. ⏳ 等待 3-5 秒
5. 🎊 **开始对话！**

---

### 需要帮助？

- 📖 查看 README.md - 完整功能介绍
- 📚 查看 QUICKSTART.md - 快速入门
- 📁 查看 logs/ - 排查问题
- 💬 在对话中问 Koto - AI助手随时待命

---

**祝你使用愉快！** 🚀

*Last Updated: 2026-02-12*
