"""Print a lightweight code-audit baseline for the current checkout."""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache",
    ".pytest_tmp",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "models",
    "node_modules",
}

EXCLUDED_PARTS = {
    "static/vendor",
    "static/js/build",
    "static/univer-dist",
}

CODE_SCAN_ROOTS = ("app", "web", "src")
VENDOR_REFERENCE_ROOTS = ("app", "web")
PRODUCTION_AGENT_SCAN_ROOTS = ("app", "web")
AGENT_ENTRYPOINT_TARGETS = {
    "KernelAgent": "KernelAgent",
    "FileTaskRuntime": "FileTaskRuntime",
}
DELETED_AGENT_ENTRYPOINTS = (
    "UnifiedAgent",
    "app.core.agent.unified_agent",
    "unified_agent.py",
    "TaskAgent",
    "app.core.agent.task_agent",
    "task_agent.py",
    "app.core.skills.skill_runner",
    "skill_runner.py",
    "app.core.agent.doc_agent",
    "doc_agent.py",
    "app.core.agent.doc_event_emitter",
    "doc_event_emitter.py",
    "KotoAgentLoop",
    "app.core.agent.agent_loop",
    "agent_loop.py",
    "DeepResearchAgent",
    "app.core.agent.deep_research",
    "deep_research.py",
    "LangGraphAgent",
    "app.core.agent.langgraph_agent",
    "langgraph_agent.py",
    "MultiAgentOrchestrator",
    "app.core.agent.multi_agent",
    "multi_agent.py",
    "app.core.agent.lifecycle",
    "agent/lifecycle.py",
)
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".ts",
    ".tsx",
    ".yml",
    ".yaml",
}
LARGE_FILE_SUFFIXES = {".css", ".html", ".js", ".py", ".ts", ".tsx"}
LARGE_FILE_TOP_N = 25
LARGE_FILE_THRESHOLDS = (1500, 2000)

BUNDLE_PATHS = (
    "web/static/univer-dist/assets/sheets-main.js",
    "web/static/js/build/workspace-bundle.js",
    "web/static/js/tiptap-docx-bundle.js",
)

ASSET_BUDGETS_PATH = "config/frontend_asset_budgets.json"
ARCHITECTURE_BUDGETS_PATH = "config/architecture_debt_budget.json"
COMPATIBILITY_DEBT_PATH = "config/compatibility_debt.json"
FEATURE_OWNERSHIP_PATH = "config/feature_ownership.json"
ROUTE_OWNERSHIP_PATH = "config/route_ownership.json"
FRONTEND_TEMPLATE_PATH = "web/templates/index.html"
PRODUCT_TEMPLATE_ROOT = "web/templates"
FRONTEND_SOURCE_PATH = "web/src"

INLINE_EVENT_RE = re.compile(
    r"\bon(?:click|mousedown|mouseup|keydown|keyup|change|input|submit|focus|blur|wheel|scroll)\s*=\s*(?:\"[^\"]*\"|'[^']*')",
    re.IGNORECASE,
)
INLINE_SCRIPT_RE = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>", re.IGNORECASE)
EXTERNAL_SCRIPT_RE = re.compile(r"<script\b[^>]*\bsrc\s*=", re.IGNORECASE)
WA_METHOD_RE = re.compile(r"\bWA\.([A-Za-z_$][\w$]*)")
WINDOW_ASSIGNMENT_RE = re.compile(
    r"(?:\bwindow|\(window\s+as\s+any\))\.[A-Za-z_$][\w$]*\s*=(?!=)",
)
WINDOW_ASSIGNMENT_NAME_RE = re.compile(
    r"(?:\bwindow|\(window\s+as\s+any\))\.([A-Za-z_$][\w$]*)\s*=(?!=)",
)
APPROVED_BROWSER_GLOBALS = frozenset(
    {
        "KotoDocxReviewEngineModule",
        "KotoRenderSurface",
        "KotoUiScale",
        "fetch",
    }
)


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if any(part in EXCLUDED_DIRS for part in Path(rel).parts):
        return True
    return any(excluded in rel for excluded in EXCLUDED_PARTS)


def _count_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_dir():
        return _dir_size(path)
    return path.stat().st_size


def _load_asset_budgets() -> dict[str, int]:
    path = ROOT / ASSET_BUDGETS_PATH
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    budgets = data.get("budgets", {})
    if not isinstance(budgets, dict):
        return {}
    return {
        str(rel): int(limit)
        for rel, limit in budgets.items()
        if str(rel).strip() and int(limit) > 0
    }


def _asset_budget_status() -> dict[str, dict[str, int | bool]]:
    status: dict[str, dict[str, int | bool]] = {}
    for rel, budget in _load_asset_budgets().items():
        size = _path_size(ROOT / rel)
        status[rel] = {
            "size": size,
            "budget": budget,
            "remaining": budget - size,
            "over_budget": size > budget,
        }
    return status


def _load_json_object(relative_path: str) -> dict:
    path = ROOT / relative_path
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _frontend_source_files() -> list[Path]:
    root = ROOT / FRONTEND_SOURCE_PATH
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*.ts")
        if path.is_file() and not path.name.endswith(".test.ts")
    )


def _frontend_runtime_debt() -> dict[str, object]:
    template_path = ROOT / FRONTEND_TEMPLATE_PATH
    html = (
        template_path.read_text(encoding="utf-8", errors="ignore")
        if template_path.exists()
        else ""
    )
    inline_events = [match.group(0) for match in INLINE_EVENT_RE.finditer(html)]
    product_template_inline_events: list[str] = []
    product_template_root = ROOT / PRODUCT_TEMPLATE_ROOT
    product_templates = (
        sorted(product_template_root.rglob("*.html"))
        if product_template_root.exists()
        else []
    )
    for product_template in product_templates:
        product_source = product_template.read_text(encoding="utf-8", errors="ignore")
        product_template_inline_events.extend(
            match.group(0) for match in INLINE_EVENT_RE.finditer(product_source)
        )
    inline_wa_events = [event for event in inline_events if "WA." in event]
    wa_methods = sorted(set(WA_METHOD_RE.findall(html)))

    window_assignments = 0
    window_assignment_names: set[str] = set()
    generated_inline_events: list[str] = []
    publish_workspace_api_calls = 0
    window_state_writes = 0
    source_files_over_1000: list[dict[str, int | str]] = []
    for path in _frontend_source_files():
        source = path.read_text(encoding="utf-8", errors="ignore")
        window_assignments += len(WINDOW_ASSIGNMENT_RE.findall(source))
        window_assignment_names.update(WINDOW_ASSIGNMENT_NAME_RE.findall(source))
        generated_inline_events.extend(
            match.group(0) for match in INLINE_EVENT_RE.finditer(source)
        )
        publish_workspace_api_calls += source.count("publishWorkspaceApi(")
        window_state_writes += len(
            re.findall(
                r"(?:\bwindow|\(window\s+as\s+any\))\.state\s*=",
                source,
            )
        )
        lines = len(source.splitlines())
        if lines > 1000:
            source_files_over_1000.append(
                {"path": path.relative_to(ROOT).as_posix(), "lines": lines}
            )

    source_files_over_1000.sort(
        key=lambda item: (-int(item["lines"]), str(item["path"]))
    )
    return {
        "inline_script_tags": len(INLINE_SCRIPT_RE.findall(html)),
        "external_script_tags": len(EXTERNAL_SCRIPT_RE.findall(html)),
        "inline_event_handlers": len(inline_events),
        "product_template_inline_event_handlers": len(
            product_template_inline_events
        ),
        "inline_wa_event_handlers": len(inline_wa_events),
        "inline_wa_method_count": len(wa_methods),
        "inline_wa_methods": wa_methods,
        "window_global_assignments": window_assignments,
        "window_global_assignment_names": sorted(window_assignment_names),
        "unapproved_window_global_assignment_count": len(
            window_assignment_names - APPROVED_BROWSER_GLOBALS
        ),
        "unapproved_window_global_assignments": sorted(
            window_assignment_names - APPROVED_BROWSER_GLOBALS
        ),
        "generated_inline_event_handlers": len(generated_inline_events),
        "window_state_writes": window_state_writes,
        "publish_workspace_api_calls": publish_workspace_api_calls,
        "frontend_source_files_over_1000_count": len(source_files_over_1000),
        "frontend_source_files_over_1000": source_files_over_1000,
    }


def _validate_compatibility_debt(reference_date: dt.date | None = None) -> list[str]:
    data = _load_json_object(COMPATIBILITY_DEBT_PATH)
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("compatibility debt schema_version must be 1")
    entries = data.get("entries")
    if not isinstance(entries, list):
        return [*errors, "compatibility debt entries must be a list"]

    required_text = (
        "id",
        "category",
        "owner",
        "reason",
        "replacement",
        "target_phase",
        "remove_by",
        "delete_when",
    )
    seen: set[str] = set()
    today = reference_date or dt.date.today()
    for index, entry in enumerate(entries):
        label = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue
        entry_id = str(entry.get("id") or "").strip()
        if entry_id in seen:
            errors.append(f"duplicate compatibility debt id: {entry_id}")
        if entry_id:
            seen.add(entry_id)
        for field in required_text:
            if not str(entry.get(field) or "").strip():
                errors.append(f"{label}.{field} must be non-empty")
        for field in ("paths", "callers", "tests"):
            value = entry.get(field)
            if not isinstance(value, list) or not value:
                errors.append(f"{label}.{field} must be a non-empty list")
        if not re.fullmatch(r"P[1-6]", str(entry.get("target_phase") or "")):
            errors.append(f"{label}.target_phase must be P1..P6")
        try:
            remove_by = dt.date.fromisoformat(str(entry.get("remove_by") or ""))
        except ValueError:
            errors.append(f"{label}.remove_by must use YYYY-MM-DD")
        else:
            if remove_by < today:
                errors.append(f"compatibility debt is overdue: {entry_id}")
        for path in entry.get("paths") or []:
            if not (ROOT / str(path)).exists():
                errors.append(f"{label}.paths missing: {path}")
        for path in entry.get("tests") or []:
            if not (ROOT / str(path)).exists():
                errors.append(f"{label}.tests missing: {path}")
    return errors


def _compatibility_debt_status() -> dict[str, object]:
    data = _load_json_object(COMPATIBILITY_DEBT_PATH)
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    by_phase: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        phase = str(entry.get("target_phase") or "unassigned")
        by_phase[phase] = by_phase.get(phase, 0) + 1
    return {
        "count": len(entries),
        "by_phase": dict(sorted(by_phase.items())),
        "validation_errors": _validate_compatibility_debt(),
    }


def _validate_route_ownership() -> list[str]:
    data = _load_json_object(ROUTE_OWNERSHIP_PATH)
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("route ownership schema_version must be 1")
    families = data.get("families")
    if not isinstance(families, dict) or not families:
        return [*errors, "route ownership families must be a non-empty object"]
    for family, entry in sorted(families.items()):
        label = f"families.{family}"
        if not str(family or "").strip():
            errors.append("route ownership family names must be non-empty")
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue
        if not str(entry.get("feature") or "").strip():
            errors.append(f"{label}.feature must be non-empty")
        if entry.get("tier") not in {"core", "bundled", "optional"}:
            errors.append(f"{label}.tier must be core, bundled or optional")
        owner = str(entry.get("owner") or "").strip()
        if not owner:
            errors.append(f"{label}.owner must be non-empty")
        elif not (ROOT / owner).is_file():
            errors.append(f"{label}.owner missing: {owner}")
    return errors


def _validate_feature_ownership() -> list[str]:
    data = _load_json_object(FEATURE_OWNERSHIP_PATH)
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("feature ownership schema_version must be 1")
    features = data.get("features")
    if not isinstance(features, list):
        return [*errors, "feature ownership features must be a list"]
    seen: set[str] = set()
    for index, feature in enumerate(features):
        label = f"features[{index}]"
        if not isinstance(feature, dict):
            errors.append(f"{label} must be an object")
            continue
        feature_id = str(feature.get("id") or "").strip()
        if not feature_id:
            errors.append(f"{label}.id must be non-empty")
        elif feature_id in seen:
            errors.append(f"duplicate feature id: {feature_id}")
        else:
            seen.add(feature_id)
        if feature.get("release_status") not in {"stable", "beta", "disabled"}:
            errors.append(f"{label}.release_status must be stable, beta, or disabled")
        for field in ("frontend_owners", "backend_owners", "entrypoints", "tests"):
            values = feature.get(field)
            if not isinstance(values, list) or not values:
                errors.append(f"{label}.{field} must be a non-empty list")
                continue
            if field in {"frontend_owners", "backend_owners", "tests"}:
                for path in values:
                    if not (ROOT / str(path)).exists():
                        errors.append(f"{label}.{field} missing: {path}")
        acceptance = feature.get("acceptance")
        if not isinstance(acceptance, list) or not acceptance:
            errors.append(f"{label}.acceptance must be a non-empty list")
        if feature.get("release_status") == "beta":
            known_gaps = feature.get("known_gaps")
            if not isinstance(known_gaps, list) or not known_gaps:
                errors.append(f"{label}.known_gaps must explain beta status")
    return errors


def _architecture_budget_status() -> dict[str, dict[str, int | bool]]:
    config = _load_json_object(ARCHITECTURE_BUDGETS_PATH)
    budgets = config.get("budgets") if isinstance(config.get("budgets"), dict) else {}
    frontend = _frontend_runtime_debt()
    large_summary = _large_file_summary(_large_production_files())
    current = {
        **{key: int(value) for key, value in frontend.items() if isinstance(value, int)},
        **large_summary,
    }
    status: dict[str, dict[str, int | bool]] = {}
    for metric, raw_budget in budgets.items():
        if metric not in current:
            continue
        budget = int(raw_budget)
        value = int(current[metric])
        status[str(metric)] = {
            "value": value,
            "budget": budget,
            "remaining": budget - value,
            "over_budget": value > budget,
        }
    return status


def _vendor_packages() -> dict[str, dict[str, int | str]]:
    vendor_root = ROOT / "web" / "static" / "vendor"
    packages: dict[str, dict[str, int | str]] = {}
    if not vendor_root.exists():
        return packages
    for item in sorted(vendor_root.iterdir(), key=lambda path: path.name.lower()):
        if item.is_dir():
            packages[item.name] = {
                "path": item.relative_to(ROOT).as_posix(),
                "bytes": _dir_size(item),
            }
        elif item.is_file():
            packages[item.name] = {
                "path": item.relative_to(ROOT).as_posix(),
                "bytes": item.stat().st_size,
            }
    return packages


def _vendor_reference_graph() -> dict[str, dict[str, object]]:
    packages = _vendor_packages()
    reference_map: dict[str, list[str]] = {package: [] for package in packages}
    patterns = {
        package: (
            re.compile(rf"(?<![\w.-])vendor/{re.escape(package)}(?:[/'\"?#)]|$)"),
            re.compile(rf"(?<![\w.-])/static/vendor/{re.escape(package)}(?:[/'\"?#)]|$)"),
        )
        for package in packages
    }
    for root_name in VENDOR_REFERENCE_ROOTS:
        base = ROOT / root_name
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or _is_excluded(path):
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            if "vendor/" not in source and "/static/vendor/" not in source:
                continue
            rel = path.relative_to(ROOT).as_posix()
            for package, package_patterns in patterns.items():
                if any(pattern.search(source) for pattern in package_patterns):
                    reference_map[package].append(rel)

    graph: dict[str, dict[str, object]] = {}
    for package, info in packages.items():
        references = reference_map[package]
        graph[package] = {
            "path": info["path"],
            "bytes": info["bytes"],
            "reference_files": references,
            "referenced": bool(references),
        }
    return graph


def _find_todos() -> list[str]:
    matches: list[str] = []
    for scan_root in CODE_SCAN_ROOTS:
        base = ROOT / scan_root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or _is_excluded(path):
                continue
            if path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".css", ".html"}:
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for lineno, line in enumerate(lines, 1):
                if "TODO" in line or "FIXME" in line:
                    rel = path.relative_to(ROOT).as_posix()
                    matches.append(f"{rel}:{lineno}: {line.strip()}")
    return matches


def _large_production_files() -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    for scan_root in CODE_SCAN_ROOTS:
        base = ROOT / scan_root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or _is_excluded(path):
                continue
            if path.suffix.lower() not in LARGE_FILE_SUFFIXES:
                continue
            lines = _count_lines(path)
            rows.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "lines": lines,
                }
            )
    rows.sort(key=lambda item: (-int(item["lines"]), str(item["path"])))
    return rows


def _large_file_summary(rows: list[dict[str, int | str]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for threshold in LARGE_FILE_THRESHOLDS:
        over_threshold = [row for row in rows if int(row["lines"]) >= threshold]
        summary[f"over_{threshold}_count"] = len(over_threshold)
        summary[f"over_{threshold}_lines"] = sum(
            int(row["lines"]) for row in over_threshold
        )
    return summary


def _agent_hit_files(
    scan_roots: tuple[str, ...],
) -> dict[str, list[str]]:
    hits = {key: [] for key in AGENT_ENTRYPOINT_TARGETS}
    for root_name in scan_roots:
        base = ROOT / root_name
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if _is_excluded(path):
                continue
            rel = path.relative_to(ROOT).as_posix()
            source = path.read_text(encoding="utf-8", errors="ignore")
            for key, needle in AGENT_ENTRYPOINT_TARGETS.items():
                if needle in source:
                    hits[key].append(rel)
    return hits


def _agent_entrypoint_hits() -> dict[str, list[str]]:
    return _agent_hit_files(("app", "web", "tests"))


def _agent_production_entrypoint_hits() -> dict[str, list[str]]:
    return _agent_hit_files(PRODUCTION_AGENT_SCAN_ROOTS)


def _deleted_agent_entrypoint_hits() -> dict[str, list[str]]:
    hits = {target: [] for target in DELETED_AGENT_ENTRYPOINTS}
    for root_name in PRODUCTION_AGENT_SCAN_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if _is_excluded(path):
                continue
            rel = path.relative_to(ROOT).as_posix()
            source = path.read_text(encoding="utf-8", errors="ignore")
            for target in DELETED_AGENT_ENTRYPOINTS:
                if target in source:
                    hits[target].append(rel)
    return hits


def _web_app_exports() -> list[str]:
    app_path = ROOT / "web" / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8", errors="ignore"))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return names


def collect_baseline() -> dict:
    agent_top = list((ROOT / "app" / "core" / "agent").glob("*.py"))
    agent_recursive = list((ROOT / "app" / "core" / "agent").rglob("*.py"))
    bundles = {
        rel: (ROOT / rel).stat().st_size if (ROOT / rel).exists() else 0
        for rel in BUNDLE_PATHS
    }
    large_files = _large_production_files()
    return {
        "web_app_lines": _count_lines(ROOT / "web" / "app.py"),
        "agent_py_top_level": len(agent_top),
        "agent_py_recursive": len(agent_recursive),
        "agent_py_recursive_bytes": sum(path.stat().st_size for path in agent_recursive),
        "large_file_summary": _large_file_summary(large_files),
        "large_production_files": large_files[:LARGE_FILE_TOP_N],
        "todo_fixme_count": len(_find_todos()),
        "bundles_bytes": bundles,
        "web_node_modules_bytes": _dir_size(ROOT / "web" / "node_modules"),
        "web_static_vendor_bytes": _dir_size(ROOT / "web" / "static" / "vendor"),
        "asset_budget_status": _asset_budget_status(),
        "architecture_budget_status": _architecture_budget_status(),
        "frontend_runtime_debt": _frontend_runtime_debt(),
        "compatibility_debt": _compatibility_debt_status(),
        "feature_ownership_validation_errors": _validate_feature_ownership(),
        "route_ownership_validation_errors": _validate_route_ownership(),
        "vendor_reference_graph": _vendor_reference_graph(),
        "web_app_top_level_exports": _web_app_exports(),
        "agent_entrypoint_hits": _agent_entrypoint_hits(),
        "agent_production_entrypoint_hits": _agent_production_entrypoint_hits(),
        "deleted_agent_entrypoint_hits": _deleted_agent_entrypoint_hits(),
    }


def _governance_failures(baseline: dict) -> list[str]:
    """Return architecture conditions that must make the audit command fail."""
    failures: list[str] = []
    architecture_budgets = baseline["architecture_budget_status"]
    if not architecture_budgets:
        failures.append("architecture debt budgets are missing or empty")
    failures.extend(
        f"architecture budget exceeded: {metric}"
        for metric, status in architecture_budgets.items()
        if status["over_budget"]
    )
    failures.extend(baseline["compatibility_debt"]["validation_errors"])
    failures.extend(baseline["feature_ownership_validation_errors"])
    failures.extend(baseline["route_ownership_validation_errors"])
    for symbol, paths in baseline["deleted_agent_entrypoint_hits"].items():
        if paths:
            failures.append(f"retired Agent entrypoint returned: {symbol}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()
    baseline = collect_baseline()
    failures = _governance_failures(baseline)
    if args.json:
        print(json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if failures else 0

    print("# Koto Code Audit Baseline")
    print()
    print(f"- web/app.py lines: {baseline['web_app_lines']}")
    print(f"- app/core/agent top-level .py files: {baseline['agent_py_top_level']}")
    print(f"- app/core/agent recursive .py files: {baseline['agent_py_recursive']}")
    print(f"- app/core/agent recursive bytes: {baseline['agent_py_recursive_bytes']}")
    print("- large production files:")
    for key, value in baseline["large_file_summary"].items():
        print(f"  - {key}: {value}")
    for item in baseline["large_production_files"][:10]:
        print(f"  - {item['path']}: {item['lines']} lines")
    print(f"- TODO/FIXME count, filtered: {baseline['todo_fixme_count']}")
    print("- bundle bytes:")
    for rel, size in baseline["bundles_bytes"].items():
        print(f"  - {rel}: {size}")
    print(f"- web/node_modules bytes: {baseline['web_node_modules_bytes']}")
    print(f"- web/static/vendor bytes: {baseline['web_static_vendor_bytes']}")
    print("- frontend asset budgets:")
    for rel, item in baseline["asset_budget_status"].items():
        state = "OVER" if item["over_budget"] else "ok"
        print(f"  - {rel}: {item['size']} / {item['budget']} ({state})")
    print("- frontend runtime debt:")
    for key, value in baseline["frontend_runtime_debt"].items():
        if not isinstance(value, list):
            print(f"  - {key}: {value}")
    print("- architecture debt budgets:")
    for metric, item in baseline["architecture_budget_status"].items():
        state = "OVER" if item["over_budget"] else "ok"
        print(f"  - {metric}: {item['value']} / {item['budget']} ({state})")
    compatibility = baseline["compatibility_debt"]
    print(f"- compatibility debt entries: {compatibility['count']}")
    print(f"- compatibility debt validation errors: {len(compatibility['validation_errors'])}")
    print(
        "- feature ownership validation errors: "
        f"{len(baseline['feature_ownership_validation_errors'])}"
    )
    print(
        "- route ownership validation errors: "
        f"{len(baseline['route_ownership_validation_errors'])}"
    )
    print("- vendor reference graph:")
    for package, item in baseline["vendor_reference_graph"].items():
        state = "referenced" if item["referenced"] else "unreferenced"
        print(f"  - {package}: {item['bytes']} bytes, {state}, refs={len(item['reference_files'])}")
    print(f"- web/app.py top-level exports: {len(baseline['web_app_top_level_exports'])}")
    print("- agent entrypoint hit files:")
    for name, files in baseline["agent_entrypoint_hits"].items():
        print(f"  - {name}: {len(files)}")
    print("- agent production entrypoint hit files:")
    for name, files in baseline["agent_production_entrypoint_hits"].items():
        print(f"  - {name}: {len(files)}")
    print("- deleted agent entrypoint hit files:")
    for name, files in baseline["deleted_agent_entrypoint_hits"].items():
        print(f"  - {name}: {len(files)}")
    if failures:
        print("- governance failures:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
