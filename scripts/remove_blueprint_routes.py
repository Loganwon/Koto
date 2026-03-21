#!/usr/bin/env python3
"""
Remove @app.route-decorated functions from web/app.py that have been
migrated to web/blueprints/.

Usage:
    python scripts/remove_blueprint_routes.py [--dry-run]

The script:
  1. Discovers all routes defined in web/blueprints/*.py
  2. Parses web/app.py with Python's ast module to find the exact line ranges
     of every @app.route-decorated function
  3. Removes those functions whose URL matches a blueprint route
  4. Writes cleaned web/app.py (original backed up as web/app.py.bak)
"""

import argparse
import ast
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
APP_PY = REPO_ROOT / "web" / "app.py"
BLUEPRINTS_DIR = REPO_ROOT / "web" / "blueprints"


# ---------------------------------------------------------------------------
# Step 1: Collect all URLs defined in blueprint files
# ---------------------------------------------------------------------------

def discover_blueprint_routes() -> set[str]:
    """Return the set of URL patterns already handled by blueprints."""
    urls: set[str] = set()
    for bp_file in sorted(BLUEPRINTS_DIR.glob("*.py")):
        if bp_file.name.startswith("_"):
            continue
        src = bp_file.read_text(encoding="utf-8")
        # Match @<name>_bp.route("/path" or '/path'
        for m in re.finditer(r'@\w+_bp\.route\(["\']([^"\']+)["\']', src):
            urls.add(m.group(1))
    return urls


# ---------------------------------------------------------------------------
# Step 2: Parse app.py AST to find route function ranges
# ---------------------------------------------------------------------------

class RouteBlock:
    def __init__(self, urls: list[str], first_decorator_line: int, end_line: int):
        self.urls = urls
        self.first_decorator_line = first_decorator_line  # 1-indexed
        self.end_line = end_line                          # 1-indexed inclusive


def find_route_blocks(source: str) -> list[RouteBlock]:
    """Use AST to locate every @app.route-decorated function."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"[ERROR] Cannot parse web/app.py: {e}", file=sys.stderr)
        sys.exit(1)

    blocks: list[RouteBlock] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        urls: list[str] = []
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "route"
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "app"
            ):
                if dec.args:
                    arg = dec.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        urls.append(arg.value)
        if not urls:
            continue
        first_line = min(d.lineno for d in node.decorator_list)
        end_line = getattr(node, "end_lineno", None)
        if end_line is None:
            continue  # Python < 3.8 – skip
        blocks.append(RouteBlock(urls, first_line, end_line))
    return blocks


# ---------------------------------------------------------------------------
# Step 3: Remove matched blocks and clean up blank lines
# ---------------------------------------------------------------------------

def remove_blocks(lines: list[str], to_remove: list[RouteBlock]) -> list[str]:
    """Delete the line ranges corresponding to *to_remove* from *lines*."""
    # Build a set of 0-indexed line numbers to drop
    drop: set[int] = set()
    for block in to_remove:
        for idx in range(block.first_decorator_line - 1, block.end_line):
            drop.add(idx)

    # Also drop any trailing blank lines right after a removed block so we
    # don't accumulate excessive whitespace.
    extra_drop: set[int] = set()
    max_idx = len(lines) - 1
    for block in to_remove:
        cursor = block.end_line  # 0-indexed: first line after block
        while cursor <= max_idx and lines[cursor].strip() == "":
            # Only drop if the lines immediately before (post-removal) are
            # already blank – i.e. avoid removing separators between blocks
            # that are NOT being removed.
            extra_drop.add(cursor)
            cursor += 1
            if cursor > block.end_line + 2:  # keep at most 2 trailing blanks
                break

    keep_lines: list[str] = []
    for i, line in enumerate(lines):
        if i in drop:
            continue
        # Suppress extra blanks after removed blocks only if they'd double up
        if i in extra_drop and keep_lines and keep_lines[-1].strip() == "":
            continue
        keep_lines.append(line)

    return keep_lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be removed without modifying any file.",
    )
    args = parser.parse_args()

    blueprint_urls = discover_blueprint_routes()
    print(f"[INFO] Blueprint routes discovered: {len(blueprint_urls)}")

    source = APP_PY.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    print(f"[INFO] app.py lines before cleanup: {len(lines)}")

    blocks = find_route_blocks(source)
    print(f"[INFO] @app.route blocks found in app.py: {len(blocks)}")

    to_remove: list[RouteBlock] = []
    kept: list[RouteBlock] = []
    for block in blocks:
        match = any(url in blueprint_urls for url in block.urls)
        if match:
            to_remove.append(block)
        else:
            kept.append(block)

    print(f"\n[INFO] Blocks to REMOVE ({len(to_remove)}):")
    for b in sorted(to_remove, key=lambda x: x.first_decorator_line):
        print(f"  L{b.first_decorator_line}-L{b.end_line}  {b.urls}")

    print(f"\n[INFO] Blocks to KEEP ({len(kept)}):")
    for b in sorted(kept, key=lambda x: x.first_decorator_line):
        print(f"  L{b.first_decorator_line}-L{b.end_line}  {b.urls}")

    if args.dry_run:
        lines_removed = sum(b.end_line - b.first_decorator_line + 1 for b in to_remove)
        print(f"\n[DRY-RUN] Would remove ~{lines_removed} lines from app.py")
        return

    if not to_remove:
        print("[INFO] Nothing to remove.")
        return

    # Back up original
    bak_path = APP_PY.with_suffix(".py.bak")
    shutil.copy2(APP_PY, bak_path)
    print(f"\n[INFO] Backup saved: {bak_path}")

    cleaned = remove_blocks(lines, to_remove)
    APP_PY.write_text("".join(cleaned), encoding="utf-8")
    print(f"[INFO] app.py lines after cleanup: {len(cleaned)}")
    print(f"[INFO] Lines removed: {len(lines) - len(cleaned)}")
    print("[OK] Done.")


if __name__ == "__main__":
    main()
