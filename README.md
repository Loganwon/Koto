# Koto

Koto is a local AI workspace for chat, file tasks, document editing, and task
automation. The Flask application serves one unified browser/desktop shell;
the current workspace frontend is authored in TypeScript under `web/src/` and
published as the generated `web/static/js/build/workspace-bundle.js` asset.

## Download and use Koto

Download the current Windows release from the [Koto Releases page](https://github.com/Loganwon/Koto/releases/latest).
Choose the installer for a normal Windows setup, or the portable ZIP if you
prefer to keep Koto in a self-contained folder. Start with the
[user guide](docs/USER_GUIDE.md) for the first-run checklist and example
prompts. If something does not work, use [support and feedback](docs/SUPPORT.md)
before sharing logs or screenshots.

## Start here

Use the [current documentation index](docs/DOCUMENTATION_INDEX.md). It is the
only entrypoint for the supported startup, test, architecture, and release
guides:

- [Quick start](docs/QUICKSTART.md)
- [User guide](docs/USER_GUIDE.md)
- [Support and feedback](docs/SUPPORT.md)
- [Python and frontend test environment](docs/PYTHON_TEST_ENV.md)
- [Architecture and active ownership](docs/ARCHITECTURE.md)
- [Architecture debt and cleanup roadmap](docs/KOTO_CODE_DEBT_REPORT.md)
- [AI assistant test lanes](docs/ai-assistant-testing.md)
- [Release gate](docs/RELEASE_GATE.md)

## Local development

Requirements: Python 3.11+, Node.js for frontend checks/builds, and Windows for
the desktop packaging workflow.

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r config\requirements.txt
Copy-Item config\deepseek_config.env.example config\deepseek_config.env
# Edit config\deepseek_config.env and set DEEPSEEK_API_KEY.
```

Start the web server with the repository virtual environment:

```powershell
.\start_koto.bat
# Equivalent: .\.venv\Scripts\python.exe -m web.app
```

For the desktop launcher use `Koto_Start.vbs` or `Koto_Start.ps1`; the launcher
owns desktop/server mode selection and logs startup failures under `logs/`.

## Repository layout

```text
launcher/                 Bootstrap and frozen-app entry support
web/app.py                Flask app factory and compatibility assembly
web/blueprints/           HTTP route modules
web/services/             Web-facing orchestration
app/core/                 Domain logic, agents, LLMs, skills, and file services
web/src/                  TypeScript source for the unified frontend
src/                      Desktop and release packaging support
tests/                    Unit, integration, E2E, installer, and release tests
```

Historical reports remain in `docs/` for traceability, but they are not current
implementation guides and are not part of the entrypoint above.
