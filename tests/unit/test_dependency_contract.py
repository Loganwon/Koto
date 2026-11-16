"""Dependency publication gates must catch clean-checkout installation gaps."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_dependency_contract as contract


def project(tmp_path: Path, requirements: str, lock: str) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    (config / "requirements.txt").write_text(requirements, encoding="utf-8")
    (config / "requirements_core.txt").write_text("# core\n", encoding="utf-8")
    (config / "requirements_desktop.txt").write_text("# desktop\n", encoding="utf-8")
    (config / "requirements.lock").write_text(lock, encoding="utf-8")
    return tmp_path


def check(root: Path, **kwargs) -> dict:
    return contract.check_contract(root, target_platforms=("linux",), **kwargs)


def codes(report: dict) -> set[str]:
    return {row["code"] for row in report["issues"]}


def test_repository_direct_runtime_contract_is_complete():
    report = contract.check_contract(Path(__file__).resolve().parents[2])
    assert report["status"] == "passed", report["issues"]
    assert report["direct_requirement_count"] > 0
    assert len(report["target_environments"]) == 3
    assert report["imports"]["status"] == "not_requested"


def test_detects_missing_openai_sdk_in_clean_install(tmp_path):
    report = check(project(tmp_path, "openai>=2.41,<3\n", "httpx==0.28.1\n"))
    assert report["status"] == "failed"
    assert "missing_lock_pin" in codes(report)
    assert report["issues"][0]["package"] == "openai"


def test_detects_logger_pin_below_supported_minimum(tmp_path):
    report = check(
        project(tmp_path, "python-json-logger>=4.1\n", "python-json-logger==4.0.0\n")
    )
    assert "lock_constraint_mismatch" in codes(report)
    assert report["issues"][0]["locked_version"] == "4.0.0"


def test_normalizes_distribution_names_and_preserves_extras(tmp_path):
    root = project(
        tmp_path,
        "Flask_WTF>=1.2\nsentry-sdk[flask]>=2\n",
        "flask-wtf==1.3.0\nsentry_sdk==2.54.0\n",
    )
    assert check(root)["status"] == "passed"


def test_inactive_direct_marker_does_not_require_linux_pin(tmp_path):
    report = check(
        project(tmp_path, 'pywin32>=305; sys_platform == "win32"\n', "# none\n")
    )
    assert report["status"] == "passed"
    assert report["active_requirement_checks"] == 0


def test_target_platform_selects_conditional_lock_versions(tmp_path):
    root = project(
        tmp_path,
        'example>=1; python_version >= "3.10"\n',
        'example==1.0; sys_platform == "win32"\n'
        'example==2.0; sys_platform == "linux"\n',
    )
    report = contract.check_contract(root, target_platforms=("win32", "linux"))
    assert report["status"] == "passed"
    assert report["active_requirement_checks"] == 2


def test_target_python_marker_is_evaluated_not_host_version(tmp_path):
    root = project(tmp_path, 'example>=1; python_version >= "3.12"\n', "# none\n")
    assert check(root, python_version="3.11")["status"] == "passed"
    assert "missing_lock_pin" in codes(check(root, python_version="3.12"))


def test_named_linux_target_uses_x64_machine_marker(tmp_path):
    root = project(tmp_path, 'example>=1; platform_machine == "x86_64"\n', "# none\n")
    report = check(root)
    assert "missing_lock_pin" in codes(report)
    assert report["target_environments"][0]["platform_machine"] == "x86_64"


def test_overlapping_lock_markers_are_ambiguous(tmp_path):
    root = project(
        tmp_path,
        "example>=1\n",
        'example==1.0\nexample==2.0; sys_platform == "linux"\n',
    )
    assert "ambiguous_lock_pin" in codes(check(root))


@pytest.mark.parametrize("lock", ["example>=1\n", "example==1.*\n"])
def test_lock_requires_an_exact_version(tmp_path, lock):
    assert "lock_requires_exact_pin" in codes(
        check(project(tmp_path, "example>=1\n", lock))
    )


def test_url_credentials_never_enter_diagnostics(tmp_path):
    root = project(
        tmp_path,
        "example @ https://user:PRIVATE_TEST_VALUE@example.invalid/example.whl\n",
        "example==1.0\n",
    )
    report = check(root)
    assert "unapproved_requirement_url" in codes(report)
    assert "PRIVATE_TEST_VALUE" not in json.dumps(report)
    assert "example.invalid" not in json.dumps(report)


def test_missing_file_is_reported_without_traceback(tmp_path):
    report = check(tmp_path)
    assert report["status"] == "failed"
    assert "unreadable_requirement_file" in codes(report)


def test_invalid_requirement_is_reported_without_source_line(tmp_path):
    report = check(
        project(tmp_path, "--extra-index-url https://PRIVATE_TEST_VALUE.invalid\n", "")
    )
    assert "invalid_requirement" in codes(report)
    assert "PRIVATE_TEST_VALUE" not in json.dumps(report)


def test_opt_in_import_failures_only_report_exception_type(tmp_path, monkeypatch):
    imported = []

    def import_module(name):
        imported.append(name)
        if name == "openai":
            raise ModuleNotFoundError("PRIVATE_TEST_EXCEPTION_DETAIL")
        return object()

    monkeypatch.setattr(contract.importlib, "import_module", import_module)
    report = check(
        project(tmp_path, "example>=1\n", "example==1.0\n"), include_imports=True
    )
    assert report["status"] == "failed"
    assert imported == list(contract.IMPORT_MODULES)
    assert report["imports"]["failures"] == [
        {"module": "openai", "error_type": "ModuleNotFoundError"}
    ]
    assert "PRIVATE_TEST_EXCEPTION_DETAIL" not in json.dumps(report)


def test_cli_json_report_and_exit_code_match(tmp_path):
    root = project(tmp_path, "example>=2\n", "example==1.0\n")
    output = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(Path(contract.__file__)),
            "--root",
            str(root),
            "--platform",
            "linux",
            "--json-output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report == json.loads(result.stdout)
    assert report["schema_version"] == 1
    assert report["status"] == "failed"
