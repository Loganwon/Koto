"""Koto security/quality validator adapter for the Agent Kernel."""

from __future__ import annotations

from app.core.agent.kernel import AgentRequest, ValidationOutcome


class KotoOutputValidator:
    def validate(self, content: str, request: AgentRequest) -> ValidationOutcome:
        from app.core.security.output_validator import (
            OutputValidator,
            sanitize_user_visible_text,
        )

        result = OutputValidator.validate(
            text=str(content or ""),
            original_prompt=request.prompt,
        )
        reasons = tuple(str(item) for item in (result.reasons or []))
        if result.is_blocked:
            safe = sanitize_user_visible_text(
                result.text or content,
                fallback="抱歉，这段输出包含不应直接展示的内部内容。请换个方式描述你的问题后重试。",
            )
            return ValidationOutcome.block(safe, reasons=reasons)
        if result.needs_retry:
            instruction = (
                result.text
                if result.text and result.text != content
                else "上一次回答未通过完整性或安全验收。请修正问题后重新回答。"
            )
            return ValidationOutcome.retry(
                content,
                instruction,
                reasons=reasons,
            )
        return ValidationOutcome.accept(result.text or content, reasons=reasons)


__all__ = ["KotoOutputValidator"]
