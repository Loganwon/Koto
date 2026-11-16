# P7 启动、路由与前端通路收敛完成报告

日期：2026-07-19  
状态：完成

## 1. 目标

P7 解决“多个入口、多个注册器、多个旧页面和多个前端全局同时生效”的结构性问题。验收原则不是旧接口仍可跳转，而是退役通路不再执行、不再注册、不再由测试保活。

## 2. 完成结果

| 维度 | P7 结果 |
|---|---:|
| 桌面启动入口 | `src/koto_setup.py`，唯一 |
| 服务端启动入口 | `web/app.py`，唯一 |
| 入口 fallback | 0 |
| 兼容债务登记项 | 0 |
| 发布版路由规则 | 287 |
| 完整源码模式路由规则 | 399 |
| 重复 method + path | 0 |
| 无所有者路由族 | 0 |
| 发布版默认关闭的可选功能 | 8 |
| 浏览器全局赋值 | 4 个，全部显式批准 |
| 未批准浏览器全局 | 0 |
| TypeScript 动态 HTML 内联事件 | 0 |
| 产品模板内联事件 | 0 |
| 删除旧页面/注册 shim 文件 | 8 |

## 3. 启动与生命周期

- `config/runtime_entrypoints.json` 成为启动入口的唯一声明源。
- `launcher/bootstrap.py` 与 `Koto_Start.ps1` 都只解析声明入口；入口缺失或损坏时明确失败，不再尝试另一套生命周期。
- `web/runtime_context.py` 使用显式 `ServiceRegistry.bind_module()` 绑定应用模块，删除 `sys.modules` 多名称探测。
- 剪贴板、任务调度、任务队列和自动目录服务统一由 `web/app_runtime.py` 管理。
- `web/app_entrypoint.py` 只负责服务进程生命周期，不再启动兼容服务线程。
- 本地默认不挂载 Swagger/Prometheus；它们改为显式启用的可选观测能力，不能阻塞桌面启动。

## 4. 路由所有权与发布分层

- `web/app_blueprints.py` 改为 `BlueprintSpec` 清单驱动注册，并把注册状态放入 Flask app 自身的 `extensions`，不再使用进程级“已注册”开关。
- `config/route_ownership.json` 为 36 个路由族声明功能、层级和代码所有者。
- 冻结发布版默认只启用 core/bundled 路由；analytics、execution、goals、jobs、knowledge-base、legacy-file-api、proactive、workflow 默认关闭，可显式启用。
- 必需蓝图注册失败仍会使发布启动失败；可选蓝图失败只进入健康状态，不拖垮核心应用。
- `/api/ppt/*` 收敛为生成文件下载合同，编辑统一由 `/api/pptx` 承担。

## 5. 已退役通路

删除旧页面：文件网络、知识图谱、旧 PPT 编辑器、旧 PPTX 页面、移动端副本、文档对比页、监控静态页以及旧蓝图加载 shim。

同时移除：

- `/api/file-network/*`
- `/api/knowledge-graph/*`
- 旧 `/api/ppt/session|slide|insert|reorder|regenerate|render/*`
- `/skills`、`/skill-marketplace`、`/skill-community`、`/addon-center`
- `/mobile`、`/m`、`/doc-compare`、`/monitoring-dashboard`

这些地址按“已删除”处理并返回 404，不做重定向，以免旧链路继续被隐藏使用。

## 6. 前端运行时收敛

- 新增 `dynamic-action-controller.ts`，用 `data-koto-action` + 事件委托代替 TypeScript 生成的 `onclick/ondblclick/onmousedown` 字符串。
- 内部跨模块能力统一注册到 document-backed FeatureRegistry。
- 仅保留 4 个有原生脚本消费者或浏览器级观测职责的全局，并在审计脚本中逐项允许。
- `mini_koto.html` 收敛为外部 CSS/JS 的薄页面，不再包含内联脚本和事件。
- 动态保存文件链接对文件名做 HTML 转义，避免文件路径进入动态 HTML 时形成注入面。

## 7. 自动化门禁

- `config/p7_quality_gates.json` 固化入口、路由上限、可选功能、退役路径、全局变量和内联事件指标。
- `tests/unit/test_p7_route_convergence.py` 同时构造完整源码模式和冻结发布模式，验证路由唯一性、所有权、默认关闭策略和退役资源。
- `scripts/audit_code_baseline.py` 增加产品模板、动态 HTML 内联事件和未批准全局变量检查。

## 8. 验收记录

- P7 专属与启动/工作区/PPTX/典型用户任务跨层测试：277 项通过。
- 前端 Vitest：55 个文件、211 项通过。
- TypeScript typecheck：通过。
- 15 个生产 bundle：全部构建成功，全部满足体积预算。
- 架构债务审计：全部在预算内；兼容债务 0；未批准全局 0；动态内联事件 0。
- 仓库级 unit 测试用于最终关账，首次发现的 9 个失败均为旧架构断言，已迁移到 P7 新合同并完成定向复验。

## 9. 明确保留但不可执行的历史边界

Gemini provider 源码仍作为历史迁移/归档边界保留，但发布清单排除它，provider factory 显式拒绝它，生产模块没有导入它，前端也不暴露它。它不是可执行并行模型通路。后续若迁移完仍使用 `gemini_config.env` 命名的 Telegram/历史配置，再物理删除归档文件；该动作不应与启动收敛混在一起。

## 10. 后续阶段建议

P8 应从“结构收敛”转向“真实任务可靠性”：以真实 PDF 文本定位、水印清理、转换、长 DOCX 批注/修订加载和无本地模型启动为黄金任务，采集成功率、耗时、产物证据和失败恢复，而不是继续增加兼容入口。
