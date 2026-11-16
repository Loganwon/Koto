"""Create deterministic review batches for the current Git worktree.

The plan is read-only with respect to source files: it never stages, commits,
deletes, or rewrites worktree content.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Change:
    path: str
    git_status: str
    batch: str
    untracked: bool
    risk_flags: tuple[str, ...]
    previous_path: str | None = None


BATCHES: dict[str, dict[str, object]] = {
    "01_release_and_governance": {
        "title": "Release, configuration, and governance",
        "guidance": "Review release contracts, CI, configuration defaults, and repository policy first.",
    },
    "02_agent_and_platform_core": {
        "title": "Agent kernel and platform core",
        "guidance": "Review runtime ownership, tools, MCP, plugin protocol, collaboration, and workspace boundaries together.",
    },
    "03_file_llm_and_services": {
        "title": "File, LLM, API, and domain services",
        "guidance": "Review backend service migrations, file processing, providers, and API contracts.",
    },
    "04_web_backend": {
        "title": "Web transport and server runtime",
        "guidance": "Review Flask blueprints, chat streaming, knowledge, document, and workspace server owners.",
    },
    "05_frontend_source": {
        "title": "Frontend source and templates",
        "guidance": "Review TypeScript, Vue/editor runtime, templates, and authored styles before generated bundles.",
    },
    "06_generated_frontend": {
        "title": "Generated frontend bundles",
        "guidance": "Regenerate from the reviewed frontend source and verify byte parity; do not hand-edit bundles.",
    },
    "07_desktop_and_launcher": {
        "title": "Desktop launcher and packaging runtime",
        "guidance": "Review Windows desktop startup, external-open handoff, and frozen runtime integration.",
    },
    "08_tests": {
        "title": "Regression and release tests",
        "guidance": "Review tests with their owning product batches; this batch is an inventory boundary, not a recommendation to separate behavior from tests.",
    },
    "09_current_documentation": {
        "title": "Current documentation and design records",
        "guidance": "Keep only documentation that describes the supported implementation or active design decisions.",
    },
    "10_archived_documentation": {
        "title": "Archived historical documentation",
        "guidance": "Confirm historical files are clearly archived and contain no secrets or current release claims.",
    },
    "99_manual_classification": {
        "title": "Manual classification required",
        "guidance": "Resolve every path in this batch before staging a formal source snapshot.",
    },
}


def run_git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", os.fspath(root), *args], stderr=subprocess.DEVNULL
    )


def worktree_changes(root: Path) -> list[tuple[str, str, str | None]]:
    payload = run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    records = payload.decode("utf-8", errors="surrogateescape").split("\0")
    changes: list[tuple[str, str, str | None]] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            raise ValueError(f"unexpected Git porcelain record: {record!r}")
        status = record[:2]
        path = record[3:].replace("\\", "/")
        previous_path = None
        if "R" in status or "C" in status:
            if index >= len(records) or not records[index]:
                raise ValueError(f"rename/copy record is missing its source path: {record!r}")
            previous_path = records[index].replace("\\", "/")
            index += 1
        changes.append((status, path, previous_path))
    return changes


def classify(path: str) -> str:
    if path.startswith("docs/archive/"):
        return "10_archived_documentation"
    if path.startswith("tests/"):
        return "08_tests"
    if (
        path.startswith("web/static/js/build/")
        or re.match(r"^web/static/js/[^/]*bundle[.]js(?:[.]map)?$", path)
    ):
        return "06_generated_frontend"
    if path.startswith(("web/src/", "web/templates/", "web/tiptap-editor/", "web/univer-editor/")):
        return "05_frontend_source"
    if path.startswith("web/static/") and Path(path).suffix.lower() in {
        ".css",
        ".html",
        ".js",
        ".map",
    }:
        return "05_frontend_source"
    if path.startswith("web/"):
        return "04_web_backend"
    if path.startswith(
        (
            "app/core/agent/",
            "app/core/collaboration/",
            "app/core/information/",
            "app/core/mcp/",
            "app/core/plugin_protocol/",
            "app/core/toolkits/",
            "app/core/workflow/",
            "app/core/workspace/",
        )
    ):
        return "02_agent_and_platform_core"
    if path.startswith("app/"):
        return "03_file_llm_and_services"
    if path.startswith(("launcher/", "src/")) or path in {
        "Koto_Start.ps1",
        "Koto_Start.vbs",
    }:
        return "07_desktop_and_launcher"
    if path.startswith(("docs/", ".codex/designs/")) or path in {
        "README.md",
        "ARCHITECTURE.md",
        "data/README.md",
    }:
        return "09_current_documentation"
    if path.startswith((".github/", "scripts/", "config/", "build/")) or path in {
        ".gitignore",
        "AGENTS.md",
        "Build_Release.ps1",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "VERSION",
        "build_config.py",
        "build_cython.py",
        "koto.spec",
        "koto_installer.iss",
        "local_model_installer.spec",
        "pytest.ini",
        "setup.cfg",
    }:
        return "01_release_and_governance"
    return "99_manual_classification"


def risks(root: Path, path: str, *, untracked: bool) -> tuple[str, ...]:
    if not untracked:
        return ()
    flags: list[str] = []
    lowered = path.lower()
    if re.search(r"(^|[/_.-])(secret|token|password|private[_-]?key|api[_-]?key)([/_.-]|$)", lowered):
        flags.append("secret_like_name")
    suffix = Path(path).suffix.lower()
    if suffix in {".db", ".sqlite", ".sqlite3", ".pem", ".pfx", ".key", ".env"}:
        flags.append("sensitive_or_runtime_extension")
    full_path = root / Path(path)
    if full_path.is_file() and full_path.stat().st_size > 1_000_000:
        flags.append("large_untracked_file")
    return tuple(flags)


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Koto source snapshot review plan",
        "",
        f"- Pending paths: **{report['pending_count']}**",
        f"- Tracked changes: **{report['tracked_count']}**",
        f"- Untracked paths: **{report['untracked_count']}**",
        f"- Manual classification paths: **{report['manual_classification_count']}**",
        f"- Risk-flagged untracked paths: **{report['risk_flagged_count']}**",
        f"- Generated: {report['generated_at']}",
        "",
        "> This report never stages, commits, deletes, or rewrites source files.",
        "",
        "## Recommended review order",
        "",
        "| Batch | Paths | Untracked | Deleted | Purpose |",
        "|---|---:|---:|---:|---|",
    ]
    batch_rows = report["batches"]
    assert isinstance(batch_rows, list)
    for batch in batch_rows:
        assert isinstance(batch, dict)
        lines.append(
            f"| `{batch['id']}` | {batch['path_count']} | {batch['untracked_count']} | "
            f"{batch['deleted_count']} | {batch['title']} |"
        )
    lines.extend(["", "## Batch details", ""])
    for batch in batch_rows:
        assert isinstance(batch, dict)
        lines.extend(
            [
                f"### {batch['id']} — {batch['title']}",
                "",
                str(batch["guidance"]),
                "",
                "<details>",
                f"<summary>{batch['path_count']} paths</summary>",
                "",
                "```text",
            ]
        )
        for item in batch["changes"]:
            assert isinstance(item, dict)
            risk = f" [{', '.join(item['risk_flags'])}]" if item["risk_flags"] else ""
            lines.append(f"{item['git_status']} {item['path']}{risk}")
        lines.extend(["```", "", "</details>", ""])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--fail-on-unclassified", action="store_true")
    parser.add_argument("--fail-on-risk", action="store_true")
    args = parser.parse_args()

    root = args.source_root.resolve()
    raw_changes = worktree_changes(root)
    changes = [
        Change(
            path=path,
            git_status=status,
            batch=classify(path),
            untracked=status == "??",
            risk_flags=risks(root, path, untracked=status == "??"),
            previous_path=previous_path,
        )
        for status, path, previous_path in raw_changes
    ]
    changes.sort(key=lambda item: (item.batch, item.path.casefold()))
    counts = Counter(item.batch for item in changes)
    batches = []
    for batch_id, metadata in BATCHES.items():
        batch_changes = [item for item in changes if item.batch == batch_id]
        if not batch_changes:
            continue
        batches.append(
            {
                "id": batch_id,
                "title": metadata["title"],
                "guidance": metadata["guidance"],
                "path_count": len(batch_changes),
                "untracked_count": sum(item.untracked for item in batch_changes),
                "deleted_count": sum("D" in item.git_status for item in batch_changes),
                "changes": [asdict(item) for item in batch_changes],
            }
        )

    report: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_root": os.fspath(root),
        "pending_count": len(changes),
        "tracked_count": sum(not item.untracked for item in changes),
        "untracked_count": sum(item.untracked for item in changes),
        "manual_classification_count": counts["99_manual_classification"],
        "risk_flagged_count": sum(bool(item.risk_flags) for item in changes),
        "batches": batches,
    }
    json_output = args.json_output if args.json_output.is_absolute() else root / args.json_output
    markdown_output = (
        args.markdown_output if args.markdown_output.is_absolute() else root / args.markdown_output
    )
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_output.write_text(markdown(report), encoding="utf-8")
    print(f"Wrote source snapshot plan: {markdown_output}")
    print(
        "Pending={pending_count}; Untracked={untracked_count}; Manual={manual_classification_count}; Risk={risk_flagged_count}".format(
            **report
        )
    )
    if args.fail_on_unclassified and counts["99_manual_classification"]:
        return 1
    if args.fail_on_risk and report["risk_flagged_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
