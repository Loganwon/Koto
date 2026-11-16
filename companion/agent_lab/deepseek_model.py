"""Preserve DeepSeek's required private reasoning state across tool rounds.

https://api-docs.deepseek.com/guides/thinking_mode/
The pinned SDK reads reasoning_content but its request converter drops it.
"""

from urllib.parse import urlsplit
from langchain_deepseek import ChatDeepSeek


def thinking_provider(config):
    return urlsplit(config.base_url).hostname == "api.deepseek.com"


class KotoDeepSeek(ChatDeepSeek):
    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for source, target in zip(messages, payload["messages"]):
            if target["role"] == "assistant":
                reasoning = source.additional_kwargs.get("reasoning_content")
                # Synthetic summaries and history from a non-thinking model have
                # no reasoning. Never discard actual reasoning when it exists.
                target["reasoning_content"] = (
                    reasoning if isinstance(reasoning, str) else ""
                )
        return payload
