# Koto quick start

This is the supported local startup path. For testing and release work, return
to the [documentation index](DOCUMENTATION_INDEX.md).

## 1. Create the environment

From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r config\requirements.txt
Copy-Item config\deepseek_config.env.example config\deepseek_config.env
```

Set `DEEPSEEK_API_KEY` in `config/deepseek_config.env`. Do not commit that
file.

## 2. Start Koto

```powershell
.\start_koto.bat
```

The script always uses `.venv\\Scripts\\python.exe` and starts `web.app`. Open
the local URL printed by Flask (normally `http://127.0.0.1:5000/`).

Equivalent development command:

```powershell
.\.venv\Scripts\python.exe -m web.app
```

For the desktop shell, launch `Koto_Start.vbs` or run:

```powershell
.\Koto_Start.ps1
```

## 3. First smoke check

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit/test_health_endpoint.py
.\.venv\Scripts\python.exe scripts\run_ai_assistant_flow_tests.py smoke -q
```

See [PYTHON_TEST_ENV.md](PYTHON_TEST_ENV.md) for the complete test setup and
[RELEASE_GATE.md](RELEASE_GATE.md) before creating a package.
