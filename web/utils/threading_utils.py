# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import queue
import threading
import time


def run_with_timeout(fn, timeout_seconds):
    holder = {"result": None, "error": None}

    def _runner():
        try:
            holder["result"] = fn()
        except Exception as e:
            holder["error"] = e

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout_seconds)
    if t.is_alive():
        return None, TimeoutError(f"Timeout after {timeout_seconds}s"), True
    return holder["result"], holder["error"], False


def run_with_heartbeat(
    fn, start_time, heartbeat_callback, heartbeat_interval=5, timeout_seconds=90
):
    result_queue = queue.Queue()

    def worker():
        try:
            result = fn()
            result_queue.put(("success", result))
        except Exception as e:
            result_queue.put(("error", e))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    last_heartbeat = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            return None, TimeoutError(f"操作超时 ({int(elapsed)}s)"), True

        try:
            status, data = result_queue.get(timeout=1.0)
            if status == "success":
                return data, None, False
            else:
                return None, data, False
        except queue.Empty:
            current_time = time.time()
            if current_time - last_heartbeat >= heartbeat_interval:
                heartbeat_callback(int(current_time - start_time))
                last_heartbeat = current_time


def stream_with_keepalive(
    response_stream, start_time, keepalive_interval=5, max_wait_first_token=60
):
    chunk_queue = queue.Queue()
    first_chunk_received = threading.Event()
    stream_done = threading.Event()
    stream_error = {"error": None}

    def stream_reader():
        try:
            for chunk in response_stream:
                chunk_queue.put(("chunk", chunk))
                first_chunk_received.set()
            chunk_queue.put(("done", None))
        except Exception as e:
            stream_error["error"] = e
            chunk_queue.put(("error", e))
        finally:
            stream_done.set()

    reader_thread = threading.Thread(target=stream_reader, daemon=True)
    reader_thread.start()

    last_heartbeat = time.time()

    while True:
        if not first_chunk_received.is_set():
            elapsed = time.time() - start_time
            if elapsed > max_wait_first_token:
                yield ("timeout", f"等待响应超时 ({int(elapsed)}s)")
                return

        try:
            item_type, item_data = chunk_queue.get(timeout=1.0)

            if item_type == "chunk":
                yield ("chunk", item_data)
            elif item_type == "done":
                return
            elif item_type == "error":
                raise item_data

        except queue.Empty:
            current_time = time.time()
            if current_time - last_heartbeat >= keepalive_interval:
                elapsed = int(current_time - start_time)
                yield ("heartbeat", elapsed)
                last_heartbeat = current_time

            if stream_done.is_set() and chunk_queue.empty():
                if stream_error["error"]:
                    raise stream_error["error"]
                return
