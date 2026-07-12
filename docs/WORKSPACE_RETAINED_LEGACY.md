# Removed legacy workspace frontend

Koto has one product shell: `/`, rendered by `web/templates/index.html` and
implemented from `web/src/` TypeScript source. The browser loads the generated
`web/static/js/build/workspace-bundle.js` asset.

Do not restore these removed files as compatibility shims:

| Removed path | Current source owner |
| --- | --- |
| `web/src/workspace/ (已迁移至模块化工作区)` | `web/src/workspace/*` modules, bundled by `web/src/bundles/workspace.ts` |
| `web/static/js/workspace-ai-task.js` | `web/src/workspace/task-runner.ts` and `task-dispatcher.ts` |
| `web/static/js/workspace-ai-task-refresh.js` | `web/src/workspace/task-refresh.ts` |
| `web/static/js/workspace-ai-transport.js` | `web/src/workspace/transport.ts` |
| `web/static/js/workspace-ai-results.js` | `web/src/workspace/results.ts` and `task-final-report.ts` |
| `web/static/js/workspace-ai-quick-actions.js` | `web/src/workspace/quick-actions.ts` |
| `web/static/js/workspace-ai-conversation.js` | `web/src/workspace/conversation.ts` |
| `web/static/js/workspace-task-dispatcher.js` | `web/src/workspace/task-dispatcher.ts` |
| `web/static/js/workspace-task-workbench.js` | `web/src/workspace/task-workbench.ts` |
| `web/templates/workspace_assistant.html` | `web/templates/index.html` |

`web/blueprints/workspace_assistant.py` is an active API module despite its
legacy name. `/workspace-assistant` is a compatibility redirect to `/`, not a
second rendered shell.

New frontend contracts must cite `web/src/` and test the generated bundle only
as a build artifact. See [ARCHITECTURE.md](ARCHITECTURE.md) for current
ownership.
