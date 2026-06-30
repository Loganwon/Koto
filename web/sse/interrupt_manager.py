# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import logging
import threading

_logger = logging.getLogger("koto.sse.interrupt")


class StreamInterruptManager:

    def __init__(self):
        self.interrupts = {}
        self._lock = threading.Lock()

    def _ensure(self, session_name):
        if session_name not in self.interrupts:
            self.interrupts[session_name] = {"flag": False, "event": threading.Event()}
        elif self.interrupts[session_name].get("event") is None:
            self.interrupts[session_name]["event"] = threading.Event()

    def set_interrupt(self, session_name):
        with self._lock:
            self._ensure(session_name)
            self.interrupts[session_name]["flag"] = True
            if self.interrupts[session_name]["event"]:
                self.interrupts[session_name]["event"].set()
        _logger.debug(f"[INTERRUPT] Marked session {session_name} for interruption")

    def is_interrupted(self, session_name):
        with self._lock:
            if session_name not in self.interrupts:
                return False
            record = self.interrupts[session_name]
            event_flag = record.get("event").is_set() if record.get("event") else False
            return bool(record.get("flag")) or event_flag

    def reset(self, session_name):
        with self._lock:
            self._ensure(session_name)
            self.interrupts[session_name]["flag"] = False
            if self.interrupts[session_name]["event"]:
                self.interrupts[session_name]["event"].clear()
        _logger.debug(f"[INTERRUPT] Reset interrupt flag for session {session_name}")

    def get_event(self, session_name):
        with self._lock:
            self._ensure(session_name)
            return self.interrupts[session_name]["event"]

    def cleanup(self, session_name):
        with self._lock:
            if session_name in self.interrupts:
                del self.interrupts[session_name]
