# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

_CANCELLED_RUNS: Dict[str, float] = {}
_CANCEL_LOCK = threading.Lock()
_CANCEL_TTL_SECONDS = 60 * 60


def _clean_run_id(run_id: Any) -> str:
    return str(run_id or "").strip()


def _prune_cancelled_runs(now: Optional[float] = None) -> None:
    current = time.time() if now is None else now
    expired = [
        run_id
        for run_id, ts in _CANCELLED_RUNS.items()
        if current - float(ts or 0) > _CANCEL_TTL_SECONDS
    ]
    for run_id in expired:
        _CANCELLED_RUNS.pop(run_id, None)


def request_cancel(run_id: str) -> bool:
    clean = _clean_run_id(run_id)
    if not clean:
        return False
    with _CANCEL_LOCK:
        _prune_cancelled_runs()
        already_requested = clean in _CANCELLED_RUNS
        _CANCELLED_RUNS[clean] = time.time()
    return not already_requested


def is_cancel_requested(run_id: str) -> bool:
    clean = _clean_run_id(run_id)
    if not clean:
        return False
    with _CANCEL_LOCK:
        _prune_cancelled_runs()
        return clean in _CANCELLED_RUNS
