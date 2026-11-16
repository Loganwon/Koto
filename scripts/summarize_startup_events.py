#!/usr/bin/env python3
"""Validate and summarize Koto startup event artifacts."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_EVENTS = {"desktop_start", "backend_port_selected", "window_shown"}
STARTUP_PHASES = (
    ("process_to_python", "Process → Python", None, "python_runtime_ready"),
    (
        "desktop_preflight",
        "Python → backend request",
        "python_runtime_ready",
        "backend_start_requested",
    ),
    (
        "port_selection",
        "Port selection",
        "backend_start_requested",
        "backend_port_selected",
    ),
    (
        "backend_import",
        "Backend import",
        "backend_import_started",
        "backend_import_completed",
    ),
    (
        "backend_ready",
        "Backend selected → ready",
        "backend_port_selected",
        "backend_ready",
    ),
    (
        "webview_import",
        "WebView import",
        "webview_import_started",
        "webview_import_completed",
    ),
    (
        "window_create",
        "Native window create",
        "window_create_started",
        "window_created",
    ),
    ("window_show", "Native window show", "window_created", "window_shown"),
    ("frontend_after_window", "Window → interactive", "window_shown", "frontend_ready"),
)
PHASE_LABELS = {name: label for name, label, _, _ in STARTUP_PHASES}


def summarize_file(path: Path | str) -> list[dict[str, Any]]:
    source = Path(path)
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line_number, raw in enumerate(
        source.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{source}:{line_number}: invalid JSON: {exc.msg}"
            ) from exc
        if event.get("schema_version") != 1:
            raise ValueError(f"{source}:{line_number}: unsupported schema version")
        if not event.get("session_id") or not event.get("event"):
            raise ValueError(f"{source}:{line_number}: missing session_id or event")
        sessions[str(event["session_id"])].append(event)

    if not sessions:
        raise ValueError(f"{source}: no startup events")

    summaries: list[dict[str, Any]] = []
    for session_id, events in sessions.items():
        names = {str(event["event"]) for event in events}
        missing = REQUIRED_EVENTS - names
        if missing:
            raise ValueError(
                f"{source}: session {session_id} missing events: {', '.join(sorted(missing))}"
            )
        selected = next(
            event for event in events if event["event"] == "backend_port_selected"
        )
        window = next(event for event in events if event["event"] == "window_shown")
        status_stopped = next(
            (event for event in events if event["event"] == "status_server_stopped"),
            None,
        )
        by_name = {str(event["event"]): event for event in events}

        def elapsed(event_name: str | None) -> int | None:
            if event_name is None:
                return 0
            event = by_name.get(event_name)
            return int(event.get("elapsed_ms") or 0) if event else None

        phase_durations: dict[str, int | None] = {}
        for phase, _, start_name, end_name in STARTUP_PHASES:
            start = elapsed(start_name)
            end = elapsed(end_name)
            phase_durations[phase] = (
                max(0, end - start) if start is not None and end is not None else None
            )
        frontend = by_name.get("frontend_ready")
        summaries.append(
            {
                "file": str(source),
                "scenario": source.stem,
                "session_id": session_id,
                "backend_port": selected.get("port"),
                "used_fallback": bool(selected.get("used_fallback")),
                "via_status_page": bool(window.get("via_status_page")),
                "window_shown_ms": int(window.get("elapsed_ms") or 0),
                "frontend_ready_ms": (
                    int(frontend.get("elapsed_ms") or 0) if frontend else None
                ),
                "phase_durations_ms": phase_durations,
                "status_server_stopped_ms": (
                    int(status_stopped.get("elapsed_ms") or 0)
                    if status_stopped
                    else None
                ),
                "event_count": len(events),
            }
        )
    return summaries


def load_budget(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    budget = json.loads(source.read_text(encoding="utf-8"))
    if budget.get("schema_version") != 1 or not isinstance(
        budget.get("scenarios"), dict
    ):
        raise ValueError(f"{source}: invalid startup performance budget")
    return budget


def evaluate_budget(
    summaries: list[dict[str, Any]], budget: dict[str, Any]
) -> dict[str, Any]:
    by_scenario = {summary["scenario"]: summary for summary in summaries}
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    warnings: list[str] = []

    for scenario, rule in budget["scenarios"].items():
        summary = by_scenario.get(scenario)
        if summary is None:
            failures.append(f"missing required scenario: {scenario}")
            continue

        scenario_failures: list[str] = []
        scenario_warnings: list[str] = []
        elapsed = int(summary["window_shown_ms"])
        warning_limit = int(rule["warning_window_ms"])
        hard_limit = int(rule["hard_window_ms"])
        if elapsed > hard_limit:
            scenario_failures.append(
                f"window_shown_ms {elapsed} exceeded hard limit {hard_limit}"
            )
        elif elapsed > warning_limit:
            scenario_warnings.append(
                f"window_shown_ms {elapsed} exceeded warning {warning_limit}"
            )

        interactive = summary.get("frontend_ready_ms")
        if rule.get("require_frontend_ready") and interactive is None:
            scenario_failures.append("frontend_ready event missing")
        if interactive is not None and "hard_interactive_ms" in rule:
            interactive = int(interactive)
            interactive_warning = int(rule["warning_interactive_ms"])
            interactive_hard = int(rule["hard_interactive_ms"])
            if interactive > interactive_hard:
                scenario_failures.append(
                    f"frontend_ready_ms {interactive} exceeded hard limit {interactive_hard}"
                )
            elif interactive > interactive_warning:
                scenario_warnings.append(
                    f"frontend_ready_ms {interactive} exceeded warning {interactive_warning}"
                )

        phase_results: list[dict[str, Any]] = []
        for phase, phase_rule in budget.get("phase_budgets", {}).items():
            duration = summary.get("phase_durations_ms", {}).get(phase)
            phase_failures: list[str] = []
            phase_warnings: list[str] = []
            if duration is None:
                if rule.get("require_phase_metrics"):
                    phase_failures.append("metric missing")
            else:
                duration = int(duration)
                phase_warning = int(phase_rule["warning_ms"])
                phase_hard = int(phase_rule["hard_ms"])
                if duration > phase_hard:
                    phase_failures.append(
                        f"{duration} ms exceeded hard limit {phase_hard}"
                    )
                elif duration > phase_warning:
                    phase_warnings.append(
                        f"{duration} ms exceeded warning {phase_warning}"
                    )
            scenario_failures.extend(
                f"phase {phase}: {message}" for message in phase_failures
            )
            scenario_warnings.extend(
                f"phase {phase}: {message}" for message in phase_warnings
            )
            phase_results.append(
                {
                    "phase": phase,
                    "label": PHASE_LABELS.get(phase, phase),
                    "duration_ms": duration,
                    "warning_ms": int(phase_rule["warning_ms"]),
                    "hard_ms": int(phase_rule["hard_ms"]),
                    "status": (
                        "fail"
                        if phase_failures
                        else "warning" if phase_warnings else "pass"
                    ),
                }
            )

        for rule_name, summary_name in (
            ("expected_fallback", "used_fallback"),
            ("expected_status_page", "via_status_page"),
        ):
            if rule_name in rule and bool(summary[summary_name]) != bool(
                rule[rule_name]
            ):
                scenario_failures.append(
                    f"{summary_name}={summary[summary_name]!r}, expected {rule[rule_name]!r}"
                )

        release_limit = rule.get("max_status_release_after_window_ms")
        if release_limit is not None:
            stopped = summary.get("status_server_stopped_ms")
            if stopped is None:
                scenario_failures.append("status_server_stopped event missing")
            else:
                release_delay = int(stopped) - elapsed
                if release_delay > int(release_limit):
                    scenario_failures.append(
                        f"status port release delay {release_delay} exceeded {release_limit}"
                    )

        failures.extend(f"{scenario}: {message}" for message in scenario_failures)
        warnings.extend(f"{scenario}: {message}" for message in scenario_warnings)
        results.append(
            {
                **summary,
                "warning_window_ms": warning_limit,
                "hard_window_ms": hard_limit,
                "warning_interactive_ms": rule.get("warning_interactive_ms"),
                "hard_interactive_ms": rule.get("hard_interactive_ms"),
                "phase_results": phase_results,
                "status": (
                    "fail"
                    if scenario_failures
                    else "warning" if scenario_warnings else "pass"
                ),
                "failures": scenario_failures,
                "warnings": scenario_warnings,
            }
        )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "fail" if failures else "warning" if warnings else "pass",
        "failures": failures,
        "warnings": warnings,
        "scenarios": results,
    }


def load_history(path: Path | str) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(
        source.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{source}:{line_number}: invalid history JSON: {exc.msg}"
            ) from exc
        if record.get("schema_version") != 1 or not isinstance(
            record.get("scenarios"), dict
        ):
            raise ValueError(f"{source}:{line_number}: invalid history record")
        records.append(record)
    return records


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(int(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def apply_trends(
    report: dict[str, Any],
    history: list[dict[str, Any]],
    policy: dict[str, Any],
    *,
    current_run_id: str | None = None,
) -> dict[str, Any]:
    history_window = max(1, int(policy.get("history_window", 20)))
    minimum_samples = max(1, int(policy.get("minimum_samples", 5)))
    warning_ratio = float(policy.get("p95_warning_ratio", 1.35))
    blocking_ratio = float(policy.get("p95_blocking_ratio", 2.0))
    consecutive_runs = max(2, int(policy.get("consecutive_degradation_runs", 3)))
    minimum_increase = max(
        0.0, float(policy.get("minimum_consecutive_increase_ratio", 0.1))
    )
    eligible = [record for record in history if record.get("run_id") != current_run_id][
        -history_window:
    ]
    trend_results: list[dict[str, Any]] = []

    for scenario in report["scenarios"]:
        name = scenario["scenario"]
        values = [
            int(record["scenarios"][name]["window_shown_ms"])
            for record in eligible
            if name in record["scenarios"]
            and record["scenarios"][name].get("window_shown_ms") is not None
        ]
        interactive_values = [
            int(record["scenarios"][name]["frontend_ready_ms"])
            for record in eligible
            if name in record["scenarios"]
            and record["scenarios"][name].get("frontend_ready_ms") is not None
        ]
        trend = {
            "scenario": name,
            "sample_count": len(values),
            "p50_ms": None,
            "p95_ms": None,
            "p95_ratio": None,
            "interactive_sample_count": len(interactive_values),
            "interactive_p50_ms": None,
            "interactive_p95_ms": None,
            "status": "insufficient_history",
        }
        if len(values) >= minimum_samples:
            p50 = round(statistics.median(values))
            p95 = _percentile(values, 0.95)
            current = int(scenario["window_shown_ms"])
            ratio = round(current / p95, 3) if p95 > 0 else None
            trend.update(
                {
                    "p50_ms": p50,
                    "p95_ms": p95,
                    "p95_ratio": ratio,
                    "status": "pass",
                }
            )
            if ratio is not None and ratio >= blocking_ratio:
                message = (
                    f"{name}: current {current} ms is {ratio:.2f}x historical P95 "
                    f"{p95} ms (blocking ratio {blocking_ratio:.2f}x)"
                )
                report["failures"].append(message)
                scenario["failures"].append(message.removeprefix(f"{name}: "))
                trend["status"] = "fail"
            elif ratio is not None and ratio >= warning_ratio:
                message = (
                    f"{name}: current {current} ms is {ratio:.2f}x historical P95 "
                    f"{p95} ms (warning ratio {warning_ratio:.2f}x)"
                )
                report["warnings"].append(message)
                scenario["warnings"].append(message.removeprefix(f"{name}: "))
                trend["status"] = "warning"

        if len(interactive_values) >= minimum_samples:
            trend["interactive_p50_ms"] = round(statistics.median(interactive_values))
            trend["interactive_p95_ms"] = _percentile(interactive_values, 0.95)

        recent = values[-(consecutive_runs - 1) :] + [int(scenario["window_shown_ms"])]
        if len(recent) == consecutive_runs and all(
            newer >= older * (1.0 + minimum_increase)
            for older, newer in zip(recent, recent[1:])
        ):
            message = (
                f"{name}: startup slowed for {consecutive_runs} consecutive runs "
                f"({', '.join(str(value) for value in recent)} ms)"
            )
            report["warnings"].append(message)
            scenario["warnings"].append(message.removeprefix(f"{name}: "))
            if trend["status"] != "fail":
                trend["status"] = "warning"
        trend_results.append(trend)

    for scenario in report["scenarios"]:
        scenario["status"] = (
            "fail"
            if scenario["failures"]
            else "warning" if scenario["warnings"] else "pass"
        )
    report["status"] = (
        "fail" if report["failures"] else "warning" if report["warnings"] else "pass"
    )
    report["trend"] = {
        "history_records": len(eligible),
        "history_window": history_window,
        "minimum_samples": minimum_samples,
        "scenarios": trend_results,
    }
    return report


def update_history(
    path: Path | str,
    report: dict[str, Any],
    *,
    run_id: str,
    revision: str = "",
    retention_records: int = 50,
) -> list[dict[str, Any]]:
    destination = Path(path)
    records = [
        record for record in load_history(destination) if record.get("run_id") != run_id
    ]
    records.append(
        {
            "schema_version": 1,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": run_id,
            "revision": revision,
            "status": report["status"],
            "scenarios": {
                scenario["scenario"]: {
                    "window_shown_ms": scenario["window_shown_ms"],
                    "frontend_ready_ms": scenario.get("frontend_ready_ms"),
                    "phase_durations_ms": scenario.get("phase_durations_ms", {}),
                    "used_fallback": scenario["used_fallback"],
                    "via_status_page": scenario["via_status_page"],
                }
                for scenario in report["scenarios"]
            },
        }
    )
    records = records[-max(1, int(retention_records)) :]
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return records


def render_markdown(report: dict[str, Any]) -> str:
    icon = {"pass": "✅", "warning": "⚠️", "fail": "❌"}
    lines = [
        "## Koto startup performance budget",
        "",
        f"Overall: {icon[report['status']]} **{report['status'].upper()}**",
        "",
        "| Scenario | Native window | Interactive | Window budget | Interactive budget | Result |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for scenario in report["scenarios"]:
        interactive = (
            f"{scenario['frontend_ready_ms']} ms"
            if scenario.get("frontend_ready_ms") is not None
            else "—"
        )
        interactive_budget = (
            f"{scenario['warning_interactive_ms']} / {scenario['hard_interactive_ms']} ms"
            if scenario.get("hard_interactive_ms") is not None
            else "—"
        )
        lines.append(
            f"| {scenario['scenario']} | {scenario['window_shown_ms']} ms | "
            f"{interactive} | {scenario['warning_window_ms']} / "
            f"{scenario['hard_window_ms']} ms | {interactive_budget} | "
            f"{icon[scenario['status']]} {scenario['status']} |"
        )
    phase_rows = [
        (scenario["scenario"], phase)
        for scenario in report["scenarios"]
        for phase in scenario.get("phase_results", [])
    ]
    if phase_rows:
        lines.extend(
            [
                "",
                "### Startup phase breakdown",
                "",
                "| Scenario | Phase | Duration | Warning | Hard limit | Result |",
                "|---|---|---:|---:|---:|:---:|",
            ]
        )
        for scenario_name, phase in phase_rows:
            duration = (
                f"{phase['duration_ms']} ms"
                if phase["duration_ms"] is not None
                else "—"
            )
            lines.append(
                f"| {scenario_name} | {phase['label']} | {duration} | "
                f"{phase['warning_ms']} ms | {phase['hard_ms']} ms | "
                f"{icon[phase['status']]} {phase['status']} |"
            )
    trend = report.get("trend")
    if trend:
        lines.extend(
            [
                "",
                "### Historical trend",
                "",
                "| Scenario | Window samples | Window P50 | Window P95 | Interactive samples | Interactive P50 | Interactive P95 | Trend |",
                "|---|---:|---:|---:|---:|---:|---:|:---:|",
            ]
        )
        for scenario in trend["scenarios"]:
            p50 = f"{scenario['p50_ms']} ms" if scenario["p50_ms"] is not None else "—"
            p95 = f"{scenario['p95_ms']} ms" if scenario["p95_ms"] is not None else "—"
            ratio = (
                f"{scenario['p95_ratio']:.2f}x"
                if scenario["p95_ratio"] is not None
                else "—"
            )
            interactive_p50 = (
                f"{scenario['interactive_p50_ms']} ms"
                if scenario["interactive_p50_ms"] is not None
                else "—"
            )
            interactive_p95 = (
                f"{scenario['interactive_p95_ms']} ms"
                if scenario["interactive_p95_ms"] is not None
                else "—"
            )
            trend_icon = icon.get(scenario["status"], "ℹ️")
            lines.append(
                f"| {scenario['scenario']} | {scenario['sample_count']} | {p50} | "
                f"{p95} ({ratio}) | {scenario['interactive_sample_count']} | "
                f"{interactive_p50} | {interactive_p95} | "
                f"{trend_icon} {scenario['status']} |"
            )
    if report["failures"] or report["warnings"]:
        lines.extend(["", "### Findings", ""])
        lines.extend(f"- ❌ {item}" for item in report["failures"])
        lines.extend(f"- ⚠️ {item}" for item in report["warnings"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--budget", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--revision", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    args = parser.parse_args(argv)

    summaries: list[dict[str, Any]] = []
    try:
        for path in args.paths:
            summaries.extend(summarize_file(path))
    except (OSError, ValueError) as exc:
        print(f"[startup-events] ERROR: {exc}", file=sys.stderr)
        return 1

    print("file\tport\tfallback\tstatus_page\twindow_ms\tinteractive_ms\tevents")
    for summary in summaries:
        print(
            f"{summary['file']}\t{summary['backend_port']}\t"
            f"{str(summary['used_fallback']).lower()}\t"
            f"{str(summary['via_status_page']).lower()}\t"
            f"{summary['window_shown_ms']}\t{summary.get('frontend_ready_ms')}\t"
            f"{summary['event_count']}"
        )

    if not args.budget:
        return 0
    try:
        budget = load_budget(args.budget)
        report = evaluate_budget(summaries, budget)
        history = load_history(args.history) if args.history else []
        run_id = args.run_id or datetime.now(timezone.utc).strftime(
            "local-%Y%m%dT%H%M%S.%fZ"
        )
        if args.history and budget.get("trend"):
            report = apply_trends(
                report,
                history,
                budget["trend"],
                current_run_id=run_id,
            )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        markdown = render_markdown(report)
        if args.markdown:
            args.markdown.parent.mkdir(parents=True, exist_ok=True)
            args.markdown.write_text(markdown, encoding="utf-8")
        print(markdown)
        if args.history:
            update_history(
                args.history,
                report,
                run_id=run_id,
                revision=args.revision,
                retention_records=int(
                    budget.get("trend", {}).get("retention_records", 50)
                ),
            )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[startup-budget] ERROR: {exc}", file=sys.stderr)
        return 1
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
