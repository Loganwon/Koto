#!/usr/bin/env python3
"""
Add -> Response / -> str return type annotations and URL-parameter type hints
to un-annotated Flask route functions in web/blueprints/*.py.

The script is intentionally conservative:
  - Only touches functions preceded by a @xxx_bp.route() decorator
  - Only modifies functions that have NO return annotation yet
  - Adds `: str` to bare URL path parameters (leaves existing annotations alone)
  - Returns `str` for render_template routes, `Response` for everything else
  - Ensures `Response` is in the Flask import when needed

Usage:
    python scripts/add_route_type_hints.py [--dry-run]
"""

import argparse
import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BLUEPRINTS_DIR = REPO_ROOT / "web" / "blueprints"


def _extract_url_params(url: str) -> dict[str, str]:
    """Map path parameter names → Python type string."""
    params: dict[str, str] = {}
    for m in re.finditer(r"<(int:|float:|path:|string:)?(\w+)>", url):
        converter = m.group(1) or ""
        name = m.group(2)
        if converter == "int:":
            params[name] = "int"
        elif converter == "float:":
            params[name] = "float"
        else:
            params[name] = "str"
    return params


def _uses_render_template(funcnode: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the function has a return render_template(...) statement."""
    for child in ast.walk(funcnode):
        if not isinstance(child, ast.Return):
            continue
        val = child.value
        if val is None:
            continue
        # render_template(...)
        if isinstance(val, ast.Call) and isinstance(val.func, ast.Name):
            if val.func.id == "render_template":
                return True
        # render_template(...), status_code  — tuple case
        if isinstance(val, ast.Tuple) and val.elts:
            first = val.elts[0]
            if isinstance(first, ast.Call) and isinstance(first.func, ast.Name):
                if first.func.id == "render_template":
                    return True
    return False


def _annotate_def_line(line: str, url_params: dict[str, str], return_type: str) -> str:
    """
    Annotate a single-line def/async-def with parameter types and return type.
    Multi-line defs are handled by the caller which joins lines first.
    """
    # Add `: type` to each bare URL parameter (no existing annotation)
    for pname, ptype in url_params.items():
        # Match the parameter not already followed by `:` or `=`
        line = re.sub(
            r"\b" + re.escape(pname) + r"\b(?!\s*[=:])",
            f"{pname}: {ptype}",
            line,
        )
    # Append return annotation before the trailing `:`
    # Only if no `->` already present
    if "->" not in line:
        line = re.sub(r"\)\s*:", f") -> {return_type}:", line)
    return line


def _ensure_response_import(source: str) -> str:
    """Add 'Response' to the 'from flask import ...' line if not already present."""
    if "Response" in source:
        return source
    return re.sub(
        r"(from flask import )([^\n]+)",
        lambda m: m.group(0)
        if "Response" in m.group(2)
        else m.group(1) + "Response, " + m.group(2),
        source,
        count=1,
    )


def process_blueprint(path: Path, dry_run: bool) -> int:
    """
    Return the number of functions modified.
    Writes file in-place unless dry_run is True.
    """
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        print(f"  [SKIP] SyntaxError in {path.name}: {exc}", file=sys.stderr)
        return 0

    lines = source.splitlines(keepends=True)
    changes: list[tuple[int, int, str]] = []  # (start_0idx, end_0idx_excl, replacement)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Must have at least one @xxx_bp.route decorator
        route_urls: list[str] = []
        for dec in node.decorator_list:
            if not (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "route"
            ):
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant):
                route_urls.append(str(dec.args[0].value))
        if not route_urls:
            continue

        # Already annotated? skip.
        if node.returns is not None:
            continue

        # Determine return type
        return_type = "str" if _uses_render_template(node) else "Response"

        # Collect URL params across all route URLs for this function
        url_params: dict[str, str] = {}
        for url in route_urls:
            url_params.update(_extract_url_params(url))

        # Locate the def line(s) — handle multi-line signatures
        def_start = node.lineno - 1  # 0-indexed
        # Find closing ): by counting parentheses
        paren = 0
        def_end = def_start
        for i in range(def_start, len(lines)):
            paren += lines[i].count("(") - lines[i].count(")")
            def_end = i
            if paren <= 0:
                break
        def_end += 1  # exclusive

        original_def = "".join(lines[def_start:def_end])
        modified_def = _annotate_def_line(original_def, url_params, return_type)

        if modified_def != original_def:
            changes.append((def_start, def_end, modified_def))

    if not changes:
        return 0

    needs_response = any("-> Response" in repl for _, __, repl in changes)

    print(f"  {path.name}: {len(changes)} function(s) annotated")
    if dry_run:
        for start, _end, repl in changes[:3]:
            print(f"    L{start+1}: {repl.rstrip()[:100]}")
        if len(changes) > 3:
            print(f"    … and {len(changes) - 3} more")
        return len(changes)

    # Apply changes in reverse order to keep indices valid
    for start, end, repl in sorted(changes, reverse=True):
        repl_lines = repl.splitlines(keepends=True)
        if repl_lines and not repl_lines[-1].endswith("\n"):
            repl_lines[-1] += "\n"
        lines[start:end] = repl_lines

    new_src = "".join(lines)
    if needs_response:
        new_src = _ensure_response_import(new_src)

    path.write_text(new_src, encoding="utf-8")
    return len(changes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    total = 0
    bp_files = sorted(BLUEPRINTS_DIR.glob("*.py"))
    for path in bp_files:
        if path.name.startswith("_"):
            continue
        n = process_blueprint(path, dry_run=args.dry_run)
        total += n

    print(f"\n{'[DRY-RUN] Would annotate' if args.dry_run else 'Annotated'} {total} route function(s) across {len(bp_files)} blueprint files.")


if __name__ == "__main__":
    main()
