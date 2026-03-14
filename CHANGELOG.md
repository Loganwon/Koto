# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Structured JSON logging via `KOTO_LOG_FORMAT=json` (requires `python-json-logger`)
- Request ID tracing: `X-Request-ID` header on every request/response for log correlation
- Global Flask error handlers returning JSON `{error, status, request_id}` for 404/405/500
- `/api/info` endpoint exposing `{version, deploy_mode, auth_enabled}`
- `version` field in `/api/health` and `/api/ping` responses
- Dependabot config for weekly pip + GitHub Actions dependency updates
- `.pre-commit-config.yaml` with black, isort, flake8, bandit hooks
- `docker-compose.yml` for local development with volume mounts
- `Makefile` with `dev`, `test`, `lint`, `format`, `build`, `audit` targets
- `pip-audit` CVE scanning step in CI (non-blocking)
- `CHANGELOG.md` — this file

### Security
- JWT secret startup validation: raises `RuntimeError` in cloud mode if `KOTO_JWT_SECRET` not set
- `werkzeug.secure_filename()` applied to all file upload filenames (prevents path traversal)

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
