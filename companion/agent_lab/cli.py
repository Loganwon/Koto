"""An opt-in local task runner. Does not attach to any native Office process."""

import argparse
import json
from pathlib import Path

from companion.config import config_from_key_file
from .store import TaskStore
from .tools import JsonDocument, ToolBroker
from .runtime import LabSession, WriteVerifier


def open_session(
    folder,
    engine,
    config,
    *,
    goal=None,
    task=None,
    expected_outputs=(),
    compact_messages=None
):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    workspace = folder / "references"
    workspace.mkdir(exist_ok=True)
    store = TaskStore(folder / "tasks.sqlite3")
    if task is None:
        task = store.create(goal, expected_outputs=expected_outputs)
        (folder / "task.json").write_text(
            json.dumps({"task": task, "engine": engine}), encoding="utf-8"
        )
    document = JsonDocument(
        folder / "document.json", ["甲方将在全部验收完成之后再进行付款。"]
    )
    broker = ToolBroker(
        store,
        task,
        workspace,
        folder / "outputs",
        document,
        WriteVerifier(config, store, task),
    )
    if engine == "deepagents":
        from .deep_engine import DeepEngine

        runtime = DeepEngine(
            config, folder / "checkpoints.sqlite3", compact_messages=compact_messages
        )
    elif engine == "pi":
        from .pi_engine import PiEngine

        runtime = PiEngine(config)
    else:
        raise ValueError(engine)
    return LabSession(store, task, broker, runtime)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--engine", choices=("deepagents", "pi"), required=True)
    parser.add_argument("--api-key-file", required=True)
    parser.add_argument("--goal")
    parser.add_argument("--message", required=True)
    parser.add_argument("--task")
    parser.add_argument("--mode", choices=("read", "auto"), default="auto")
    parser.add_argument("--acknowledge", action="store_true")
    parser.add_argument("--require-output", action="append", default=[])
    args = parser.parse_args()
    session = open_session(
        args.directory,
        args.engine,
        config_from_key_file(args.api_key_file),
        goal=args.goal,
        task=args.task,
        expected_outputs=args.require_output,
    )
    try:
        print(
            json.dumps(
                session.send(
                    args.message, mode=args.mode, acknowledge=args.acknowledge
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        session.close()
        session.store.close()


if __name__ == "__main__":
    main()
