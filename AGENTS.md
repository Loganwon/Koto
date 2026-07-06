# Koto AI - Agent Guidelines

## Project Overview

Koto is an AI-powered workspace assistant with chat, file editing, document generation,
code execution, and web search capabilities. It runs as a Flask web application with a
rich browser-based UI.

## Architecture

```
entry: launcher/entry.py  →  web/app.py (Flask app factory)
                                │
         ┌──────────────────────┼──────────────────────┐
         ▼                      ▼                      ▼
   web/blueprints/        web/services/           app/core/
   (HTTP routes)          (chat_stream, etc.)     (domain logic)
```

### Key Layers

| Layer | Location | Role |
|---|---|---|
| Entry | `launcher/` | Bootstrap, health checks, frozen-app support |
| Web | `web/` | Flask app, blueprints, SSE streaming, static assets |
| Blueprints | `web/blueprints/` | 24 route modules (chat, editor_ai, workspace, etc.) |
| Services | `web/services/chat_stream/` | Chat streaming pipeline (orchestrator → handlers) |
| Core | `app/core/` | Domain logic: agent, llm, skills, routing, security |
| Agents | `app/core/agent/` | File tasks, task tools, classification, plugins |
| LLM | `app/core/llm/` | Provider wrappers (DeepSeek, Gemini, Ollama, OpenAI) |
| Desktop | `src/` | PyInstaller packaging, local model installer |

### Request Flow (Chat)

```
Browser → POST /api/chat
  → web/blueprints/chat.py : chat()
    → web/runtime_context.py : get_brain()
      → web/app.py : KotoBrain.chat()
        → app/core/llm/ : provider call
        → web/session_manager : save history
```

### Request Flow (Streaming)

```
Browser → POST /api/chat/stream
  → web/blueprints/chat.py : chat_stream()
    → web/app.py : chat_stream()
      → web/services/chat_stream/orchestrator.py : setup_chat_stream_context()
      → web/services/chat_stream/agent_handler.py : handle_agent_task()
      → web/services/chat_stream/generate/regular_handler.py : handle_regular()
      → SSE events → Browser
```

### Request Flow (File Tasks)

```
Browser → POST /api/editor/ai/task-stream
  → web/blueprints/editor_ai.py : editor_ai_task_stream()
    → web/runtime_context.py : stream_file_task_request()
      → web/file_task_stream.py : stream_file_task_request()
        → app/core/agent/file_task_runtime.py : orchestrator
        → app/core/agent/task_tools.py : tool implementations
```

## Service Locator

`web/runtime_context.py` provides a `ServiceRegistry` singleton. Prefer:

```python
from web.runtime_context import service_registry
session_mgr = service_registry.session_manager
```

Legacy `get_*()` functions (e.g., `get_brain()`, `get_session_manager()`) are wrappers
around the registry. New code should use `service_registry.<property>` directly.

## God Files (Refactor Targets)

These files exceed 1000 lines and should be split when touched:

| File | Lines | Suggested split |
|---|---|---|
| `app/core/agent/task_tools.py` | 6083 | xlsx/pdf/pptx/docx sub-modules |
| `app/core/agent/file_task_runtime.py` | 5573 | stepwise/whitebox/supervisor sub-modules |
| `web/app.py` | 3340 | KotoBrain → app/core/brain.py |
| `app/core/file/parsers/docx_parser.py` | 4125 | paragraph/table/style sub-parsers |

## Naming Conventions

- Blueprints: `web/blueprints/<name>.py`, variable `{name}_bp`
- Services: `app/core/services/<name>.py`
- LLM providers: `app/core/llm/<name>_provider.py`
- Test batches: `tests/unit/test_web_modules_batch<N>.py` (temporary during migration)

## Running

```bash
# Development
python -m web.app

# Environment
config/deepseek_config.env   # API keys (gitignored)
config/requirements.txt      # Python dependencies
```

## Migration Status

Services are being moved from `web/` root to `app/core/services/`.
The `web/` copies are backward-compatible re-export shims:

```python
# web/knowledge_base.py (shim)
from app.core.services.knowledge_base import *  # noqa
```

When importing, prefer `app.core.services.xxx` for new code.
