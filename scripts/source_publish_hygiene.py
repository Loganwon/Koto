"""Read-only source publication inventory. Never print matched secret values.

The manifest is an input to human-reviewed publication, not git add/push.
Excluded local files are preserved. Existing public Git history is not rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

PRIVATE_PATHS = frozenset(
    {
        "config/.builtin_key",
        "config/jwt_secret.txt",
        "web/config/jwt_secret.txt",
        "config/email_accounts.json",
        "config/context/user_background.json",
        "config/memory_summaries.json",
        "config/file_task_plans.json",
        "config/file_task_followups.json",
        "app/core/llm/_license.py",
    }
)
PRIVATE_PREFIXES = (
    ".git/",
    ".claude/",
    ".codex/",
    ".venv/",
    ".nodeenv/",
    ".koto/",
    "node_modules/",
    "build/",
    "dist/",
    "logs/",
    "chats/",
    "workspace/",
    "uploads/",
    "web/workspace/_index/",
    "web/uploads/",
    "app/core/chats/",
    "app/core/workspace/images/",
    "app/core/workspace/uploads/",
    "companion/artifacts/",
    "companion/exports/",
    "companion/logs/",
    "companion/runs/",
)
CONFIG_DEFAULTS = frozenset(
    {
        "architecture_debt_budget.json",
        "compatibility_debt.json",
        "feature_ownership.json",
        "frontend_asset_budgets.json",
        "p4_quality_gates.json",
        "p5_quality_gates.json",
        "p6_quality_gates.json",
        "packaged_startup_performance_budget.json",
        "route_ownership.json",
        "runtime_entrypoints.json",
        "startup_performance_budget.json",
        "requirements.txt",
        "requirements.lock",
        "requirements-dev.txt",
        "requirements_core.txt",
        "requirements_desktop.txt",
        "requirements_training.txt",
        "build-requirements.lock",
        "context/_TEMPLATE.json.example",
        "divination_data/esports_teams.json",
        "deepseek_config.env.example",
        "gemini_config.env.example",
        "deploy/.env.example",
        "deploy/Dockerfile",
        "deploy/railway.toml",
        "skill_cache/.gitkeep",
    }
)
SOURCE_PREFIXES = (
    "app/",
    "launcher/",
    "src/",
    "web/",
    "scripts/",
    "tests/",
    "docs/",
    "companion/",
    ".github/",
    "screenshots/",
)
SOURCE_SUFFIXES = {
    ".py",
    ".pyi",
    ".typed",
    ".ts",
    ".tsx",
    ".vue",
    ".js",
    ".mjs",
    ".cjs",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".html",
    ".css",
    ".md",
    ".txt",
    ".ps1",
    ".bat",
    ".vbs",
    ".sh",
    ".spec",
    ".iss",
    ".map",
    ".lock",
    ".example",
    ".xml",
}
ASSET_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".wasm",
}
FORBIDDEN_SUFFIXES = {
    ".exe",
    ".zip",
    ".pyd",
    ".so",
    ".dll",
    ".pyc",
    ".pyo",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pfx",
    ".p12",
    ".pem",
    ".key",
    ".docx",
    ".xlsx",
    ".pptx",
    ".pdf",
    ".log",
    ".bak",
}
SECRET_PATTERNS = (
    ("private_key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "github_token",
        re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    ),
    ("provider_key", re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(rb"\bAIza[A-Za-z0-9_-]{30,}\b")),
    ("aws_access_key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
)
PLACEHOLDER = re.compile(
    rb"^(?:sk-)?(?:test|fake|dummy|example|placeholder|your)[_-]", re.I
)


def path_policy(path: str) -> str | None:
    """None permits content scanning; other values exclude without reading."""
    p = PurePosixPath(path.replace("\\", "/"))
    name = p.as_posix()
    lower = name.lower()
    if name == "web/static/univer-dist/assets/sheets-main.js.map":
        return "reproducible_vendor_debug_map"
    if p.is_absolute() or ".." in p.parts or any(":" in part for part in p.parts):
        return "unsafe_path"
    if lower in PRIVATE_PATHS:
        return "private_credential_or_state"
    if name == "koto-sidebar-review.html":
        return "local_review_prototype"
    if name == "build/ChineseSimplified.isl" or name in (
        "data/README.md",
        "web/uploads/.gitkeep",
    ):
        return None
    if (
        lower.startswith(PRIVATE_PREFIXES)
        or "node_modules" in p.parts
        or "__pycache__" in p.parts
    ):
        return "local_runtime_or_build_output"
    if lower.startswith("data/"):
        return "runtime_data"
    if lower.startswith("web/workspace/") and p.suffix.lower() not in {
        ".py",
        ".pyi",
        ".typed",
    }:
        return "workspace_user_document"
    if p.suffix.lower() in FORBIDDEN_SUFFIXES or lower.endswith(
        (".sqlite-wal", ".sqlite-shm")
    ):
        return "binary_runtime_or_private_file"
    if (
        p.name == ".env" or p.name.endswith(".env") or ".env." in p.name
    ) and not name.endswith(".env.example"):
        return "provider_environment"
    if lower.startswith("config/"):
        relative = name[len("config/") :]
        if relative in CONFIG_DEFAULTS or (
            relative.startswith(("hooks/", "tools/")) and p.suffix in {".py", ".md"}
        ):
            return None
        return "unapproved_runtime_configuration"
    if name in {
        "LICENSE",
        "VERSION",
        ".gitignore",
        ".gitattributes",
        ".dockerignore",
        ".flake8",
        ".pre-commit-config.yaml",
        ".coveragerc",
        "Dockerfile",
        "Makefile",
        "docker-compose.yml",
    }:
        return None
    if name.startswith(SOURCE_PREFIXES) and p.name in {
        ".gitkeep",
        ".nojekyll",
        "LICENSE",
        "CODEOWNERS",
    }:
        return None
    if name.startswith(SOURCE_PREFIXES) and (
        p.suffix.lower() in SOURCE_SUFFIXES
        or (
            name.startswith(
                (
                    "web/static/",
                    "src/assets/",
                    "docs/assets/",
                    "screenshots/",
                    "companion/addins/",
                )
            )
            and p.suffix.lower() in ASSET_SUFFIXES
        )
    ):
        return None
    if len(p.parts) == 1 and (
        p.suffix
        in {".py", ".ps1", ".bat", ".vbs", ".spec", ".iss", ".md", ".cfg", ".ini"}
    ):
        return None
    return "manual_classification_required"


def scan_content(data: bytes) -> list[dict]:
    findings = []
    for kind, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(data):
            if PLACEHOLDER.match(match.group()):
                continue
            findings.append(
                {"type": kind, "line": data.count(b"\n", 0, match.start()) + 1}
            )
            if len(findings) >= 20:
                return findings
    return findings


def inventory(root: Path) -> dict:
    def git(*args: str) -> list[str]:
        raw = subprocess.check_output(
            ["git", "-C", str(root), *args], stderr=subprocess.DEVNULL
        )
        return [
            p for p in raw.decode("utf-8", errors="surrogateescape").split("\0") if p
        ]

    tracked = set(git("ls-files", "-z"))
    candidates = tracked | set(git("ls-files", "--others", "--exclude-standard", "-z"))
    included, excluded, missing = [], [], []
    for name in sorted(candidates):
        full = root / name
        if not full.exists():
            if name in tracked:
                missing.append(name)
            continue
        reason = path_policy(name)
        if (
            full.is_symlink()
            or not full.is_file()
            or not full.resolve().is_relative_to(root)
        ):
            reason = "non_regular_or_escaping_file"
        if reason:
            excluded.append(
                {"path": name, "reason": reason, "tracked": name in tracked}
            )
            continue
        size = full.stat().st_size
        if size > 25 * 1024 * 1024:
            excluded.append(
                {
                    "path": name,
                    "reason": "large_file_requires_review",
                    "tracked": name in tracked,
                }
            )
            continue
        data = full.read_bytes()
        findings = scan_content(data)
        if findings:
            excluded.append(
                {
                    "path": name,
                    "reason": "secret_pattern",
                    "findings": findings,
                    "tracked": name in tracked,
                }
            )
            continue
        included.append(
            {
                "path": name,
                "bytes": size,
                "sha256": hashlib.sha256(data).hexdigest(),
                "tracked": name in tracked,
            }
        )
    return {
        "schema_version": 1,
        "read_only": True,
        "secret_values_printed": False,
        "limitations": "Path policy and high-confidence token patterns; not proof of absence of all secrets or history remediation.",
        "tracked_count": len(tracked),
        "publish_files": included,
        "excluded_files": excluded,
        "deleted_tracked_files": missing,
        "publish_count": len(included),
        "excluded_count": len(excluded),
        "tracked_exclusions": sum(row["tracked"] for row in excluded),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if tracked publish candidates are excluded",
    )
    args = parser.parse_args()
    report = inventory(args.source_root.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "publish_count",
                    "excluded_count",
                    "tracked_exclusions",
                    "secret_values_printed",
                )
            }
        )
    )
    return 1 if args.check and report["tracked_exclusions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
