# Koto architecture

Last verified: 2026-07-12. For current run, test, and release instructions use
the [documentation index](DOCUMENTATION_INDEX.md).

## Runtime shape

```text
launcher/entry.py
  -> web/app.py (Flask app assembly)
       -> web/app_blueprints.py and web/blueprints/* (HTTP boundaries)
       -> web/services/* (web-facing orchestration)
       -> app/core/* (agents, files, LLMs, skills, domain services)

Browser / desktop shell
  -> web/templates/index.html
  -> web/src/* TypeScript source
  -> web/static/js/build/workspace-bundle.js generated runtime asset
```

## Ownership boundaries

| Boundary | Current owner | Rule |
| --- | --- | --- |
| Flask assembly and compatibility wiring | `web/app.py` | Do not add new route business logic here. |
| HTTP request/response mapping | `web/blueprints/*` | Blueprints parse requests and map domain results to HTTP/SSE. |
| Web flow orchestration | `web/services/*`, `web/file_task_stream.py` | Keep route-independent orchestration out of blueprint files. |
| File-task execution | `app/core/agent/file_task_runtime.py` plus phase helpers | Keep request, planning, execution, and finalization contracts explicit. |
| File/document operations | `app/core/file/*`, `app/core/agent/task_tools*.py` | Format-specific behavior belongs behind core boundaries. |
| Skills | `app/core/skills/*` | Read runtime skills through public `SkillManager` methods. |
| Unified frontend | `web/src/*` | TypeScript source is authoritative; the generated bundle is not a second owner. |
| Desktop/release assembly | `src/*`, `koto.spec`, `Build_Release.ps1` | Packaging changes require release-gate verification. |

## Request flows

### Chat

```text
Browser -> POST /api/chat/stream -> web/blueprints/chat.py
  -> web/app.py / web/services/chat_stream/* -> app/core/llm/*
  -> SSE -> browser
```

### File task

```text
Browser -> POST /api/editor/ai/task-stream -> web/blueprints/editor_ai.py
  -> web/runtime_context.py -> web/file_task_stream.py
  -> app/core/agent/file_task_runtime.py -> task tools
  -> SSE progress and artifacts -> browser
```

See [ARCHITECTURE_CLEANUP_ROADMAP.md](ARCHITECTURE_CLEANUP_ROADMAP.md) for
open structural work and [KOTO_CODE_DEBT_REPORT.md](KOTO_CODE_DEBT_REPORT.md)
for its current baseline.
