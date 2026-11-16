"""Deduplicate UI actions when an HTTP response is lost after acceptance."""

from concurrent.futures import Future
from collections import OrderedDict
import threading


class RequestCache:
    def __init__(self, limit=128):
        self.limit = limit
        self.lock = threading.Lock()
        self.entries = OrderedDict()
        self.barriers = {}
        self.stops = {}

    def ordered(self, channel, method, order, action):
        if method not in (
            "submit",
            "start",
            "advance",
            "revise",
            "retry",
            "stop",
            "prepare_task",
            "execute_plan",
            "task_turn",
            "adjust_plan",
        ):
            return action()
        with self.lock:
            barrier = self.barriers.setdefault(channel, threading.Lock())
        with barrier:
            if order > 0 and method != "stop" and order <= self.stops.get(channel, 0):
                return {"ok": False, "error": "这一条旧请求已停止，没有再次执行。"}
            if method == "stop":
                self.stops[channel] = max(order, self.stops.get(channel, 0))
            return action()

    def run(self, key, signature, action):
        with self.lock:
            existing = self.entries.get(key)
            if existing:
                saved_signature, future = existing
                if saved_signature != signature:
                    raise ValueError("Request ID reused with different arguments")
                owner = False
            else:
                future = Future()
                self.entries[key] = (signature, future)
                owner = True
                while len(self.entries) > self.limit:
                    candidate = next(
                        (
                            name
                            for name, (_, value) in self.entries.items()
                            if value.done()
                        ),
                        None,
                    )
                    if candidate is None:
                        break
                    self.entries.pop(candidate)
        if owner:
            try:
                future.set_result(action())
            except Exception as error:
                future.set_exception(error)
        return future.result(timeout=25)
