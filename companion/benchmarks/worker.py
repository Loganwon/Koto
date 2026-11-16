"""One isolated real-model run. Credentials stay in process memory."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import threading

from companion.config import config_from_key_file
from companion.agent_lab.store import TaskStore
from companion.agent_lab.tools import JsonDocument, ToolBroker
from companion.agent_lab.runtime import LabSession, WriteVerifier


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def hashes(folder):
    return {p.name: digest(p) for p in folder.iterdir() if p.is_file()}


def texts(folder):
    """Independent saved prose snapshots for turn-by-turn quality grading."""
    from companion.file_readers import parse_file

    values = {}
    for path in folder.iterdir():
        if path.suffix.lower() in {".docx", ".pptx"}:
            content = parse_file(path).text
            values[path.name] = {
                "text": content[:100000],
                "truncated": len(content) > 100000,
            }
    return values


def run(root, name, engine, repeat, key_file):
    spec = json.loads((root / "cases.json").read_text(encoding="utf-8"))[name]
    folder = root / f"{engine}-{name}-{repeat}"
    folder.mkdir()  # Never overwrite an earlier attempt.
    refs = folder / "references"
    refs.mkdir()
    for filename in spec["sources"]:
        shutil.copy2(root / "inputs" / filename, refs / filename)
    document = JsonDocument(
        folder / "document.json",
        list(spec.get("document", {"0": "未授权修改正文。"}).values()),
    )
    config = config_from_key_file(key_file)
    store = TaskStore(folder / "tasks.sqlite3")
    task = store.create(spec["turns"][0]["message"], expected_outputs=spec["outputs"])
    broker = ToolBroker(
        store,
        task,
        refs,
        folder / "outputs",
        document,
        WriteVerifier(config, store, task),
    )
    if engine == "koto":
        from companion.agent_lab.deep_engine import DeepEngine

        runtime = DeepEngine(config, folder / "checkpoints.sqlite3")
    elif engine == "pi":
        from companion.agent_lab.pi_engine import PiEngine

        runtime = PiEngine(config)
    elif engine == "smolagents":
        from .smol_engine import SmolEngine

        runtime = SmolEngine(config)
    else:
        raise ValueError(engine)
    session = LabSession(store, task, broker, runtime)
    result = {
        "engine": engine,
        "case": name,
        "repeat": repeat,
        "task": task,
        "turns": [],
        "limits_per_turn": {
            "window_seconds": 600,
            "max_progress_windows": 2,
            "model_requests_total": 60,
            "tool_calls_total": 100,
        },
        "code_sha256": {
            str(p.relative_to(Path(__file__).resolve().parents[2])): digest(p)
            for p in (Path(__file__).resolve().parents[1] / "agent_lab").glob("*.py")
        },
    }
    started = time.monotonic()
    save(folder / "progress.json", {"status": "running", "turn": 0})
    try:
        for number, turn in enumerate(spec["turns"]):
            turn = dict(turn)
            stop_after = turn.pop("stop_after_change", None)
            item = {
                "number": number,
                "request": turn,
                "before": hashes(broker.outputs),
                "document_before": document.contents(),
            }
            tick = time.monotonic()
            monitor_done, interrupted = threading.Event(), {}
            monitor_thread = None
            if stop_after:
                baseline = (
                    store.get(task)["artifacts"].get(stop_after, {}).get("sha256")
                )

                def monitor():
                    while not monitor_done.wait(0.02):
                        current = store.get(task)
                        receipt = current["artifacts"].get(stop_after)
                        if receipt and receipt["sha256"] != baseline:
                            interrupted.update(
                                task=task,
                                phase=current["phase"],
                                artifacts=dict(current["artifacts"]),
                            )
                            session.stop()
                            return

                monitor_thread = threading.Thread(target=monitor, daemon=True)
                monitor_thread.start()
            try:
                item["result"] = session.send(**turn)
            except Exception as error:
                diagnostic = (type(error).__name__ + ": " + str(error)).replace(
                    config.api_key, "[redacted]"
                )[:2000]
                if interrupted:
                    item["interruption_error"] = diagnostic
                else:
                    item["error"] = diagnostic
            finally:
                monitor_done.set()
                if monitor_thread is not None:
                    monitor_thread.join(timeout=1)
            if stop_after:
                item["interruption"] = {
                    "requested": bool(interrupted),
                    "after_change": stop_after,
                    **interrupted,
                }
            item.update(
                seconds=round(time.monotonic() - tick, 3),
                after=hashes(broker.outputs),
                document_after=document.contents(),
                artifact_text=texts(broker.outputs),
                state=store.get(task),
            )
            result["turns"].append(item)
            save(folder / "result.json", result)
            save(folder / "events.json", store.events(task))
            save(
                folder / "progress.json",
                {
                    "status": "running",
                    "turn": number + 1,
                    "error": item.get("error"),
                    "phase": item["state"]["phase"],
                },
            )
        result.update(
            seconds=round(time.monotonic() - started, 3),
            references_unchanged=all(
                digest(refs / f) == digest(root / "inputs" / f) for f in spec["sources"]
            ),
        )
        save(folder / "result.json", result)
        save(
            folder / "progress.json",
            {
                "status": "finished",
                "seconds": result["seconds"],
                "errors": sum("error" in t for t in result["turns"]),
            },
        )
    finally:
        session.close()
        store.close()
    print(
        json.dumps(
            {
                "run": folder.name,
                "seconds": result["seconds"],
                "errors": sum("error" in t for t in result["turns"]),
            },
            ensure_ascii=False,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--engine", choices=("koto", "pi", "smolagents"), required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--key-file", default="C:/Users/12524/Desktop/DS_KEY.txt")
    args = parser.parse_args()
    run(args.root, args.case, args.engine, args.repeat, args.key_file)


if __name__ == "__main__":
    main()
