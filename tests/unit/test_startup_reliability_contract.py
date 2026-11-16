"""Architecture guards for Koto's provider-independent desktop startup."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _function_source(path: Path, function_name: str) -> str:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ):
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function {function_name!r} not found in {path}")


def _function_runtime_source(path: Path, function_name: str) -> str:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ):
            statements = node.body
            if (
                statements
                and isinstance(statements[0], ast.Expr)
                and isinstance(statements[0].value, ast.Constant)
                and isinstance(statements[0].value.value, str)
            ):
                statements = statements[1:]
            return "\n".join(ast.unparse(statement) for statement in statements)
    raise AssertionError(f"function {function_name!r} not found in {path}")


def test_startup_health_has_no_optional_provider_dependency() -> None:
    health_source = _function_runtime_source(
        ROOT / "web" / "routes" / "health.py", "startup_health"
    )
    forbidden = (
        "ollama",
        "local_model",
        "deepseek",
        "provider",
        "_check_disk",
        "_check_blueprint_registration",
    )

    for token in forbidden:
        assert token not in health_source.lower(), token


def test_desktop_entry_treats_provider_setup_as_nonfatal() -> None:
    main_source = _function_source(ROOT / "src" / "koto_app.py", "main")

    assert "_bootstrap_api_setup()" in main_source
    assert "Koto 将以降级模式启动" in main_source
    assert "if not _bootstrap_api_setup():\n        return" not in main_source


def test_normal_desktop_bootstrap_does_not_validate_or_open_setup() -> None:
    bootstrap_source = _function_source(
        ROOT / "src" / "koto_app.py", "_bootstrap_api_setup"
    )

    assert "refresh_model_capabilities(probe_local=False)" in bootstrap_source
    assert "explicit_setup" in bootstrap_source
    assert bootstrap_source.index("if explicit_setup") < bootstrap_source.index(
        "_run_setup_if_needed"
    )
    assert "model_setup_done.json" not in bootstrap_source


def test_retired_local_router_cannot_return_through_desktop_startup() -> None:
    main_source = _function_source(ROOT / "src" / "koto_app.py", "main")

    assert "LocalModelRouter" not in main_source
    assert "local_model_router" not in main_source
    assert "KOTO_PREWARM_LOCAL_ROUTER" not in main_source


def test_packaged_entry_does_not_duplicate_or_gate_provider_setup() -> None:
    main_source = _function_source(ROOT / "src" / "koto_setup.py", "main")

    assert "_run_setup_if_needed()" not in main_source
    assert "koto_app.main()" in main_source


def test_ollama_remains_an_optional_launcher_dependency() -> None:
    bootstrap_source = (ROOT / "launcher" / "bootstrap.py").read_text(
        encoding="utf-8-sig"
    )

    required_section = bootstrap_source.split("REQUIRED_PACKAGES =", 1)[1].split(
        "OPTIONAL_PACKAGES =", 1
    )[0]
    assert "ollama" not in required_section.lower()


def test_outer_desktop_launcher_uses_only_startup_health() -> None:
    launcher_source = (ROOT / "Koto_Start.ps1").read_text(encoding="utf-8-sig")
    probe_source = launcher_source.split("function Test-KotoHealth", 1)[1].split(
        "function", 1
    )[0]

    assert "/api/startup-health" in probe_source
    assert "/api/health" not in probe_source.replace("/api/startup-health", "")


def test_installer_and_portable_share_the_complete_startup_matrix() -> None:
    helper = (ROOT / "tests" / "installer" / "release_e2e_helpers.ps1").read_text(
        encoding="utf-8-sig"
    )
    expected = {
        "blank",
        "cloud_invalid",
        "cloud_offline",
        "local_unselected",
        "local_service_down",
        "local_model_missing",
        "local_runtime_incompatible",
        "legacy_upgrade",
    }
    for scenario in expected:
        assert f'Name = "{scenario}"' in helper

    for script_name in ("test_installer_e2e.ps1", "test_portable_e2e.ps1"):
        source = (ROOT / "tests" / "installer" / script_name).read_text(
            encoding="utf-8-sig"
        )
        assert "Invoke-KotoStartupMatrix" in source
        assert "/api/startup-health" in helper
        assert "/api/capabilities" in helper


def test_frontend_startup_uses_configuration_only_capability_checks() -> None:
    source = (ROOT / "web" / "src" / "app" / "settings.ts").read_text(
        encoding="utf-8-sig"
    )
    setup_start = source.index("export async function checkSetupStatus")
    setup_end = source.index("export function showSetupWizard", setup_start)
    setup_body = source[setup_start:setup_end]
    status_start = source.index("export async function checkStatus")
    status_end = source.index("// ── Batch Jobs Panel", status_start)
    status_body = source[status_start:status_end]

    assert "'/api/capabilities'" in setup_body
    assert "showSetupWizard()" not in setup_body
    assert "probeModels: boolean = false" in status_body
    assert "probeModels ? '/api/ping/models' : '/api/capabilities'" in status_body
