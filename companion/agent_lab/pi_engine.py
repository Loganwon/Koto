"""Pi core adapter; Koto owns task state, receipts and persistence in this variant."""

import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time


class PiEngine:
    name = "pi"

    def __init__(self, config, *, max_models=60, timeout=240, max_tokens=8192):
        self.config, self.max_models, self.timeout = config, max_models, timeout
        self.max_tokens = max_tokens

    def run(self, broker, prompt, message):
        script = Path(__file__).with_name("pi") / "bridge.mjs"
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Pi验证需要Node.js。")
        process = subprocess.Popen(
            [node, str(script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def send(value):
            process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
            process.stdin.flush()

        inbox = queue.Queue()
        errors = []

        def reader():
            for line in process.stdout:
                inbox.put(line)
            inbox.put(None)

        def err_reader():
            for line in process.stderr:
                errors.append(line[-300:])

        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=err_reader, daemon=True).start()
        send(
            {
                "model": self.config.model,
                "base_url": self.config.base_url,
                "api_key": self.config.api_key,
                "prompt": prompt,
                "message": message,
                "tools": broker.definitions(),
                "max_models": self.max_models,
                "max_tokens": self.max_tokens,
                "messages": broker.store.messages(broker.task, "pi"),
            }
        )
        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                if broker.turn.cancelled.is_set():
                    send({"type": "abort"})
                    raise RuntimeError("任务已停止，进度保留。")
                try:
                    line = inbox.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    raise RuntimeError(
                        "Pi进程提前结束。"
                        + "".join(errors)[-500:].replace(
                            self.config.api_key, "[redacted]"
                        )
                    )
                item = json.loads(line)
                if item["type"] == "tool":
                    send(
                        {
                            "id": item["id"],
                            "result": broker.invoke(item["name"], item["args"]),
                        }
                    )
                elif item["type"] == "persist":
                    broker.store.messages(broker.task, "pi", item["messages"])
                    send({"id": item["id"], "result": {"ok": True}})
                elif item["type"] == "model_permit":
                    from .model_budget import charge

                    charge(
                        broker.turn,
                        "execution",
                        lambda body: broker.store.event(
                            broker.task, "model_budget_used", body
                        ),
                    )
                    broker.turn.model_step += 1
                    broker.store.event(broker.task, "model_requested", {"engine": "pi"})
                    send({"id": item["id"], "result": {"ok": True}})
                elif item["type"] == "event":
                    broker.store.event(broker.task, item["kind"], item["body"])
                elif item["type"] == "done":
                    return item["answer"]
                elif item["type"] == "failed":
                    raise RuntimeError(
                        item["error"].replace(self.config.api_key, "[redacted]")
                    )
            raise TimeoutError("Pi本轮超时，进度保留。")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def close(self):
        pass
