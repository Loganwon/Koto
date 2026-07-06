# Koto AI — Agent Instructions

## Project Overview
Koto is an AI-powered desktop workspace with chat, file editing, document generation, and agent orchestration. Built with Flask (Python) backend and vanilla JS frontend.

## Architecture

```
Koto/
├── web/                        # Flask web layer
│   ├── app.py                  # Main app (3340 lines — KotoBrain, chat_stream, routing)
│   ├── app_blueprints.py       # Blueprint registration + CSRF exemptions
│   ├── runtime_context.py      # ServiceRegistry singleton + backward-compat getters
│   ├── session_manager.py      # Thread-safe JSON file session store
│   ├── blueprints/             # 24 Flask blueprints (chat, editor_ai, workspace, etc.)
│   ├── services/chat_stream/   # Extracted chat stream handlers
│   ├── static/css/             # style.css (5250L) + workspace.css (11506L)
│   │   └── z-layers.css        # Z-index layer system (CSS custom properties)
│   └── static/js/build/        # Bundled JS (app-bundle, workspace-bundle, etc.)
├── app/                        # Domain logic
│   └── core/
│       ├── agent/              # Agents: task_tools (6083L), file_task_runtime (5573L)
│       ├── services/           # Migrated services (doc_gen, ppt, rag, memory, etc.)
│       ├── llm/                # LLM providers (Gemini, Ollama, DeepSeek)
│       ├── routing/            # SmartDispatcher, local model router
│       ├── skills/             # Skill system (auto-builder, matcher, manager)
│       ├── file/               # File parsers, exporters, registry
│       ├── security/           # Output validator, auth
│       └── workspace/          # Workspace management
├── src/                        # Desktop app entry (koto_app.py)
├── launcher/                   # Bootstrap/health
└── tests/                      # Tests (unit, integration, e2e)
```

## Key Patterns

### Service Registry
```python
from web.runtime_context import service_registry
brain = service_registry.brain
session_mgr = service_registry.session_manager
```
Prefer `service_registry.<prop>` over `get_*()` helpers in new code.

### Blueprint Pattern
All routes in `web/blueprints/`. Register in `web/app_blueprints.py`.
CSRF-exempt API endpoints with `_exempt_csrf_endpoint()`.

### Session Storage
Thread-safe JSON files in `app/core/chats/`. All read-modify-write ops use per-file `threading.Lock`.

### CSS Z-Index
Use variables from `z-layers.css`: `--z-dropdown`, `--z-modal-panel`, `--z-toast`, `--z-app-window`, `--z-topmost-critical`. No raw values above 2000.

## Known Debt
- `task_tools.py` (6083L) and `file_task_runtime.py` (5573L) need splitting
- 30+ `get_*()` backward-compat wrappers in runtime_context.py
- `web/` root has 107 .py files in gradual migration to `app/core/`
- No frontend test coverage
- CSS ~16,700 total lines, no automated dead-code detection

## Running
```bash
python -m web.app          # Start server on :5000
python src/koto_app.py     # Desktop app
```

## API Key Config
- `config/deepseek_config.env` (gitignored)
- `web/config/jwt_secret.txt` (gitignored)
