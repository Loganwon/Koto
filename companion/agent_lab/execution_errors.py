"""Structured execution diagnostics; never infer user intent from error text."""

from companion.contracts import CompanionError


class ToolDiagnosticError(CompanionError):
    def __init__(self, message, recovery):
        super().__init__(message)
        self.recovery = recovery
