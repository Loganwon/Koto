"""One bounded call to the currently configured provider, without secret output.

Run this before fixture isolation; fixtures deliberately replace credentials.
The parent process imposes a wall deadline as well as the SDK request timeout.
An existing report is reused so a repeated command cannot repeat the probe.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def probe_worker(output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    isolated_environment = {"KOTO_SKIP_BACKGROUND_RUNTIME": "true", "DEEPSEEK_ENABLE_THINKING": "false",
                            "KOTO_TOKEN_USAGE_PATH": str(output.parent / "probe-token-usage.json")}
    previous_environment = {key: os.environ.get(key) for key in isolated_environment}
    previous_logging = logging.root.manager.disable
    os.environ.update(isolated_environment)
    logging.disable(logging.CRITICAL)
    result = {"probe_requests_limit": 1, "requests_attempted": 0, "output_token_cap": 16,
              "request_timeout_seconds": 6, "actual_usage": None, "provider_charge_usd": None,
              "live_task_attempts": 0, "model_quality_verified": False}
    start = time.monotonic()
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            from app.core.llm.runtime_gateway import create_runtime_llm_gateway
            gateway = create_runtime_llm_gateway()
            provider = gateway._provider
            result["provider_type"] = type(provider).__name__
            result["model"] = gateway.model_id
            result["host"] = urlparse(str(getattr(provider, "base_url", "") or "")).hostname
            provider.MAX_RETRIES = 1
            provider.CALL_TIMEOUT = 6
            sdk_client = getattr(provider, "client", None)
            if sdk_client is not None and hasattr(sdk_client, "with_options"):
                provider._client = sdk_client.with_options(timeout=6, max_retries=0)
            result["requests_attempted"] = 1
            response = provider.generate_content(
                prompt="仅回复OK", model=gateway.model_id, stream=False,
                max_tokens=16, timeout=6, temperature=0,
            )
            usage = response.get("usage") if isinstance(response, dict) else None
            if isinstance(usage, dict):
                result["actual_usage"] = {key: int(value) for key, value in usage.items()
                                          if isinstance(value, (int, float)) and not isinstance(value, bool)} or None
            text = str(response.get("content") or "") if isinstance(response, dict) else ""
            result.update(status="connected" if text else "empty_response", response_received=bool(text))
    except Exception as exc:
        types, numbers, cursor, seen = [], [], exc, set()
        while cursor is not None and id(cursor) not in seen:
            seen.add(id(cursor))
            types.append(type(cursor).__name__)
            numbers += [value for value in (getattr(cursor, "errno", None), getattr(cursor, "winerror", None)) if isinstance(value, int)]
            cursor = cursor.__cause__ or cursor.__context__
        network = any(any(word in name.lower() for word in ("connect", "timeout", "socket", "gaierror")) for name in types)
        result.update(status="blocked" if network else "unavailable", response_received=False,
                      error_types=types, os_error_numbers=sorted(set(numbers)),
                      status_code=getattr(exc, "status_code", None),
                      reason="network_connection_unavailable" if network else "configured_provider_unavailable")
    finally:
        logging.disable(previous_logging)
        for key, previous in previous_environment.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
    result["elapsed_seconds"] = round(time.monotonic() - start, 6)
    result["live_group_action"] = "eligible_for_budgeted_tasks" if result.get("status") == "connected" else "stopped_after_probe"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def run_probe(output):
    output = Path(output).resolve()
    if output.exists():
        return json.loads(output.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    try:
        process = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(output)],
                                 cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 timeout=12, check=False)
        if output.exists():
            return json.loads(output.read_text(encoding="utf-8"))
        result = {"status": "blocked", "reason": "probe_worker_failed", "exit_code": process.returncode}
    except subprocess.TimeoutExpired:
        result = {"status": "blocked", "reason": "probe_wall_deadline_exceeded"}
    result.update(probe_requests_limit=1, requests_attempted=1, output_token_cap=16,
                  actual_usage=None, provider_charge_usd=None, live_task_attempts=0,
                  live_group_action="stopped_after_probe", model_quality_verified=False,
                  elapsed_seconds=round(time.monotonic() - start, 6))
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker is not None:
        probe_worker(args.worker)
        return
    if args.output is None:
        parser.error("--output is required")
    print(json.dumps(run_probe(args.output), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
