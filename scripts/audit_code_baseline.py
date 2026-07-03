"""Print a lightweight code-audit baseline for the current checkout."""

from __future__ import annotations

import argparse
import ast
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
    "LangGraphAgent": "LangGraphAgent",
    "UnifiedAgent": "UnifiedAgent",
    "FileTaskRuntime": "FileTaskRuntime",
}
DELETED_AGENT_ENTRYPOINTS = ("KotoAgentLoop", "app.core.agent.agent_loop", "agent_loop.py")
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
        "vendor_reference_graph": _vendor_reference_graph(),
        "web_app_top_level_exports": _web_app_exports(),
        "agent_entrypoint_hits": _agent_entrypoint_hits(),
        "agent_production_entrypoint_hits": _agent_production_entrypoint_hits(),
        "deleted_agent_entrypoint_hits": _deleted_agent_entrypoint_hits(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()
    baseline = collect_baseline()
    if args.json:
        print(json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
