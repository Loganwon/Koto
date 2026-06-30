# Koto 启动器使用说明

## 推荐入口

Koto 现在只有一个产品入口：统一桌面入口。

日常使用请双击：

```text
Koto_Start.vbs
```

这个入口会调用 `Koto_Start.ps1 -Mode desktop`，启动 `src/koto_app.py`，并在桌面窗口里加载统一前端 `/`。文件工作台、AI 对话、历史会话、Skills、设置和白盒任务流程都在同一套界面内运行。

## 备用入口

如果需要在控制台里看到启动日志，可以运行：

```bat
Koto_Start.bat
```

如果需要手动指定模式：

```bat
Koto_Start.bat desktop
Koto_Start.bat server
```

`server` 只用于开发调试，会用浏览器访问统一前端 `/`。它不是第二套产品入口。

历史参数 `silent` 仍被接受，但会自动归一化为 `desktop`：

```bat
Koto_Start.bat silent
```

## 启动链路

```text
Koto_Start.vbs / Koto_Start.bat
  -> Koto_Start.ps1
  -> src/koto_app.py
  -> web.app:app
  -> /
```

兼容地址 `/workspace-assistant` 会重定向到 `/`，不再作为独立页面维护。

## 日志

常用日志位置：

```text
logs/launcher.log
logs/runtime_YYYYMMDD.log
logs/server_latest_err.log
```

## 常见问题

如果双击没有反应，先检查 `logs/launcher.log`。

如果端口被占用，启动器会尝试备用端口，并把最终端口写入日志。

如果要完全退出，可以关闭 Koto 窗口，或运行：

```bat
Stop_Koto.bat
```
