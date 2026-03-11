from datetime import datetime
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin


class BasicToolsPlugin(AgentPlugin):
    @property
    def name(self) -> str:
        return "BasicTools"

    @property
    def description(self) -> str:
        return "Basic utility tools for testing and general assistance."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "get_current_time",
                "func": self.get_current_time,
                "description": "Returns the current date and time.",
            },
            {
                "name": "calculate",
                "func": self.calculate,
                "description": "Performs basic arithmetic calculation.",
                # Explicit parameters example
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "expression": {
                            "type": "STRING",
                            "description": "Mathematical expression to evaluate (e.g. '2 + 2')",
                        }
                    },
                    "required": ["expression"],
                },
            },
        ]

    def get_current_time(self) -> str:
        """Returns the current local date and time."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def calculate(self, expression: str) -> str:
        """Evaluates a simple mathematical expression."""
        try:
            # restricted eval for safety
            allowed_chars = set("0123456789+-*/(). ")
            if not all(c in allowed_chars for c in expression):
                return "Error: Expression contains invalid characters. Only numbers and basic operators (+-*/) are allowed."

            # eval is dangerous, but this is a local desktop app for personal use, and we have basic sanitation
            result = eval(expression, {"__builtins__": None}, {})
            return str(result)
        except Exception as e:
            return f"Error calculating '{expression}': {str(e)}"
