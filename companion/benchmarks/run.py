"""Freeze requests and input copies, then dispatch independent framework runs."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone, timedelta

from .cases import CASES

PROJECT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(root):
    root.mkdir(parents=True, exist_ok=False)
    inputs = root / "inputs"
    inputs.mkdir()
    sources = {}
    for filename in sorted({f for c in CASES.values() for f in c["sources"]}):
        original = PROJECT / "workspace" / filename
        shutil.copy2(original, inputs / filename)
        sources[filename] = {"original": str(original), "sha256": digest(original)}
    files = list((PROJECT / "companion/agent_lab").glob("*.py")) + list(
        (PROJECT / "companion/benchmarks").glob("*.py")
    )
    files += [
        PROJECT / "companion/agent_lab/pi/bridge.mjs",
        PROJECT / "companion/agent_lab/pi/package-lock.json",
    ]
    files += [
        PROJECT / "companion" / n
        for n in (
            "file_actions.py",
            "file_readers.py",
            "model.py",
            "config.py",
            "workspace.py",
            "harness.py",
            "contracts.py",
        )
    ]
    manifest = {
        "date": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
        "model": "deepseek-chat",
        "temperature": 0,
        "repeats": 1,
        "limits_per_turn": {
            "model_requests": 60,
            "tool_calls": 100,
            "seconds": 240,
            "max_output_tokens": 8192,
        },
        "sources": sources,
        "code": {str(p.relative_to(PROJECT)): digest(p) for p in files if p.is_file()},
        "engines": {
            "koto": "deepagents 0.7.28 / LangGraph 1.2.16",
            "pi": "@earendil-works/pi-agent-core 1.3.0",
            "smolagents": "smolagents.ToolCallingAgent 1.26.0",
        },
        "scope": "Same Koto tools, verifier, task ledger, user requests and file snapshots. Framework orchestration comparison; not a whole-product ranking. Editor case is JsonDocument, not native Office.",
    }
    (root / "cases.json").write_text(
        json.dumps(CASES, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def dispatch(root, engine, case):
    python = (
        PROJECT
        / (".venv-agent-bench" if engine == "smolagents" else ".venv-agent")
        / "Scripts/python.exe"
    )
    folder = root / f"{engine}-{case}-1"
    if folder.exists():
        return {"run": folder.name, "status": "exists"}
    command = [
        str(python),
        "-m",
        "companion.benchmarks.worker",
        "--root",
        str(root),
        "--engine",
        engine,
        "--case",
        case,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=1100,
        )
        (root / (folder.name + ".log")).write_text(
            completed.stdout[-12000:] + completed.stderr[-12000:], encoding="utf-8"
        )
        return {"run": folder.name, "returncode": completed.returncode}
    except subprocess.TimeoutExpired:
        return {"run": folder.name, "error": "worker timeout"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--engines", nargs="+", default=["koto", "pi", "smolagents"])
    parser.add_argument("--cases", nargs="+", default=list(CASES))
    args = parser.parse_args()
    if args.freeze:
        freeze(args.root)
    # Three isolated model/file jobs; no shared task or writable source.
    jobs = [(e, c) for c in args.cases for e in args.engines]
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [pool.submit(dispatch, args.root, e, c) for e, c in jobs]
        for future in as_completed(tasks):
            print(json.dumps(future.result(), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
