"""Task state and write receipts, independent of model and editor lifetimes."""

from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from companion.contracts import CompanionError, ResultUncertain


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class TaskStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._executing = threading.local()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=20)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, task TEXT, kind TEXT, body TEXT, at REAL);
            CREATE TABLE IF NOT EXISTS actions(task TEXT, id TEXT, fingerprint TEXT, state TEXT, result TEXT, PRIMARY KEY(task,id));
            CREATE TABLE IF NOT EXISTS engine_messages(task TEXT, engine TEXT, body TEXT, PRIMARY KEY(task,engine));
        """)
        self.db.commit()

    @contextmanager
    def running(self, task):
        """One actor per task, including independent processes; reads remain free."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", task):
            raise ValueError("Invalid task id")
        path = Path(self.db.execute("PRAGMA database_list").fetchone()[2]).parent / (
            task + ".runlock"
        )
        with path.open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise CompanionError(
                    "这个任务正在另一个执行器中运行，请先停止或等待。"
                ) from None
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def create(self, goal, *, expected_outputs=(), task_id=None):
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("A user goal is required")
        task_id = task_id or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", task_id):
            raise ValueError("Invalid task id")
        state = {
            "id": task_id,
            "goal": goal,
            "constraints": {},
            "plan": [],
            "expected_outputs": list(expected_outputs),
            "contract_revision": 0,
            "contract_history": [],
            "artifacts": {},
            "edits": [],
            "phase": "active",
            "review": None,
            "turn": 0,
            "epoch": 0,
        }
        with self.lock, self.db:
            self.db.execute("INSERT INTO tasks VALUES(?,?)", (task_id, dumps(state)))
        self.event(task_id, "task_created", {"goal": goal})
        return task_id

    def get(self, task):
        with self.lock:
            row = self.db.execute(
                "SELECT state FROM tasks WHERE id=?", (task,)
            ).fetchone()
        if not row:
            raise KeyError(task)
        return json.loads(row[0])

    def change(self, task, **updates):
        with self.lock, self.db:
            state = self.get(task)
            state.update(updates)
            self.db.execute("UPDATE tasks SET state=? WHERE id=?", (dumps(state), task))
        return state

    def event(self, task, kind, body=None):
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO events(task,kind,body,at) VALUES(?,?,?,?)",
                (task, kind, dumps(body or {}), time.time()),
            )

    def events(self, task, after=0):
        with self.lock:
            rows = self.db.execute(
                "SELECT seq,kind,body,at FROM events WHERE task=? AND seq>? ORDER BY seq",
                (task, after),
            ).fetchall()
        return [
            {"seq": seq, "kind": kind, "body": json.loads(body), "at": at}
            for seq, kind, body, at in rows
        ]

    def begin_turn(
        self,
        task,
        message,
        mode,
        acknowledge=False,
        *,
        interaction="message",
        record_request=True
    ):
        if mode not in ("auto", "read"):
            raise ValueError("mode must be auto or read")
        if type(record_request) is not bool or (
            not record_request and interaction != "continue"
        ):
            raise ValueError(
                "Only an explicit Continue control can omit a content request"
            )
        with self.lock:
            state = self.get(task)
            requests = list(state.get("user_requests", []))
            recorded = {r["turn"] for r in requests}
            # Recover earlier text-bearing Continue messages from the immutable
            # event ledger. Old releases discarded all Continue requirements.
            # New empty UI controls explicitly opt out; no text classifier or
            # message rewriting decides whether a human instruction is real.
            for event in self.events(task):
                if event["kind"] != "user_message":
                    continue
                body = event["body"]
                if type(body.get("turn")) is not int or not isinstance(
                    body.get("message"), str
                ):
                    continue
                if body.get("record_request", True) and body["turn"] not in recorded:
                    requests.append(
                        {
                            "turn": body["turn"],
                            "message": body["message"],
                            "interaction": body.get("interaction", "message"),
                            **({"mode": "read"} if body.get("mode") == "read" else {}),
                        }
                    )
                    recorded.add(body["turn"])
            requests.sort(key=lambda r: r["turn"])
            if self.db.execute(
                "SELECT 1 FROM actions WHERE task=? AND state='started'", (task,)
            ).fetchone():
                state = self.change(task, phase="uncertain")
            if state["phase"] == "uncertain":
                raise ResultUncertain("有操作待核实，请先检查实际文件。")
            phase = (
                state["phase"] if state["phase"] in ("review", "complete") else "active"
            )
            if acknowledge:
                phase = "active"
            state = self.change(
                task,
                turn=state["turn"] + 1,
                epoch=state["epoch"] + 1,
                phase=phase,
                review=None if acknowledge else state["review"],
                user_requests=[
                    *requests,
                    *(
                        [
                            {
                                "turn": state["turn"] + 1,
                                "message": message,
                                "interaction": interaction,
                                **({"mode": "read"} if mode == "read" else {}),
                            }
                        ]
                        if record_request
                        else []
                    ),
                ],
            )
            self.event(
                task,
                "user_message",
                {
                    "message": message,
                    "mode": mode,
                    "turn": state["turn"],
                    "acknowledge": acknowledge,
                    "interaction": interaction,
                    "record_request": record_request,
                },
            )
            return state["turn"], state["epoch"]

    def history(self, task, limit=30):
        return [
            e
            for e in self.events(task)
            if e["kind"] in ("user_message", "assistant_message")
        ][-limit:]

    def checkpoint(self, task, receipt):
        state = self.get(task)
        return self.change(
            task, edits=[*state["edits"], receipt], review=receipt, phase="review"
        )

    def receipt(self, task, receipt, *, updates=None):
        # The artifact manifest and recoverable result share ONE transaction.
        # A crash after this commit but before execute_once's final acknowledgement
        # can be reconciled from actual bytes, without repeating the write.
        with self.lock, self.db:
            state = self.get(task)
            state.update(
                updates
                or {
                    "artifacts": {**state["artifacts"], receipt["name"]: receipt},
                    "phase": "active",
                }
            )
            if receipt.get("previous_sha256"):
                state["drafts"] = {
                    name: draft
                    for name, draft in state.get("drafts", {}).items()
                    if name != receipt["name"]
                }
            state["plan"] = [
                (
                    {**step, "status": "completed"}
                    if step.get("artifact_name") in state["artifacts"]
                    else step
                )
                for step in state["plan"]
            ]
            self.db.execute("UPDATE tasks SET state=? WHERE id=?", (dumps(state), task))
            active = getattr(self._executing, "action", None)
            if active and active[0] == task:
                self.db.execute(
                    "UPDATE actions SET result=? WHERE task=? AND id=? AND state='started'",
                    (dumps(receipt), task, active[1]),
                )

    def recover_file_results(self, task, outputs):
        """Readback only, under the caller's task lease; never retry unknown writes."""
        root = Path(outputs).resolve()
        with self.lock:
            rows = self.db.execute(
                "SELECT id,result FROM actions WHERE task=? AND state='started'",
                (task,),
            ).fetchall()
        recovered = []
        for action_id, encoded in rows:
            if encoded is None:
                continue
            result = json.loads(encoded)
            name = result.get("name")
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or any(c in name for c in "/\\")
            ):
                continue
            path = root / name
            saved = self.get(task)["artifacts"].get(name)
            try:
                valid = (
                    result.get("verified") is True
                    and saved == result
                    and not path.is_symlink()
                    and path.resolve().parent == root
                    and Path(result["path"]).resolve() == path.resolve()
                    and hashlib.sha256(path.read_bytes()).hexdigest()
                    == result["sha256"]
                )
            except (OSError, KeyError, TypeError):
                valid = False
            if not valid:
                continue
            with self.lock, self.db:
                self.db.execute(
                    "UPDATE actions SET state='verified' WHERE task=? AND id=? AND state='started'",
                    (task, action_id),
                )
            recovered.append(action_id)
            self.event(
                task,
                "action_recovered",
                {
                    "id": action_id,
                    "name": name,
                    "sha256": result["sha256"],
                    "method": "persisted_receipt_and_disk_hash",
                },
            )
        if recovered:
            with self.lock:
                pending = self.db.execute(
                    "SELECT 1 FROM actions WHERE task=? AND state='started'", (task,)
                ).fetchone()
            if not pending and self.get(task)["phase"] == "uncertain":
                self.change(
                    task, phase="review" if self.get(task)["review"] else "active"
                )
        return recovered

    def messages(self, task, engine, value=None):
        with self.lock, self.db:
            if value is not None:
                self.db.execute(
                    "INSERT OR REPLACE INTO engine_messages VALUES(?,?,?)",
                    (task, engine, dumps(value)),
                )
                return
            row = self.db.execute(
                "SELECT body FROM engine_messages WHERE task=? AND engine=?",
                (task, engine),
            ).fetchone()
            return json.loads(row[0]) if row else []

    def execute_once(self, task, action_id, arguments, perform):
        fingerprint = hashlib.sha256(dumps(arguments).encode()).hexdigest()
        with self.lock:
            row = self.db.execute(
                "SELECT fingerprint,state,result FROM actions WHERE task=? AND id=?",
                (task, action_id),
            ).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise CompanionError("这个操作编号已经用于另一项修改。")
                if row[1] != "verified":
                    raise ResultUncertain("操作可能已经执行，不自动重放，请核对结果。")
                return json.loads(row[2])
            with self.db:
                self.db.execute(
                    "INSERT INTO actions VALUES(?,?,?,'started',NULL)",
                    (task, action_id, fingerprint),
                )
            self.event(task, "action_started", {"id": action_id})
        # Native RPC checks task permission from its delivery thread. Holding
        # the SQLite mutex while waiting for that RPC deadlocks both threads.
        # The durable 'started' record above rejects concurrent/replayed writes.
        previous_action = getattr(self._executing, "action", None)
        try:
            self._executing.action = (task, action_id)
            result = perform()
        except ResultUncertain:
            self.change(task, phase="uncertain")
            raise
        except CompanionError:
            with self.lock, self.db:
                self.db.execute(
                    "DELETE FROM actions WHERE task=? AND id=?", (task, action_id)
                )
            raise
        except Exception as error:
            # Unknown exceptions after dispatch are never assumed safe to replay.
            self.change(task, phase="uncertain")
            raise ResultUncertain("操作中断，结果待核实。") from error
        finally:
            self._executing.action = previous_action
        with self.lock, self.db:
            self.db.execute(
                "UPDATE actions SET state='verified',result=? WHERE task=? AND id=?",
                (dumps(result), task, action_id),
            )
        self.event(task, "action_verified", {"id": action_id, "result": result})
        return result

    def replay(self, task, action_id, arguments):
        fingerprint = hashlib.sha256(dumps(arguments).encode()).hexdigest()
        with self.lock:
            row = self.db.execute(
                "SELECT fingerprint,state,result FROM actions WHERE task=? AND id=?",
                (task, action_id),
            ).fetchone()
        if row is None:
            return None
        if row[0] != fingerprint:
            raise CompanionError("操作编号的内容已经改变，请为新动作使用新编号。")
        if row[1] != "verified":
            raise ResultUncertain("操作结果待核实，不自动重放。")
        return json.loads(row[2])

    def close(self):
        self.db.close()
