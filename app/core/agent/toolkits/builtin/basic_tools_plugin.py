"""BasicToolsPlugin ? general utility tools for KernelAgent.

Tools registered:
  - get_current_time()  -> current local date and time
  - calculate(expression) -> safe arithmetic evaluation

Migrated from the retired app/core/agent/plugins namespace into the
builtin toolkit package so the "basic" profile descriptor can load.
"""

from __future__ import annotations

import ast
from datetime import datetime
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin


class BasicToolsPlugin(AgentPlugin):
    """Basic utility tools for time queries and arithmetic evaluation."""

    @property
    def name(self) -> str:
        return "BasicTools"

    @property
    def description(self) -> str:
        return "Basic utility tools: current time lookup and safe arithmetic."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "get_current_time",
                "func": self.get_current_time,
                "description": "Returns the current local date and time.",
            },
            {
                "name": "calculate",
                "func": self.calculate,
                "description": "Evaluates a basic arithmetic expression safely.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "expression": {
                            "type": "STRING",
                            "description": (
                                "Mathematical expression to evaluate, e.g. '2 + 2 * 3'."
                            ),
                        }
                    },
                    "required": ["expression"],
                },
            },
        ]

    def get_current_time(self) -> str:
        """Return the current local date and time."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _CALC_FUNCS = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "int": int,
        "float": float,
    }
    _CALC_ALLOWED_NAMES = frozenset(_CALC_FUNCS)

    def calculate(self, expression: str) -> str:
        """Evaluate a simple mathematical expression without executing code."""
        try:
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, TypeError) as exc:
            return f"Error calculating '{expression}': {exc}"
        try:
            value = self._eval_node(tree.body)
        except Exception as exc:
            return f"Error calculating '{expression}': {exc}"
        return str(value)

    def _eval_node(self, node: ast.AST):
        if isinstance(node, ast.Expression):
            return self._eval_node(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant: {node.value!r}")
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left**right
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return +operand
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in self._CALC_ALLOWED_NAMES:
                raise ValueError(f"Name '{node.func.id}' is not allowed.")
            args = [self._eval_node(arg) for arg in node.args]
            return self._CALC_FUNCS[node.func.id](*args)
        if isinstance(node, ast.Name):
            raise ValueError(
                f"Name '{node.id}' is not allowed. Only basic math functions are permitted."
            )
        raise ValueError(f"Disallowed syntax node: {type(node).__name__}")
