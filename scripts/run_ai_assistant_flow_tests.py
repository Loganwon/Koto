#!/usr/bin/env python
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from collections import OrderedDict


SUITES = OrderedDict(
    [
        (
            "smoke",
            {
                "description": "Critical AI assistant routing and runtime regressions.",
                "nodes": [
                    "tests/test_ai_stream.py::TestWorkspaceAssistantTaskRemovalRegression::test_workspace_send_message_keeps_open_file_and_uses_whitebox_stream",
                    "tests/test_ai_stream.py::TestWorkspaceAssistantTaskRemovalRegression::test_workspace_send_message_builds_whitebox_payload_with_target_path_history_and_model_state",
                    "tests/test_ai_stream.py::TestEditorAIStream::test_whitebox_task_stream_emits_new_contract",
                    "tests/unit/test_file_task_runtime.py::test_file_task_model_client_passes_file_task_timeout_to_local_provider",
                    "tests/unit/test_file_task_runtime.py::test_file_task_model_client_routes_local_and_cloud",
                    "tests/unit/test_file_task_runtime.py::test_file_task_runtime_execution_brief_ignores_legacy_delegated_planner_and_stays_native",
                ],
            },
        ),
        (
            "contracts",
            {
                "description": "Source-level guards for the bundled TS workspace assistant task chain.",
                "nodes": [
                    "tests/unit/test_ai_task_chain_architecture.py",
                ],
            },
        ),
        (
            "backend",
            {
                "description": "Backend SSE task-stream endpoint flows and request normalization.",
                "nodes": [
                    "tests/test_ai_stream.py::TestEditorAIStream::test_whitebox_task_stream_executes_xlsx_to_docx_write_loop",
                    "tests/test_ai_stream.py::TestEditorAIStream::test_whitebox_task_stream_reports_no_write_when_docx_is_unchanged",
                    "tests/test_ai_stream.py::TestEditorAIStream::test_whitebox_task_stream_emits_new_contract",
                    "tests/test_ai_stream.py::TestEditorAIStream::test_whitebox_task_stream_requires_task",
                    "tests/test_ai_stream.py::TestEditorAIStream::test_whitebox_task_stream_normalizes_local_model_config",
                    "tests/test_ai_stream.py::TestEditorAIStream::test_whitebox_task_stream_keeps_finished_run_runtime_only",
                    "tests/test_ai_stream.py::TestEditorAIStream::test_whitebox_task_stream_uses_request_history_only",
                    "tests/test_ai_stream.py::TestEditorAIStream::test_whitebox_task_stream_does_not_inject_memory_router_context",
                ],
            },
        ),
        (
            "runtime",
            {
                "description": "File-task runtime, native routing, tool-gap, and provider fallback behavior.",
                "nodes": [
                    "tests/unit/test_llm_providers.py::TestOllamaProviderTimeoutPassthrough::test_generate_content_passes_call_timeout",
                    "tests/unit/test_file_task_runtime.py::test_file_task_runtime_parses_native_tool_design_protocol_from_model_text",
                    "tests/unit/test_file_task_runtime.py::test_file_task_model_client_passes_file_task_timeout_to_local_provider",
                    "tests/unit/test_file_task_runtime.py::test_file_task_model_client_routes_local_and_cloud",
                    "tests/unit/test_file_task_runtime.py::test_file_task_model_client_prefers_file_task_model_route",
                    "tests/unit/test_file_task_runtime.py::test_file_task_runtime_execution_brief_ignores_legacy_delegated_planner_and_stays_native",
                    "tests/unit/test_file_task_runtime.py::test_file_task_runtime_classification_defers_planner_without_explicit_override",
                    "tests/unit/test_file_task_runtime.py::test_file_task_runtime_does_not_external_fallback_after_tool_gap",
                    "tests/unit/test_file_task_runtime.py::test_file_task_runtime_does_not_external_fallback_after_native_model_failure",
                ],
            },
        ),
        (
            "matrix",
            {
                "description": "Task-family routing matrix and completion-contract coverage.",
                "nodes": [
                    "tests/unit/test_ai_task_family_matrix.py",
                    "tests/unit/test_file_task_recipes.py",
                    "tests/unit/test_file_task_classification_recipes.py",
                ],
            },
        ),
        (
            "browser-mock",
            {
                "description": "Playwright browser smoke for the workspace AI assistant shell and mocked task-card rendering.",
                "nodes": [
                    "tests/e2e/test_workspace_ai_assistant.py",
                ],
            },
        ),
        (
            "mcp",
            {
                "description": "MCP route, WebSocket, frontend-action, and stdio bridge contract checks.",
                "nodes": [
                    "tests/unit/test_mcp_integration.py",
                    "tests/unit/test_frontend_observability_redaction.py",
                ],
            },
        ),
        (
            "evaluation",
            {
                "description": "Offline deterministic intent accuracy and execution-quality checks; set KOTO_LIVE_EVALUATION=1 for real LLM calls.",
                "nodes": [
                    "tests/evaluation/test_intent_accuracy.py",
                    "tests/evaluation/test_execution_quality.py",
                ],
            },
        ),
    ]
)

COMPOSITE_SUITES = OrderedDict(
    [
        ("full", ["smoke", "contracts", "backend", "runtime", "matrix"]),
        ("release", ["smoke", "contracts", "backend", "runtime", "matrix", "browser-mock"]),
        ("test-ready", ["smoke", "mcp", "browser-mock"]),
    ]
)

SUITE_ALIASES = {
    "browser": "browser-mock",
}

BROWSER_PREREQUISITES = OrderedDict(
    [
        ("pytest_playwright", "pytest-playwright"),
        ("playwright", "playwright"),
    ]
)


def _ordered_unique(items: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _resolve_suite_names(name: str) -> list[str]:
    name = SUITE_ALIASES.get(name, name)
    if name in SUITES:
        return [name]
    if name in COMPOSITE_SUITES:
        return list(COMPOSITE_SUITES[name])
    raise KeyError(name)


def _resolve_nodes(name: str) -> list[str]:
    nodes: list[str] = []
    for suite_name in _resolve_suite_names(name):
        nodes.extend(SUITES[suite_name]["nodes"])
    return _ordered_unique(nodes)


def _all_suite_names() -> list[str]:
    return list(SUITES.keys()) + list(COMPOSITE_SUITES.keys()) + list(SUITE_ALIASES.keys())


def _suite_requires_browser(name: str) -> bool:
    return "browser-mock" in _resolve_suite_names(name)


def _pytest_environment(base_environment: dict[str, str] | None = None) -> dict[str, str]:
    """Return an isolated environment for deterministic assistant-flow tests.

    The task-stream assertions exercise request handling, not production
    schedulers.  Starting background jobs, model warmups, and file watchers in
    the same interpreter makes SSE timing depend on machine state.
    """
    environment = dict(os.environ if base_environment is None else base_environment)
    environment["KOTO_SKIP_BACKGROUND_RUNTIME"] = "1"
    return environment


def _missing_browser_prerequisites() -> list[str]:
    missing = []
    for module_name, package_name in BROWSER_PREREQUISITES.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(package_name)
    return missing


def _print_browser_prerequisite_error(missing: list[str]) -> None:
    print(
        "[ai-assistant-tests] browser prerequisites missing: " + ", ".join(missing),
        file=sys.stderr,
    )
    print(
        "[ai-assistant-tests] install with: pip install pytest-playwright playwright",
        file=sys.stderr,
    )
    print(
        "[ai-assistant-tests] then run: python -m playwright install chromium",
        file=sys.stderr,
    )


def _print_suite_catalog() -> None:
    print("AI assistant flow suites:")
    for name, meta in SUITES.items():
        print(f"- {name}: {meta['description']}")
        for node in meta["nodes"]:
            print(f"    {node}")
    for name, members in COMPOSITE_SUITES.items():
        joined = ", ".join(members)
        print(f"- {name}: combines [{joined}]")
    for alias, target in SUITE_ALIASES.items():
        print(f"- {alias}: alias for {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the curated Koto AI assistant task-flow regression suites.",
    )
    parser.add_argument(
        "suite",
        nargs="?",
        default="smoke",
        choices=_all_suite_names(),
        help="Suite to run. Use --list to inspect the available suites.",
    )
    parser.add_argument("--list", action="store_true", help="Print the suite catalog and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved pytest command without running it.")
    args, pytest_args = parser.parse_known_args(argv)

    if args.list:
        _print_suite_catalog()
        return 0

    resolved_suite = SUITE_ALIASES.get(args.suite, args.suite)
    nodes = _resolve_nodes(resolved_suite)
    command = [sys.executable, "-m", "pytest", *nodes, *pytest_args]

    if resolved_suite != args.suite:
        print(f"[ai-assistant-tests] suite={args.suite} alias_for={resolved_suite}")
    print(f"[ai-assistant-tests] suite={resolved_suite} nodes={len(nodes)}")
    for node in nodes:
        print(f"  - {node}")
    if pytest_args:
        print(f"[ai-assistant-tests] extra pytest args: {' '.join(pytest_args)}")
    if args.dry_run:
        print("[ai-assistant-tests] dry-run command:")
        print(" ".join(command))
        return 0

    if _suite_requires_browser(resolved_suite):
        missing = _missing_browser_prerequisites()
        if missing:
            _print_browser_prerequisite_error(missing)
            return 2

    return subprocess.call(command, env=_pytest_environment())


if __name__ == "__main__":
    raise SystemExit(main())
