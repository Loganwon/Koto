# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.6.2] — 2026-03-22

### Added
- **PPTX/PPTM/PPT file reading** (`web/file_parser.py`): `FileParser` now extracts text from PowerPoint presentations via `python-pptx`, including slide content and speaker notes. Slides are labeled `[第 N 页]` and notes `[第 N 页·备注]`.
- **DOC_ANNOTATE ↔ Skill injection** (`web/document_feedback.py`, `web/app.py`): `full_annotation_loop_streaming()` now accepts a `skill_prompt` parameter. Both the chat-stream and file-upload annotation paths look up the active annotation skill (`annotate_business`, `annotate_academic`, `annotate_translation`, `annotate_code_review`) via `SkillTriggerBinding` and prepend its domain-specific review dimensions into the annotation prompt, replacing the previous generic persona.

### Fixed
- **Office binary hallucinations** (`web/app.py` → `generate_file_analysis_stream`): Non-PDF binary documents (DOCX, PPTX, XLSX) are no longer sent as raw bytes to Gemini (which cannot parse them natively and hallucinates). They are now routed through `FileParser.parse_file()` and injected as text context. PDF files continue to use `Part.from_bytes()` for native vision analysis.
- **Merge conflict in `annotate_academic.json`**: Resolved leftover `<<<<<<< HEAD` / `=======` / `>>>>>>>` conflict markers; kept the `review/pr-20260321` version with `enabled: true`, `bound_tools: ["read_docx_paragraphs", "annotate_document", "write_file"]`.

### Tests
- `tests/unit/test_pr_20260322b.py`: **17 passed** (PPTX extraction, skill injection, Office binary routing, skill metadata)

---

## [1.6.1] — 2026-03-22

### Added
- **Skill Community page**: new community UI assets and template (`web/static/css/skill_community.css`, `web/static/js/skill_community.js`, `web/templates/skill_community.html`)
- **Launcher package marker**: added `launcher/__init__.py` for packaging/runtime compatibility

### Changed
- **Landing page refresh** (`web/templates/landing.html`): updated messaging and visual layout to emphasize local-first workflow and Skill Marketplace
- **Skill Marketplace API/UI updates** (`app/api/skill_marketplace_routes.py`, `web/templates/skill_marketplace.html`, `web/static/js/skill_marketplace.js`)
- **Setup wizard UX** (`src/koto_setup.py`): expanded window height and added activation-code entry path
- **Packaging updates** (`koto.spec`, `Build_Release.ps1`): improved web submodule data collection and hidden imports for release build stability

### Fixed
- **Web blueprint packaging gaps**: include `web.blueprints.*` and `web.routes.*` modules in build inputs to avoid missing dynamic imports in packaged app

### Tests
- `tests/test_error_handling.py`: **17 passed**

---

## [1.6.0] — 2026-03-22

### Added
- **Skill Marketplace** (`app/api/skill_marketplace_routes.py`, `web/static/css/skill_marketplace.css`, `web/static/js/skill_marketplace.js`, `web/templates/skill_marketplace.html`): Full marketplace UI — browse/search/filter by category, one-click install/uninstall, star ratings, export/import flows
- **6 New Skills**: `algorithmic_art`, `frontend_design`, `internal_comms`, `mcp_builder`, `skill_creator`, `web_artifacts_builder`
- **Chat Blueprint** (`web/blueprints/chat.py`): Chat routes extracted from `web/app.py` into a dedicated Blueprint
- **LLM License File** (`app/core/llm/_license.py`): License info for LLM provider components
- **Dev Scripts**: `scripts/add_route_type_hints.py`, `scripts/remove_blueprint_routes.py`

### Changed
- **`web/app.py` refactored**: All route groups moved to blueprints; `app.py` reduced from ~6 600 lines to ~500 lines
- All blueprints updated with type annotations and improved debug/warning logging: `analytics`, `chat`, `dev`, `document`, `execution`, `file_editor`, `file_organize`, `knowledge`, `misc_api`, `pages`, `proactive`, `sessions`, `settings`, `voice`, `workspace`
- **8 Enhanced skills**: `amount_converter`, `budget_variance_analyst`, `compliance_checker`, `divination`, `financial_statement_analyst`, `invoice_extractor`, `prompt_refiner`, `track_changes_writer` — improved prompts, `output_format`, and metadata
- **Icon refresh**: new `koto_icon.svg` / `.png` / `.ico` across `src/assets/` and `web/static/assets/`
- `config/triggers.json`: updated trigger definitions

### Removed
- **Archive cleanup**: 13 obsolete files deleted from `_archive/` — `old_agents/` (4), `old_launchers/` (4), `temp_files/` (8), `unused_code/` (3), `unused_launchers/` (1), `unused_tests/` (1)

### Fixed
- `tests/test_quality_feedback.py`: corrected `result['success']` → `bool(result.get('output_path'))` (PPTGenerator returns `output_path` not `success`)

### Tests
- `hypothesis` added as dev dependency for property-based tests (`tests/unit/test_property_based.py`)

---

## [1.5.0] — Agents, LLM Providers, Hooks, Skills & Services

### Added
- **Background Agent** (`app/core/agent/background_agent.py`) — async task execution with job queue
- **Deep Research** (`app/core/agent/deep_research.py`) — multi-step research pipeline
- **MCP Adapter** (`app/core/agent/mcp_adapter.py`) — Model Context Protocol integration
- **Reasoning Budget** (`app/core/agent/reasoning_budget.py`) — token budget management
- **LangGraph Agent** (`app/core/agent/langgraph_agent.py`) — LangGraph-based agent
- **LLM Provider Factory** (`app/core/llm/provider_factory.py`) — unified routing to Gemini/OpenAI/Anthropic/Ollama
- **Anthropic Provider** (`app/core/llm/anthropic_provider.py`) — Claude models support
- **OpenAI Provider** (`app/core/llm/openai_provider.py`) — GPT models support
- **Hook Manager** (`app/core/hooks/hook_manager.py`) — lifecycle hooks from config/hooks/
- **Skill Permissions** (`app/core/skills/skill_permissions.py`) — grant/revoke/check access control
- **Context Provider** (`app/core/context/context_provider.py`) — custom context injection into prompts
- **User Tool Loader** (`app/core/tools/user_tool_loader.py`) — user-defined tools via `@koto_tool`
- **Contact Manager** (`app/core/memory/contact_manager.py`) — CRM for contacts
- **Task Planner** (`app/core/tasks/task_planner.py`) — DAG task planner with Plan/PlanStep/StepStatus
- **Morning Brief** (`app/core/services/morning_brief.py`) — scheduled daily summaries
- **Telegram Bot Routes** (`app/api/telegram_bot_routes.py`) — Blueprint at `/api/telegram`
- **MultiAgentOrchestrator**: `parallel_roles`, `preset_analysis_pipeline`, `run(timeout)`, `AgentRole.model_id`
- **TaskDecomposer**: `suggest_multiagent_preset()` maps compound tasks → multiagent preset names
- **SmartDispatcher**: stamps `context_info["multiagent_preset"]` on compound task routing
- 20+ new Skill JSON configs in `config/skills/`

### Fixed
- `skill_routes.py`: removed duplicate `get_active_ui_config` endpoint (conflict artifact)
- `document_feedback.py`: 503 errors now immediately return fallback without retry/sleep
- `multi_agent._llm_call`: re-raises exceptions instead of silently swallowing them

### Tests
- 82 new unit tests covering all new modules (`tests/unit/test_pr_20260321.py`)
- Total: **4058 tests passing**

---

## [1.4.0] — 2026-03-20

### Added
- **Telegram Bot Integration** (`web/telegram_bot.py`, 621 lines): Full Telegram Bot support with message splitting, allowed-user filtering, `get_bot_info`, and a `TELEGRAM_BOT_TOKEN`-driven singleton
- **Memory API Routes** (`web/memory_api_routes.py`, 485 lines): RESTful memory CRUD (`GET/POST /api/memories`, `DELETE /api/memories/<id>`), user profile (`/api/memory/profile`), stats (`/api/memory/stats`), personality matrix (`/api/memory/personality`), bulk import (`/api/memories/import-profile`), and batch-extract endpoints
- **Document Comparator** (`web/document_comparator.py`, 464 lines): Refactored multi-format diff engine with `compare_documents`, `compare_multiple` (N-way matrix), `build_ai_prompt`, and `compare_versions`; new `/doc-compare` UI page
- **Skill UI Extensions**: `skill-ui-extensions.css`, `skill-ui-extensions.js`, `skill-ui.js`, `tarot-picker.js` for richer skill panel interactions
- **Stress Tests** (`tests/unit/test_stress.py`, 39 tests): Concurrent load tests for TaskLedger, AIRouter cache, auth rate limiter, KnowledgeGraph, SkillPipeline, Flask request flood, large payloads, memory growth, and InterruptManager
- **PR 20260320 Tests** (`tests/unit/test_pr_20260320.py`, 36 tests): Unit tests for TelegramBot helpers, memory API routes, and DocumentComparator

### Fixed
- **TaskLedger thread safety** (`app/core/tasks/task_ledger.py`): Added `threading.RLock` to serialise all SQLite access; `check_same_thread=False` alone does not prevent concurrent-connection race conditions
- **TaskLedger API**: `count()` now accepts `source` kwarg; `list_tasks`/`count` accept `status` as either string or enum value
- **web/app.py routes restored**: Merge conflict resolution had inadvertently dropped ~3,000 lines including clipboard, email, browser, search, workspace, notes, reminders, and calendar routes — all restored

---

## [1.3.0] — 2026-03-18

### Added
- **Playwright E2E Browser Tests** (63 tests): Full UI testing suite covering page loads, session management, chat interface, skill marketplace, settings, button sweep, mobile responsive, and accessibility checks
- **API Smoke Tests** (35 tests): Comprehensive endpoint coverage for memory, macro, setup, voice, document, notebook, ops, shadow, and utility APIs
- **Mobile Responsive Tests**: Verify pages render correctly at phone (375×667, 414×896) and tablet (768×1024) viewports with overflow and clipping detection
- **Accessibility Tests**: WCAG checks for alt text, form labels, button names, heading hierarchy, tabindex, lang attribute, and landmark roles
- **Server-Only Mode** (`KOTO_SERVER_ONLY=1`): New env var to start Flask without GUI/pywebview — enables full health check testing in CI
- **Installer E2E Improvements**: File size validation, Start Menu shortcut check, reinstall/upgrade cycle test, registry cleanup verification, `/api/ping` endpoint check
- **E2E CI Pipeline Job**: Playwright tests now run automatically on push (Windows runner, informational)

### Fixed
- **deleteSession null reference bug**: Fixed `TypeError: Cannot read properties of null (reading 'outerHTML')` when deleting the current session and `welcomeScreen` element was already removed from DOM (`web/static/js/app.js`)

### Changed
- Installer E2E tests now use `RequireHealth:$true` (was `$false`) — health endpoint is actually verified in CI builds

### Added
- **Modular Blueprint Architecture**: Extracted ~206 routes from monolithic `web/app.py` into 14 Flask blueprints (sessions, analytics, proactive, execution, knowledge, file_editor, dev, voice, document, file_organize, workspace, settings, misc_api, pages)
- **Skill Pipeline**: New `skill_pipeline.py` for structured skill execution with validation, routing, and fallback
- **Skill Tool Adapter**: New `skill_tool_adapter.py` bridging skills with the agent tool registry
- **Task Classifier**: ML-based task classification for intelligent request routing
- **Smart Dispatcher**: Enhanced model dispatching with intent analysis and local planner integration
- **Model Fallback Executor**: Automatic LLM failover with circuit breaker pattern
- **Conversation Tracker**: Long-running conversation context management
- **PersonalityMatrix**: 4-layer context injection for personalized responses
- **File Converter Engine**: Multi-format document conversion endpoint
- **Annotation & Chart Vision Plugins**: New agent plugins for image annotation and chart analysis
- **Output Validator**: Security-focused output sanitization for agent responses
- **Document Planner & Feedback Loop**: Iterative document generation with quality feedback
- **Swagger/OpenAPI docs** via flasgger at `/apidocs`
- **SQLite Migration Manager**: Lightweight schema versioning
- **Custom Exception Hierarchy**: Structured error types for all Koto subsystems
- **Landing Page**: Updated marketing site with download button, feature showcase, setup tabs
- **Bilingual Support**: EN/中文 marketing page
- **3,900+ tests** (up from 467): security, concurrency, circuit breaker, caching, XSS, path traversal, integration
- Structured JSON logging via `KOTO_LOG_FORMAT=json`
- Request ID tracing: `X-Request-ID` header for log correlation
- Global Flask error handlers returning JSON `{error, status, request_id}`
- `/api/info` endpoint exposing `{version, deploy_mode, auth_enabled}`
- Dependabot config for weekly pip + GitHub Actions dependency updates
- `.pre-commit-config.yaml` with black, isort, flake8, bandit hooks
- `docker-compose.yml` for local development with volume mounts
- `Makefile` with `dev`, `test`, `lint`, `format`, `build`, `audit` targets
- `pip-audit` CVE scanning step in CI (non-blocking)
- Dependency lock file for reproducible builds

### Changed
- **web/app.py reduced from ~20,800 to ~16,100 lines** via blueprint extraction
- Default model upgraded to `gemini-3.1-pro-preview`
- AIRouter refactored: removed `set_router_model`, uses internal `_ROUTER_MODEL_CHAIN`
- `print()` replaced with `logging` across 80+ web modules
- Proactive agent persists cooldown state across restarts
- RAG service upgraded with hybrid search improvements
- Training data builder and training database updates
- CI pipeline hardened: black, isort, bandit, pytest with coverage artifacts, Docker build

### Fixed
- Thread-safe singletons for shared services
- Bounded caches preventing unbounded memory growth
- Graceful shutdown with proper resource cleanup
- Deadlock in `TrainingDB.correct_label()`
- Path traversal in `file_converter` output directory
- XSS in `showNotification` — uses `escapeHtml` on message
- XSS in `md_to_html` fallback renderer
- Module whitelist for `importlib` entry_point loading
- Sandbox path validation in annotation plugin
- Platform-specific tests properly skipped on Linux CI (9 Windows-only tests)
- isort/black formatting compliance across all source files

### Security
- JWT secret startup validation: raises `RuntimeError` in cloud mode if `KOTO_JWT_SECRET` not set
- `werkzeug.secure_filename()` applied to all file upload filenames
- CODEOWNERS, PR template, issue templates, SECURITY.md added
- Branch protection ruleset configured

---

## [1.1.0] — 2025-01-XX

### Added
- Web UI improvements: dark/light theme toggle, improved chat layout
- Skills system: auto-builder and dynamic skill loading
- Knowledge Base routing with multi-source hybrid search
- LLM provider abstraction (Gemini, OpenAI, Claude, Ollama)
- Long-term memory module with FAISS vector index
- Learning module: training data builder and DB
- Document generation endpoint
- Unit and integration test suite (467 tests, 40% coverage)
- Agent core: ToolRegistry, datetime injection
- CI pipeline: lint (flake8/black/isort/bandit), pytest with coverage artifact, Docker build check

### Changed
- Centralized logging via `app/core/logging_setup.py` (RotatingFileHandler, `KOTO_LOG_LEVEL` env)
- `DEFAULT_MODEL` extracted to `app/core/config_defaults.py` (single source of truth)
- SQLite connection pooling via `threading.local()` (eliminates cross-thread conflicts)
- AIRouter and SmartDispatcher upgraded to LRU caches (256/128 entries)
- Skill manager upgraded to O(1) builtin prompt index
- Settings write-coalescing: 2s dirty timer reduces disk I/O
- Docker: non-root `koto` user, HEALTHCHECK start-period extended to 30s
- CI coverage threshold raised to 40%

### Fixed
- `PyPDF2` duplicate removed from `requirements.txt`
- `google-generativeai` → `google-genai>=1.0.0` in `requirements_voice.txt`
- Bare `except Exception` replaced with specific error handler in `agent_routes.py`

### Security
- Bandit security scan added to CI (non-blocking, surfaces issues)
- Docker image runs as non-root user

---

## [1.0.9] — 2025-01-XX

### Added
- Initial release pipeline with PyInstaller + Inno Setup installer
- E2E installer tests

---

## [1.0.0] — 2024-XX-XX

### Added
- Initial Koto AI assistant release
- Chat interface with Gemini integration
- File upload and processing
- Voice input support
- Local model support via Ollama
