"""Fail-closed configuration selection and privacy checks for Windows packages.

Only named, code-owned defaults are copied. Runtime directories are created
empty by the release builder; the builder's local settings are never seeds.
Diagnostics contain paths and reason codes, never configuration values.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath


SHIPPED_CONFIG_FILES = frozenset({
    "architecture_debt_budget.json",
    "compatibility_debt.json",
    "feature_ownership.json",
    "frontend_asset_budgets.json",
    "p6_quality_gates.json",
    "packaged_startup_performance_budget.json",
    "route_ownership.json",
    "runtime_entrypoints.json",
    "startup_performance_budget.json",
})
SAFE_ENV_EXAMPLE = "deepseek_config.env.example"
SAFE_ENV_EXAMPLE_CONTENT = (
    "# Koto DeepSeek configuration template\n"
    "DEEPSEEK_API_KEY=your_api_key_here\n"
    "DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
).encode("utf-8")
EMPTY_CONFIG_DIRS = frozenset({
    "context", "divination_data", "skills", "skill_packs", "tools", "workflows",
})
NEUTRAL_PERSONALITY_MATRIX = {
    "cognitive": {"exploratory": 0.5, "executor": 0.5, "analytical": 0.5, "creative": 0.5},
    "expertise": {}, "goals": [], "recent_themes": [],
    "values": {"efficiency": 0.5, "depth": 0.5, "formality": 0.5},
    "last_updated": None,
}


def validate_env_example(content: bytes) -> None:
    """Accept only the documented placeholder and public provider endpoint."""
    try:
        if len(content) > 16384:
            raise ValueError
        if content.decode("utf-8-sig").replace("\r\n", "\n") != SAFE_ENV_EXAMPLE_CONTENT.decode("utf-8"):
            raise ValueError
    except (UnicodeError, ValueError):
        raise ValueError("Provider example must contain only safe placeholder defaults") from None


def safe_config_files(config_root: str | Path) -> list[Path]:
    """Select named defaults only; do not traverse or read user-owned files."""
    root = Path(config_root).resolve()
    files = []
    for name in sorted(SHIPPED_CONFIG_FILES):
        path = root / name
        if not path.exists():
            continue
        if not path.is_file() or path.resolve().parent != root:
            raise ValueError("Shipped configuration default escapes its configuration root")
        files.append(path)
    return files


def validate_package_entry(relative_path: str, content: bytes | None = None, *, is_dir: bool = False) -> None:
    """Reject user state, credentials, and unapproved config in a package tree/ZIP."""
    normalized = relative_path.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if ".." in path.parts or path.is_absolute() or any(":" in part for part in path.parts):
        raise ValueError("Package entry escapes its package root")
    lowered = normalized.lower()
    if lowered.startswith("_internal/"):
        lowered = lowered[len("_internal/"):]
    if lowered in {"app/core/chats", "app/core/workspace"} or lowered.startswith(("app/core/chats/", "app/core/workspace/")):
        raise ValueError("Package contains personal runtime state")
    if lowered.startswith("app/core/config/user_settings.json"):
        raise ValueError("Package contains personal settings")
    if lowered in {"app/core/llm/_license.py", "app/core/llm/_license.pyc", "app/core/llm/_license.pyo"}:
        raise ValueError("Package contains an unprotected credential module")
    basename = path.name.lower()
    if (basename == ".env" or basename.endswith(".env") or ".env." in basename) and lowered != f"config/{SAFE_ENV_EXAMPLE}":
        raise ValueError("Package contains an unapproved provider environment file")
    if not lowered.startswith("config/"):
        return
    config_relative = lowered[len("config/"):]
    if is_dir:
        if config_relative not in EMPTY_CONFIG_DIRS:
            raise ValueError("Package contains an unapproved configuration directory")
        return
    if config_relative in SHIPPED_CONFIG_FILES:
        return
    if config_relative == SAFE_ENV_EXAMPLE:
        if content is None:
            raise ValueError("Provider example contents must be verified")
        validate_env_example(content)
        return
    if config_relative == "personality_matrix.json":
        try:
            if content is None or json.loads(content) != NEUTRAL_PERSONALITY_MATRIX:
                raise ValueError
        except (UnicodeError, ValueError, TypeError):
            raise ValueError("Package personality defaults contain runtime state") from None
        return
    raise ValueError("Package contains an unapproved configuration file")


def check_package_tree(package_root: str | Path) -> int:
    root = Path(package_root).resolve()
    if not root.is_dir():
        raise ValueError("Package root is missing")
    checked = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if not path.resolve().is_relative_to(root):
            raise ValueError("Package file escapes its package root")
        # The policy reads only allowlisted examples/generated defaults.
        lower = relative.lower()
        content = path.read_bytes() if lower in {
            f"config/{SAFE_ENV_EXAMPLE}", f"_internal/config/{SAFE_ENV_EXAMPLE}",
            "config/personality_matrix.json", "_internal/config/personality_matrix.json",
        } else None
        try:
            validate_package_entry(relative, content)
        except ValueError as exc:
            raise ValueError(f"{exc}: {relative}") from None
        checked += 1
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--package-root", type=Path)
    args = parser.parse_args()
    if (args.source_root is None) == (args.package_root is None):
        parser.error("Choose exactly one of --source-root and --package-root")
    try:
        if args.source_root is not None:
            selected = safe_config_files(args.source_root / "config")
            print(json.dumps({"privacy_policy": "passed", "selected_config_files": [path.name for path in selected], "generated_config_files": [SAFE_ENV_EXAMPLE]}))
        else:
            checked = check_package_tree(args.package_root)
            print(json.dumps({"privacy_policy": "passed", "package_files_checked": checked}))
    except (OSError, ValueError) as exc:
        print(json.dumps({"privacy_policy": "failed", "reason": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
