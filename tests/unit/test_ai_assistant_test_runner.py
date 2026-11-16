from pathlib import Path

from scripts import run_ai_assistant_flow_tests as runner

ROOT = Path(__file__).resolve().parents[2]


def test_ai_assistant_runner_names_mocked_browser_lane_explicitly():
    assert "browser-mock" in runner.SUITES
    assert runner.SUITE_ALIASES["browser"] == "browser-mock"
    assert runner._resolve_suite_names("browser") == ["browser-mock"]
    assert runner._suite_requires_browser("browser")
    assert runner._suite_requires_browser("browser-mock")


def test_ai_assistant_runner_has_mcp_and_test_ready_preflight_lanes():
    assert runner.SUITES["mcp"]["nodes"] == [
        "tests/unit/test_mcp_integration.py",
        "tests/unit/test_frontend_observability_redaction.py",
    ]
    assert runner.COMPOSITE_SUITES["test-ready"] == [
        "smoke",
        "mcp",
        "browser-mock",
    ]
    assert runner.COMPOSITE_SUITES["release"][-1] == "browser-mock"


def test_ai_assistant_runner_disables_background_runtime_for_pytest():
    environment = runner._pytest_environment(
        {"KOTO_SKIP_BACKGROUND_RUNTIME": "0", "KEEP_ME": "yes"}
    )

    assert environment["KOTO_SKIP_BACKGROUND_RUNTIME"] == "1"
    assert environment["KEEP_ME"] == "yes"


def test_ai_assistant_runner_resolves_every_explicit_test_node():
    for suite_name in runner.SUITES:
        nodes = runner._resolve_nodes(suite_name)
        assert runner._missing_node_ids(nodes, ROOT) == [], suite_name


def test_ai_assistant_runner_reports_a_stale_explicit_test_node(tmp_path):
    test_file = tmp_path / "test_example.py"
    test_file.write_text("def test_current():\n    pass\n", encoding="utf-8")

    assert runner._missing_node_ids(
        [f"{test_file.name}::test_removed"],
        tmp_path,
    ) == [f"{test_file.name}::test_removed"]
