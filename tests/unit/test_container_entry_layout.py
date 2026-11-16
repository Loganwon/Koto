"""Import the real server from Docker's staged COPY layout, without host code.

Only the application boundary and provider lookup are stubbed. The server,
runtime bootstrap and configuration validator are the actual copied sources.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "config" / "deploy" / "Dockerfile"
REAL_ENTRY_FILES = {
    "src/server.py",
    "src/__init__.py",
    "src/runtime_bootstrap.py",
    "src/config_validator.py",
}
STUB_FILES = {
    "app/__init__.py": "",
    "app/core/__init__.py": "",
    "app/core/llm/__init__.py": "",
    "app/core/llm/deepseek_config.py": (
        "from pathlib import Path\n"
        "def get_deepseek_api_key():\n"
        "    Path('config/provider_checked.marker').write_text('checked', encoding='utf-8')\n"
        "    return ''\n"
    ),
    "app/core/logging_setup.py": "def setup_logging(**kwargs): pass\n",
    "web/__init__.py": "",
    "web/app.py": "app = object()\n",
}


def _instructions():
    pending = ""
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        continued = line.endswith("\\")
        pending += line[:-1] + " " if continued else line
        if continued:
            continue
        operation, _, arguments = pending.partition(" ")
        yield operation.upper(), arguments.strip()
        pending = ""


def _stage_container_layout(tmp_path, *, omitted=()):
    container = tmp_path / "container"
    selected = REAL_ENTRY_FILES | set(STUB_FILES)
    copies = {}
    environment = {}
    workdir = PurePosixPath("/")
    for operation, arguments in _instructions():
        if operation == "WORKDIR":
            workdir = (
                PurePosixPath(arguments)
                if arguments.startswith("/")
                else workdir / arguments
            )
        elif operation == "ENV":
            tokens = shlex.split(arguments)
            if all("=" in token for token in tokens):
                environment.update(token.split("=", 1) for token in tokens)
            else:
                key, _, value = arguments.partition(" ")
                environment[key] = value
        elif operation == "COPY":
            tokens = (
                json.loads(arguments)
                if arguments.startswith("[")
                else shlex.split(arguments)
            )
            while tokens and tokens[0].startswith("--"):
                option = tokens.pop(0)
                assert not option.startswith(
                    "--from"
                ), "Staged COPY needs explicit build-stage resolution"
            sources, destination = tokens[:-1], tokens[-1]
            target = (
                PurePosixPath(destination)
                if destination.startswith("/")
                else workdir / destination
            )
            for source in sources:
                host = ROOT / source
                assert host.exists(), f"Docker COPY source does not exist: {source}"
                for candidate in selected:
                    if not (ROOT / candidate).is_file():
                        continue
                    relative = Path(candidate)
                    if host.is_dir():
                        try:
                            tail = relative.relative_to(Path(source))
                        except ValueError:
                            continue
                        copied = target / tail.as_posix()
                    elif relative == Path(source):
                        is_directory = (
                            len(sources) > 1
                            or destination.endswith("/")
                            or destination in {".", ".."}
                        )
                        copied = target / relative.name if is_directory else target
                    else:
                        continue
                    copies[candidate] = container.joinpath(*copied.parts[1:])
    for source, target in copies.items():
        if source in omitted:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source in STUB_FILES:
            target.write_text(STUB_FILES[source], encoding="utf-8")
        else:
            shutil.copyfile(ROOT / source, target)
    app_root = container.joinpath(*workdir.parts[1:])
    app_root.mkdir(parents=True, exist_ok=True)
    return app_root, copies, environment


def _import_staged_server(app_root, environment, *, overrides=None):
    # -I excludes PYTHONPATH, repository cwd and user site packages. -S also
    # removes installed packages, so only the staged code and stdlib can load.
    child = r"""
import importlib, json, os, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
def result(error=None):
    server = sys.modules.get('server')
    bootstrap = sys.modules.get('src.runtime_bootstrap') or sys.modules.get('runtime_bootstrap')
    validator = sys.modules.get('src.config_validator') or sys.modules.get('config_validator')
    report = {
        'error_type': type(error).__name__ if error is not None else None,
        'missing_module': getattr(error, 'name', None),
        'app_root': str(getattr(server, 'APP_ROOT', '')),
        'cwd': str(pathlib.Path.cwd()),
        'bootstrap_file': str(getattr(bootstrap, '__file__', '')),
        'validator_file': str(getattr(validator, '__file__', '')),
        'provider_checked': (root / 'config/provider_checked.marker').is_file(),
        'application_imported': 'web.app' in sys.modules,
        'python_paths': sys.path,
    }
    print('KOTO_LAYOUT_RESULT=' + json.dumps(report))
try:
    importlib.import_module('server')
except BaseException as error:
    result(error)
    raise
else:
    result()
"""
    clean_env = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    clean_env.update(environment)
    clean_env["KOTO_JWT_SECRET"] = (
        "isolated-container-test-value-with-no-service-access"
    )
    clean_env.update(overrides or {})
    outside = app_root.parent / "outside-cwd"
    outside.mkdir(exist_ok=True)
    process = subprocess.run(
        [sys.executable, "-I", "-S", "-X", "utf8", "-c", child, str(app_root)],
        cwd=outside,
        env=clean_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    lines = [
        line
        for line in process.stdout.splitlines()
        if line.startswith("KOTO_LAYOUT_RESULT=")
    ]
    assert lines, process.stderr or process.stdout
    return process, json.loads(lines[-1].partition("=")[2])


def test_docker_copy_layout_imports_real_server_bootstrap_and_validator(tmp_path):
    app_root, copied, environment = _stage_container_layout(tmp_path)
    process, report = _import_staged_server(app_root, environment)
    assert process.returncode == 0, process.stderr or process.stdout
    assert Path(report["app_root"]) == app_root
    assert Path(report["cwd"]) == app_root
    assert Path(report["bootstrap_file"]) == copied["src/runtime_bootstrap.py"]
    assert Path(report["validator_file"]) == copied["src/config_validator.py"]
    assert report["provider_checked"] and report["application_imported"]
    assert copied["src/server.py"].read_bytes() == (ROOT / "src/server.py").read_bytes()
    assert str(ROOT) not in report["python_paths"]
    assert all(
        (app_root / name).is_dir() for name in ("logs", "chats", "workspace", "config")
    )


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"KOTO_PORT": "not-a-port"}, "KOTO_PORT must be an integer"),
        ({"KOTO_AUTH_ENABLED": "false"}, "requires KOTO_AUTH_ENABLED=true"),
        ({"KOTO_JWT_SECRET": "short"}, "requires KOTO_JWT_SECRET"),
    ],
)
def test_staged_real_validator_rejects_invalid_container_startup(
    tmp_path, overrides, reason
):
    app_root, _copied, environment = _stage_container_layout(tmp_path)
    process, report = _import_staged_server(app_root, environment, overrides=overrides)
    assert process.returncode == 1
    assert report["error_type"] == "SystemExit"
    assert report["provider_checked"]
    assert not report["application_imported"]
    assert reason in process.stdout


def test_old_missing_bootstrap_copy_fails_instead_of_importing_host_repository(
    tmp_path,
):
    omitted = REAL_ENTRY_FILES - {"src/server.py"}
    app_root, _copied, environment = _stage_container_layout(tmp_path, omitted=omitted)
    process, report = _import_staged_server(app_root, environment)
    assert process.returncode != 0
    assert report["error_type"] == "ModuleNotFoundError"
    assert report["missing_module"] in {"src", "runtime_bootstrap"}
    assert not report["provider_checked"]
    assert not report["application_imported"]
    assert str(ROOT) not in report["python_paths"]
