# P3 前端运行时解耦完成报告（2026-07-19）

## 完成结论

P3 的三项兼容债务已达到删除条件并从 `config/compatibility_debt.json` 移除：

- `frontend.inline-business-handlers`
- `frontend.window-wa-bus`
- `frontend.global-editor-modules`

本阶段不包含 P5 的后端兼容入口与超大文件拆分；这些债务仍保留在账本中。

## 结果指标

| 指标 | P3 前 | P3 后 | 锁定预算 |
|---|---:|---:|---:|
| `inline_script_tags` | 11 | 2 | 2 |
| `inline_event_handlers` | 406 | 0 | 0 |
| `inline_wa_event_handlers` | 174 | 0 | 0 |
| `inline_wa_method_count` | 99 | 0 | 0 |
| `publish_workspace_api_calls` | 26 | 0 | 0 |
| `window_global_assignments` | 508 | 486 | 486 |

## 架构变化

1. 跨 bundle 业务调用统一进入 `FeatureRegistry`。注册表保存在 document 私有槽位，删除了 `workspace-api.ts` 以及 `window.WA` 的生产调用边界。
2. `index.html` 及其工作区片段中的业务事件改为 `data-koto-event-*` 路由，由 `template-event-controller.ts` 集中委派；拖拽事件也纳入同一边界。
3. 原有页面内脚本迁入 `template-runtime.ts`，入口由 app bundle 管理。仅保留必须在首次绘制前同步执行的两个启动脚本。
4. PPTX、PDF、XLSX、图片编辑器以原生 ESM 产物构建，并通过动态 `import()` 返回类型化模块，不再检查全局模块对象。
5. Skills、会话列表、查找替换、任务详情、文件右键菜单和前端观测器的懒加载桥接统一读取 FeatureRegistry 与模板 data URL。
6. TipTap 审阅/自动保存调用改读同一个注册表；启动错误队列迁入独立的 startup monitor。

## 防回归约束

- 架构预算已按 P3 实际值收紧，任一指标回升都会使审计失败。
- 单测检查所有 `data-koto-event-*` 引用都有对应控制器 handler，并禁止活动工作区模板重新出现内联事件。
- 单测检查编辑器入口保持 ESM 导出、lazy loader 使用动态 import、生产源码不再出现全局编辑器模块对象。
- FeatureRegistry、懒加载首击重放、会话/查找/任务/右键菜单桥接均有前端测试覆盖。

## 验证记录

- TypeScript 类型检查：通过。
- ESLint：通过（0 error；仓库既有 warning 不作为 P3 阻断项）。
- 生产 bundle 构建与全部 bundle 体积预算：通过。
- Vitest：49 个文件、196 个测试通过。
- P3 相关 Python 单元/集成契约：465 个通过，23 个环境型用例跳过。
- Playwright UI 原语/首击路由：5 个测试通过。
- 架构债务审计：P3 五项指标全部达到锁定值；兼容债务仅剩 3 项 P5 条目。
