from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.summarize_startup_events import (
    _percentile,
    apply_trends,
    evaluate_budget,
    load_budget,
    load_history,
    main,
    render_markdown,
    summarize_file,
    update_history,
)


def _event(session: str, name: str, elapsed: int, **details):
    return {
        "schema_version": 1,
        "timestamp": "2026-07-19T00:00:00.000+00:00",
        "session_id": session,
        "event": name,
        "elapsed_ms": elapsed,
        "pid": 123,
        **details,
    }


def test_startup_event_summary_reports_release_metrics(tmp_path) -> None:
    path = tmp_path / "slow.jsonl"
    rows = [
        _event("s1", "desktop_start", 0),
        _event("s1", "backend_port_selected", 200, port=5000, used_fallback=False),
        _event("s1", "status_server_listening", 300),
        _event("s1", "window_shown", 1800, via_status_page=True),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    summaries = summarize_file(path)

    assert summaries == [
        {
            "file": str(path),
            "scenario": "slow",
            "session_id": "s1",
            "backend_port": 5000,
            "used_fallback": False,
            "via_status_page": True,
            "window_shown_ms": 1800,
            "frontend_ready_ms": None,
            "phase_durations_ms": {
                "process_to_python": None,
                "desktop_preflight": None,
                "port_selection": None,
                "backend_import": None,
                "backend_ready": None,
                "webview_import": None,
                "window_create": None,
                "window_show": None,
                "frontend_after_window": None,
            },
            "status_server_stopped_ms": None,
            "event_count": 4,
        }
    ]
    assert main([str(path)]) == 0


def test_startup_event_summary_rejects_incomplete_sessions(tmp_path) -> None:
    path = tmp_path / "incomplete.jsonl"
    path.write_text(
        json.dumps(_event("s1", "desktop_start", 0)) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="missing events"):
        summarize_file(path)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell release helper is Windows-only")
def test_packaged_evidence_export_excludes_later_server_only_session(tmp_path) -> None:
    install_dir = tmp_path / "installed"
    event_log = install_dir / "logs" / "startup_events.jsonl"
    event_log.parent.mkdir(parents=True)
    rows = [
        _event("desktop", "desktop_start", 0),
        _event(
            "desktop",
            "backend_port_selected",
            100,
            port=5099,
            used_fallback=False,
        ),
        _event("desktop", "window_shown", 2400, via_status_page=False),
        _event("desktop", "frontend_ready", 2600),
        _event("server-only", "desktop_start", 0),
        _event(
            "server-only",
            "backend_port_selected",
            80,
            port=5119,
            used_fallback=False,
        ),
    ]
    event_log.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "evidence"
    helper = Path("tests/installer/release_e2e_helpers.ps1").resolve().as_posix()
    command = (
        f". '{helper}'; "
        f"Export-KotoDesktopStartupEvidence -InstallDir '{install_dir.as_posix()}' "
        f"-OutputDirectory '{output_dir.as_posix()}' -Scenario installer"
    )

    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    frozen = output_dir / "installer.jsonl"
    assert len(frozen.read_text(encoding="utf-8").splitlines()) == 4
    summary = summarize_file(frozen)
    assert len(summary) == 1
    assert summary[0]["session_id"] == "desktop"
    assert summary[0]["window_shown_ms"] == 2400


def _summary(
    scenario: str,
    elapsed: int,
    *,
    fallback: bool = False,
    status_page: bool = False,
    stopped: int | None = None,
    frontend: int | None = None,
    phases: dict | None = None,
):
    return {
        "file": f"{scenario}.jsonl",
        "scenario": scenario,
        "session_id": scenario,
        "backend_port": 5001 if fallback else 5000,
        "used_fallback": fallback,
        "via_status_page": status_page,
        "window_shown_ms": elapsed,
        "frontend_ready_ms": frontend,
        "phase_durations_ms": phases or {},
        "status_server_stopped_ms": stopped,
        "event_count": 6,
    }


def _budget():
    return {
        "schema_version": 1,
        "scenarios": {
            "normal": {
                "warning_window_ms": 8000,
                "hard_window_ms": 30000,
                "expected_fallback": False,
            },
            "slow": {
                "warning_window_ms": 12000,
                "hard_window_ms": 45000,
                "expected_status_page": True,
                "max_status_release_after_window_ms": 5000,
            },
            "port_conflict": {
                "warning_window_ms": 12000,
                "hard_window_ms": 45000,
                "expected_fallback": True,
            },
        },
    }


def test_startup_budget_passes_expected_lifecycle_and_renders_markdown() -> None:
    report = evaluate_budget(
        [
            _summary("normal", 2000),
            _summary("slow", 3000, status_page=True, stopped=5100),
            _summary("port_conflict", 2500, fallback=True),
        ],
        _budget(),
    )

    assert report["status"] == "pass"
    markdown = render_markdown(report)
    assert "✅ **PASS**" in markdown
    assert "| slow | 3000 ms |" in markdown


def test_startup_budget_warns_without_blocking_before_hard_limit() -> None:
    report = evaluate_budget(
        [
            _summary("normal", 9000),
            _summary("slow", 3000, status_page=True, stopped=5000),
            _summary("port_conflict", 2500, fallback=True),
        ],
        _budget(),
    )

    assert report["status"] == "warning"
    assert report["failures"] == []
    assert "normal: window_shown_ms 9000 exceeded warning 8000" in report["warnings"]


@pytest.mark.parametrize(
    ("summaries", "failure"),
    [
        (
            [
                _summary("normal", 31000),
                _summary("slow", 3000, status_page=True, stopped=5000),
                _summary("port_conflict", 2500, fallback=True),
            ],
            "normal: window_shown_ms 31000 exceeded hard limit 30000",
        ),
        (
            [
                _summary("normal", 2000),
                _summary("slow", 3000, status_page=False),
                _summary("port_conflict", 2500, fallback=True),
            ],
            "slow: via_status_page=False, expected True",
        ),
        (
            [
                _summary("normal", 2000),
                _summary("slow", 3000, status_page=True, stopped=9000),
                _summary("port_conflict", 2500, fallback=True),
            ],
            "slow: status port release delay 6000 exceeded 5000",
        ),
    ],
)
def test_startup_budget_blocks_hard_or_behavior_regressions(summaries, failure) -> None:
    report = evaluate_budget(summaries, _budget())

    assert report["status"] == "fail"
    assert failure in report["failures"]


def test_startup_budget_enforces_interactive_and_phase_limits() -> None:
    report = evaluate_budget(
        [
            _summary(
                "normal",
                2000,
                frontend=5000,
                phases={"backend_import": 2500, "frontend_after_window": 3000},
            )
        ],
        {
            "schema_version": 1,
            "phase_budgets": {
                "backend_import": {"warning_ms": 1000, "hard_ms": 3000},
                "frontend_after_window": {"warning_ms": 1000, "hard_ms": 2500},
            },
            "scenarios": {
                "normal": {
                    "warning_window_ms": 8000,
                    "hard_window_ms": 30000,
                    "warning_interactive_ms": 4000,
                    "hard_interactive_ms": 6000,
                    "require_frontend_ready": True,
                    "require_phase_metrics": True,
                }
            },
        },
    )

    assert report["status"] == "fail"
    assert "normal: frontend_ready_ms 5000 exceeded warning 4000" in report["warnings"]
    assert any("phase backend_import" in warning for warning in report["warnings"])
    assert any(
        "phase frontend_after_window" in failure for failure in report["failures"]
    )


def test_repository_startup_budget_has_warning_and_hard_limits() -> None:
    budget = load_budget("config/startup_performance_budget.json")

    assert set(budget["scenarios"]) == {"normal", "slow", "port_conflict"}
    for rule in budget["scenarios"].values():
        assert 0 < rule["warning_window_ms"] < rule["hard_window_ms"] <= 45000
        assert rule["require_frontend_ready"] is True
        assert rule["require_phase_metrics"] is True
    assert set(budget["phase_budgets"]) == {
        "process_to_python",
        "desktop_preflight",
        "port_selection",
        "backend_import",
        "backend_ready",
        "webview_import",
        "window_create",
        "window_show",
        "frontend_after_window",
    }


def test_packaged_startup_budget_covers_both_release_shapes() -> None:
    budget = load_budget("config/packaged_startup_performance_budget.json")

    assert set(budget["scenarios"]) == {"installer", "portable"}
    assert budget["trend"]["minimum_samples"] == 5
    for rule in budget["scenarios"].values():
        assert 0 < rule["warning_window_ms"] < rule["hard_window_ms"] <= 60000
        assert rule["expected_fallback"] is False


def _complete_startup_events(
    session: str,
    *,
    port: int,
    window: int,
    frontend: int,
    fallback: bool = False,
    status_page: bool = False,
    stopped: int | None = None,
):
    rows = [
        _event(session, "python_runtime_ready", 100),
        _event(session, "desktop_start", 120),
        _event(session, "backend_start_requested", 200),
        _event(
            session,
            "backend_port_selected",
            250,
            port=port,
            used_fallback=fallback,
        ),
        _event(session, "backend_import_started", 270),
        _event(session, "webview_import_started", 300),
        _event(session, "webview_import_completed", 500),
        _event(session, "backend_import_completed", 900),
        _event(session, "backend_ready", 1000),
        _event(session, "window_create_started", 1100),
        _event(session, "window_created", 1200),
        _event(session, "webview_loop_started", 1250),
        _event(session, "window_shown", window, via_status_page=status_page),
        _event(session, "frontend_ready", frontend),
    ]
    if stopped is not None:
        rows.append(_event(session, "status_server_stopped", stopped))
    return rows


def test_startup_budget_cli_writes_machine_and_human_reports(tmp_path) -> None:
    paths = []
    rows_by_scenario = {
        "normal": _complete_startup_events(
            "normal", port=5000, window=2000, frontend=2300
        ),
        "slow": _complete_startup_events(
            "slow",
            port=5000,
            window=3000,
            frontend=3400,
            status_page=True,
            stopped=5000,
        ),
        "port_conflict": _complete_startup_events(
            "conflict", port=5001, window=2500, frontend=2800, fallback=True
        ),
    }
    for scenario, rows in rows_by_scenario.items():
        path = tmp_path / f"{scenario}.jsonl"
        path.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
        paths.append(path)
    report_path = tmp_path / "report.json"
    markdown_path = tmp_path / "summary.md"
    history_path = tmp_path / "history.jsonl"

    exit_code = main(
        [
            "--budget",
            "config/startup_performance_budget.json",
            "--report",
            str(report_path),
            "--markdown",
            str(markdown_path),
            "--history",
            str(history_path),
            "--revision",
            "abc123",
            "--run-id",
            "run-123",
            *(str(path) for path in paths),
        ]
    )

    assert exit_code == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "pass"
    assert "Overall: ✅ **PASS**" in markdown_path.read_text(encoding="utf-8")
    assert "Historical trend" in markdown_path.read_text(encoding="utf-8")
    history = load_history(history_path)
    assert history[0]["run_id"] == "run-123"
    assert history[0]["revision"] == "abc123"


def _history(normal_values):
    return [
        {
            "schema_version": 1,
            "run_id": f"run-{index}",
            "scenarios": {
                "normal": {"window_shown_ms": value},
                "slow": {"window_shown_ms": 3000},
                "port_conflict": {"window_shown_ms": 2500},
            },
        }
        for index, value in enumerate(normal_values)
    ]


def _trend_policy(**overrides):
    return {
        "history_window": 20,
        "minimum_samples": 5,
        "p95_warning_ratio": 1.35,
        "p95_blocking_ratio": 2.0,
        "consecutive_degradation_runs": 3,
        "minimum_consecutive_increase_ratio": 0.1,
        **overrides,
    }


def _passing_report(normal_elapsed=2000):
    return evaluate_budget(
        [
            _summary("normal", normal_elapsed),
            _summary("slow", 3000, status_page=True, stopped=5000),
            _summary("port_conflict", 2500, fallback=True),
        ],
        _budget(),
    )


def test_startup_trend_uses_nearest_rank_p50_and_p95() -> None:
    assert _percentile(list(range(1, 21)), 0.5) == 10
    assert _percentile(list(range(1, 21)), 0.95) == 19

    report = apply_trends(
        _passing_report(),
        _history([1000, 1200, 1400, 1600, 2000]),
        _trend_policy(),
    )
    normal = next(
        scenario
        for scenario in report["trend"]["scenarios"]
        if scenario["scenario"] == "normal"
    )
    assert normal["p50_ms"] == 1400
    assert normal["p95_ms"] == 2000
    assert normal["p95_ratio"] == 1.0


@pytest.mark.parametrize(
    ("current", "expected_status"),
    [(2800, "warning"), (4500, "fail")],
)
def test_startup_trend_warns_or_blocks_relative_to_historical_p95(
    current, expected_status
) -> None:
    report = apply_trends(
        _passing_report(current),
        _history([1800, 1900, 1950, 2000, 2000]),
        _trend_policy(),
    )

    assert report["status"] == expected_status
    assert any(
        "historical P95" in item for item in report["warnings"] + report["failures"]
    )


def test_startup_trend_warns_on_consecutive_degradation_before_p95_exists() -> None:
    report = apply_trends(
        _passing_report(1500),
        _history([1000, 1200]),
        _trend_policy(),
    )

    assert report["status"] == "warning"
    assert any("3 consecutive runs" in item for item in report["warnings"])
    normal = next(
        scenario
        for scenario in report["trend"]["scenarios"]
        if scenario["scenario"] == "normal"
    )
    assert normal["p95_ms"] is None


def test_startup_history_deduplicates_run_id_and_enforces_retention(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    update_history(path, _passing_report(1000), run_id="run-1", retention_records=2)
    update_history(path, _passing_report(1200), run_id="run-2", retention_records=2)
    records = update_history(
        path,
        _passing_report(1400),
        run_id="run-2",
        revision="abc123",
        retention_records=2,
    )

    assert [record["run_id"] for record in records] == ["run-1", "run-2"]
    assert records[-1]["revision"] == "abc123"
    assert records[-1]["scenarios"]["normal"]["window_shown_ms"] == 1400
    assert load_history(path) == records
