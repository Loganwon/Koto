# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""stdio bridge for Koto's WebSocket MCP endpoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from typing import Any


class StdioMCPBridge:
    def __init__(self, url: str, timeout: float = 30.0, api_key: str = "") -> None:
        self.url = url
        self.timeout = timeout
        self.api_key = api_key
        self._ws: Any = None
        self._pending: dict[Any, threading.Event] = {}
        self._responses: dict[Any, str] = {}
        self._lock = threading.RLock()

    def _connect(self) -> None:
        if self._ws is not None:
            return
        try:
            import websocket
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("websocket-client is required for koto_mcp_cli") from exc
        headers = []
        if self.api_key:
            headers.append(f"X-Koto-MCP-Key: {self.api_key}")
        self._ws = websocket.create_connection(self.url, timeout=self.timeout, header=headers)

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._connect()
        req_id = payload.get("id")
        if req_id is None:
            self._ws.send(json.dumps(payload, ensure_ascii=False))
            return {}
        event = threading.Event()
        with self._lock:
            self._pending[req_id] = event
        self._ws.send(json.dumps(payload, ensure_ascii=False))
        if not event.wait(self.timeout):
            with self._lock:
                raw = self._responses.pop(req_id, None)
                self._pending.pop(req_id, None)
            if raw is None:
                raise TimeoutError(f"timed out waiting for MCP response id={req_id}")
        else:
            with self._lock:
                raw = self._responses.pop(req_id, None)
        if raw is None:
            raise TimeoutError(f"missing MCP response id={req_id}")
        return json.loads(raw)

    def _read_ws(self) -> None:
        while True:
            raw = self._ws.recv()
            payload = json.loads(raw)
            req_id = payload.get("id")
            with self._lock:
                self._responses[req_id] = raw
                event = self._pending.pop(req_id, None)
            if event:
                event.set()

    def _write_response(self, payload: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def _read_stdin(self) -> None:
        for line in sys.stdin:
            line = line.strip().lstrip("\ufeff")
            if not line:
                continue
            try:
                response = self._request(json.loads(line))
            except Exception as exc:
                try:
                    req_id = json.loads(line).get("id")
                except Exception:
                    req_id = None
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": str(exc)},
                }
            if response:
                self._write_response(response)

    def run(self) -> None:
        self._connect()
        reader = threading.Thread(target=self._read_ws, daemon=True)
        reader.start()
        self._read_stdin()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:5000/ws/mcp")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--api-key", default=os.environ.get("KOTO_MCP_API_KEY", ""))
    args = parser.parse_args()
    StdioMCPBridge(args.url, timeout=args.timeout, api_key=args.api_key).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
