"""Use provider thinking for bounded JSON planning, without touching tool loops."""

from urllib.parse import urlsplit
import time
from companion.model import ToolCallingModel
from companion.contracts import CompanionError


class PlanningModel(ToolCallingModel):
    def _request_once(self, payload, cancelled, on_delta=None):
        from .model_budget import charge_planning, planning_result

        charge_planning()
        started = time.monotonic()
        try:
            result = super()._request_once(payload, cancelled, on_delta)
        except Exception as error:
            planning_result(None, time.monotonic() - started, error)
            raise
        planning_result(result, time.monotonic() - started)
        return result

    def _request(self, payload, cancelled, on_delta=None, on_retry=None):
        return self._json_request(payload, cancelled, on_delta, on_retry)

    def request_review(self, payload, cancelled):
        # The reviewer owns batching. Return a truncated response to it rather
        # than retrying the same oversized batch with twice the thinking budget.
        result = self._json_request(payload, cancelled, retry_truncated=False)
        choice = result.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content")
        if (
            urlsplit(self.config.base_url).hostname == "api.deepseek.com"
            and not payload.get("tools")
            and choice.get("finish_reason") == "length"
            and not (isinstance(content, str) and content.strip())
        ):
            # A reasoning-only response has no JSON to validate or repair.
            # Retry the same obligations once without private reasoning. Every
            # dispatch still shares the turn budget/cancellation boundary, and
            # the caller validates the complete evidence protocol as before.
            return super()._request(
                {
                    **payload,
                    "thinking": {"type": "disabled"},
                    "stream": True,
                },
                cancelled,
            )
        return result

    def request_validation(self, payload, cancelled):
        """Short precommit decisions have their own explicit provider profile.

        Full requirements compilation and final source/evidence review keep
        their existing reasoning policy. Protocol, cancellation and shared
        dispatch accounting are unchanged for this bounded decision.
        """
        if urlsplit(
            self.config.base_url
        ).hostname == "api.deepseek.com" and not payload.get("tools"):
            payload = {**payload, "thinking": {"type": "disabled"}, "stream": True}
        return super()._request(payload, cancelled)

    def _json_request(
        self, payload, cancelled, on_delta=None, on_retry=None, *, retry_truncated=True
    ):
        if urlsplit(
            self.config.base_url
        ).hostname == "api.deepseek.com" and not payload.get("tools"):
            payload = {
                **payload,
                "thinking": {"type": "enabled"},
                "reasoning_effort": "low",
                "max_tokens": max(4096, payload.get("max_tokens", 2048) + 2048),
                "stream": True,
            }
            for attempt in range(2):
                result = super()._request(payload, cancelled, on_delta, on_retry)
                choice = result.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content")
                if not retry_truncated:
                    return result
                if (
                    choice.get("finish_reason") != "length"
                    and isinstance(content, str)
                    and content.strip()
                ):
                    return result
                payload = {
                    **payload,
                    "max_tokens": min(16384, payload["max_tokens"] * 2),
                }
            raise CompanionError("模型核对输出被截断，已保留进度，未执行对应文件操作。")
        return super()._request(payload, cancelled, on_delta, on_retry)
