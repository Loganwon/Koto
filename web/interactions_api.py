from __future__ import annotations

import logging
import random
import time
from typing import Optional

_log = logging.getLogger(__name__)

_INTERACTION_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "error"})
_INTERACTION_SUCCESS_STATES = frozenset({"completed"})
_INTERACTION_FAIL_STATES = frozenset({"failed", "cancelled", "error"})
_INTERACTION_STATUS_MSGS: dict = {
    "active": "Agent 工作中…",
    "running": "Agent 工作中…",
    "queued": "等待队列中，即将开始…",
    "in_progress": "Agent 处理中…",
    "thinking": "Agent 深度思考中…",
    "searching": "Agent 正在检索互联网…",
    "reading": "Agent 正在阅读资料…",
    "generating": "Agent 正在生成回复…",
}


def poll_interaction(
    ia_client,
    interaction_id: str,
    *,
    timeout: float = 900.0,
    initial_sleep: float = 2.0,
    backoff_multiplier: float = 1.5,
    max_sleep: float = 30.0,
    label: str = "",
) -> object:
    if not interaction_id:
        raise RuntimeError(f"[{label or 'poll'}] interaction_id is empty")

    tag = f"[Interactions{':' + label if label else ''}]"
    start = time.monotonic()
    sleep_interval = initial_sleep
    last_status = ""
    poll_count = 0

    _log.info("%s ⏳ job=%s  polling (timeout=%.0fs)", tag, interaction_id, timeout)

    while True:
        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            _log.warning("%s ⌛ job=%s  timeout (%.0fs)", tag, interaction_id, elapsed)
            try:
                ia_client.interactions.cancel(interaction_id)
            except Exception as ce:
                _log.debug("%s cancel failed: %s", tag, ce)
            raise TimeoutError(
                f"Interactions API timeout ({timeout:.0f}s) job={interaction_id}"
            )

        try:
            interaction = ia_client.interactions.get(interaction_id)
        except Exception as poll_err:
            _log.warning("%s job=%s  poll failed (#%d): %s", tag, interaction_id, poll_count, poll_err)
            time.sleep(min(sleep_interval, 10.0))
            continue

        status = str(getattr(interaction, "status", "") or "").lower().strip()
        poll_count += 1

        if status != last_status:
            msg = _INTERACTION_STATUS_MSGS.get(status, f"status: {status!r}")
            _log.info("%s 🔄 job=%s  [poll#%d | %.0fs] %s", tag, interaction_id, poll_count, elapsed, msg)
            last_status = status

        if status in _INTERACTION_TERMINAL_STATES:
            if status in _INTERACTION_SUCCESS_STATES:
                _log.info("%s ✅ job=%s  done (total=%.1fs, polls=%d)", tag, interaction_id, elapsed, poll_count)
                return interaction
            err_detail = getattr(interaction, "error", None) or status
            _log.error("%s ❌ job=%s  failed status=%s detail=%s", tag, interaction_id, status, err_detail)
            raise RuntimeError(f"Interactions API job failed (status={status}, detail={err_detail})")

        jitter = sleep_interval * 0.25 * (random.random() * 2 - 1)
        actual_sleep = max(1.0, min(sleep_interval + jitter, max_sleep))
        remaining = timeout - elapsed
        actual_sleep = min(actual_sleep, max(0.5, remaining - 0.1))

        _log.debug("%s job=%s  wait %.1fs ...", tag, interaction_id, actual_sleep)
        time.sleep(actual_sleep)
        sleep_interval = min(sleep_interval * backoff_multiplier, max_sleep)


def extract_interaction_text(interaction) -> str:
    def _walk(obj) -> list:
        if obj is None:
            return []
        if isinstance(obj, str):
            s = obj.strip()
            return [s] if s else []
        if isinstance(obj, dict):
            results = []
            for key in ("output_text", "text", "content"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    results.append(val.strip())
                    return results
            for val in obj.values():
                results.extend(_walk(val))
            return results
        if isinstance(obj, (list, tuple)):
            results = []
            for item in obj:
                results.extend(_walk(item))
            return results
        if hasattr(obj, "model_dump"):
            try:
                return _walk(obj.model_dump())
            except Exception:
                pass
        if hasattr(obj, "text") and obj.text:
            return [str(obj.text).strip()]
        if hasattr(obj, "parts"):
            results = []
            for p in obj.parts or []:
                results.extend(_walk(p))
            return results
        if hasattr(obj, "outputs"):
            results = []
            for o in obj.outputs or []:
                results.extend(_walk(o))
            return results
        return []

    parts = _walk(getattr(interaction, "outputs", None))
    if not parts:
        parts = _walk(interaction)

    seen: set = set()
    deduped = []
    for p in parts:
        if p not in seen:
            deduped.append(p)
            seen.add(p)
    return "\n".join(deduped).strip()
