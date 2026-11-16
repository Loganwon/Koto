# Koto AI - Agent Guidelines

## Active Product Direction

Koto's active product is the original standalone workspace in `web/`: one
conversation and task entry with file context, live model output, observable
tool execution, document review, and verified save receipts. Continue using
the single Kernel runtime, ToolCatalog, and TaskLedger for this product.
`companion/` remains an Office / WPS compatibility adapter. Preserve its host
bindings, live selection, conflict checks, and native read/write receipts;
do not make the add-in the required entry for standalone workspace tasks.

## Project Overview

Koto is an AI-powered workspace assistant with chat, file editing, document generation,
code execution, and web search capabilities. It runs as a Flask web application with a
rich browser-based UI (TypeScript + Vue).

```text
Python: 713 source files  |  TypeScript/Vue: ~530 source files  |  Tests: 396 files
```

## Architecture

```text
entry: launcher/entry.py  →  web/app.py (Flask app factory)
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
web/blueprints/              web/services/              app/core/
(HTTP routes, 25 modules)    (chat_stream, etc.)        (domain logic)
                                    │
                         app/core/services/              app/core/agent/
                         (migrated services)             (file tasks, tools, plugins)
```

### Key Layers

| Layer | Location | Role |
|---|---|---|
| Entry | `launcher/` | Bootstrap, health checks, frozen-app support |
| Web | `web/` | Flask app, blueprints, SSE streaming, static assets, frontend (src/) |
| Blueprints | `web/blueprints/` | 25 route modules (chat, editor_ai, workspace, etc.) |
| Services | `web/services/` | Chat streaming pipeline (orchestrator → handlers) |
| Core | `app/core/` | Domain logic: agent, llm, skills, routing, security |
| Agents | `app/core/agent/` | Kernel, file-task safety contracts, tools, plugins, toolkits |
| LLM | `app/core/llm/` | Provider wrappers: DeepSeek, Gemini, Ollama, OpenAI, Anthropic |
| Desktop | `src/` | PyInstaller packaging, local model installer |
| Data | `data/` | Runtime SQLite DBs, state JSON, migration tracking artifacts |

### Request Flow (Chat)

```text
Browser → POST /api/chat
  → web/blueprints/chat.py : chat()
    → web/runtime_context.py : service_registry
      → web/app.py : KotoBrain.chat()
        → app/core/llm/ : provider call
        → web/session_manager : save history
```

### Request Flow (Streaming)

```text
Browser → POST /api/chat/stream
  → web/blueprints/chat.py : chat_stream()
    → web/app.py : chat_stream()
      → web/services/chat_stream/orchestrator.py : setup_chat_stream_context()
      → web/services/chat_stream/agent_handler.py : handle_agent_task()
      → web/services/chat_stream/generate/regular_handler.py : handle_regular()
      → SSE events → Browser
```

### Request Flow (File Tasks)

```text
Browser → POST /api/editor/ai/task-stream
  → web/blueprints/editor_ai.py : editor_ai_task_stream()
    → web/runtime_context.py : stream_file_task_request()
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

## Migration Status: web/ → app/core/services/

Service implementations live in `app/core/services/`. Do not add new
root-level `web/*.py` re-export modules.

### Core-owned services

`auto_catalog_scheduler`, `calendar_manager`, `chat_system_instruction`,
`document_batch_annotator`,
`document_direct_edit`, `document_editor`,
`document_validator`, `editor_ai_text`, `file_analyzer`,
`file_fields_extractor`, `file_organizer`, `file_scanner`,
`file_task_stream`, `folder_catalog_organizer`, `image_generator`,
`organize_cleanup`, `processed_file_network`, `reminder_manager`,
`task_queue`, `windows_notifier`

### Remaining compatibility adapters

There are no root-level `web/*.py → app.core.services` re-export adapters.
Startup, scheduling, queues, and file-task streaming import their Core owners
directly. Do not recreate a Web shim for tests or transport convenience.

## Routing Policy

- Explicit transport contracts such as `locked_task` remain authoritative.
- Unlocked chat requests enter the Kernel Agent as `AGENT`.
- Ambiguous workspace requests enter `FileTaskRuntime`; only explicit file facts
  and whitelisted system actions use deterministic fast paths.
- Do not restore keyword corpora, continuation rewriting, similarity classifiers,
  or a `SmartDispatcher`-style free-text decision layer.

### Remaining migration work

Priority targets for next migration batch:
`web/app.py`, `web/documents/file_quality_checker.py`,
`web/knowledge/knowledge_graph.py`, `web/knowledge/web_searcher.py`,
`web/files/work_file_library.py`.

The former root-level domain shims were removed. Import document, file,
knowledge, and proactive services from their package owner or from
`app.core.services` when the implementation has already moved to Core.
The former `web.tasks` root shims and the unused `web.services.intent`
keyword-classifier package were also removed; use `web.tasks.*` directly and
leave free-form task intent to the Kernel/model route.
The former calendar, chat-instruction, context, editor, file-analysis,
file-organization, image, cleanup, processed-network, and reminder root shims
were removed as well; import these services from `app.core.services`.
The keyword-based `context_injector` was removed. Chat uses one stable system
instruction; memory is injected by the canonical memory runtime and machine
state is read through explicit Agent tools only when needed.

When importing, prefer `app.core.services.xxx` for new code.

## Large Files (>1000 lines) — Refactor Candidates

| File | Lines | Status |
|---|---|---|
| `web/app.py` | 1120 | → Continue extracting KotoBrain |
| `app/core/agent/toolkits/builtin/file_tools_plugin.py` | 1157 | → Split by tool category |
| `app/core/services/ppt_generator.py` | 1450 | → Split: layout/content/theme |

## God Files — Previously Refactored (historical)

These were >1000 lines and have been successfully split:

| File | Was | Now |
|---|---|---|
| `app/core/agent/task_tools.py` | 6083L | 292L |
| `app/core/agent/file_task_runtime.py` | 5573L | 92L (Kernel adapter entry) |
| `app/core/file/parsers/docx_parser.py` | 4125L | 35L |
| `app/core/services/doc_gen_service.py` | 1205L | 118L |

### Retired implementations

Do not restore `web.code_generator`, `web.files.filegen_time_context`, or
`app.core.services.feedback_loop`, `quality_evaluator`, and `search_service`.
They had no active production consumers. Document validation and search keep
their canonical active owners; the old heuristic rewrite and retired search
shell are not compatibility APIs. See
`docs/BACKEND_LEGACY_RETIREMENT_2026-11-15.md` for reference evidence.

## Naming Conventions

- Blueprints: `web/blueprints/<name>.py`, variable `{name}_bp`
- Services: `app/core/services/<name>.py`
- LLM providers: `app/core/llm/<name>_provider.py`
- Compatibility exports: preserve existing package APIs; do not add root Web shims.

## Source publication and dependency checks

- Run `scripts/source_publish_hygiene.py` before publishing. Never publish local
  credentials, user state, developer toolchains, generated test output, or build
  packages. Excluded local files must remain intact.
- `.gitignore` does not untrack files already in an index. Review the publication
  manifest and remote tree, including deletions; do not use blind `git add -A`.
- Keep `config/requirements.lock` consistent with the direct runtime requirement
  files. `scripts/check_dependency_contract.py` checks platform markers, exact
  pins and optional imports; it does not replace a resolver or vulnerability scan.
- Frontend source changes must include rebuilt tracked production assets and
  respect existing bundle budgets. Install both `web` and `web/tiptap-editor`
  dependencies when validating their integration on a clean checkout.
- Offline engineering tests, real-model tests, browser checks and signed release
  gates are separate results. Do not report an unexecuted gate as passed.

## Directory Structure

```text
Koto/
├── launcher/          # Entry point, bootstrap
├── web/               # Flask app, blueprints, frontend
│   ├── blueprints/    # HTTP route handlers (25 modules)
│   ├── services/      # Chat streaming pipeline
│   ├── src/           # TypeScript/Vue frontend (242 files)
│   └── univer-editor/ # Spreadsheet editor (separate frontend)
├── app/
│   ├── api/           # Additional API routes
│   └── core/          # Domain logic
│       ├── agent/     # Agent system (task tools, plugins, toolkits)
│       ├── llm/       # Multi-provider LLM wrappers
│       └── services/  # Migrated service implementations
├── config/            # Configuration files (API keys, requirements)
├── data/              # Runtime data (DBs, state JSON, tracking)
│   ├── db/            # SQLite databases
│   └── migration_tracking/  # Phase migration artifacts
├── tests/             # 396 test files (unit, integration, e2e)
├── docs/              # Documentation (pruned, archive in docs/archive/)
└── dist/              # PyInstaller build output
```

## Running

```bash
# Always use the venv Python (NOT the system Python):
.venv\Scripts\python.exe -m web.app

# Or use the launcher script:
start_koto.bat
```

```bash
# Environment
config/deepseek_config.env   # API keys (gitignored)
config/requirements.txt      # Python dependencies
```
