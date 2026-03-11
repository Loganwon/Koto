"""
DataProcessPlugin — 数据加载、分析、保存

从 web/adaptive_agent.py 的 data_process 工具迁移而来,
适配 UnifiedAgent 插件体系。
"""

import json
import os
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin


class DataProcessPlugin(AgentPlugin):
    """Provides data loading, analysis, and export capabilities (pandas-backed)."""

    @property
    def name(self) -> str:
        return "DataProcess"

    @property
    def description(self) -> str:
        return "Load, inspect, and save tabular data files (CSV, Excel, JSON)."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "load_data",
                "func": self.load_data,
                "description": "Load a tabular data file and return shape, columns, and a preview. "
                "Supports .csv, .xlsx, .xls, .json.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filepath": {
                            "type": "STRING",
                            "description": "Path to the data file.",
                        }
                    },
                    "required": ["filepath"],
                },
            },
            {
                "name": "query_data",
                "func": self.query_data,
                "description": "Load a data file and run a pandas query/expression on it. "
                "Returns the first 20 result rows.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filepath": {
                            "type": "STRING",
                            "description": "Path to the data file.",
                        },
                        "expression": {
                            "type": "STRING",
                            "description": "A pandas expression to evaluate on the DataFrame 'df', "
                            "e.g. \"df[df['age'] > 30].describe()\".",
                        },
                    },
                    "required": ["filepath", "expression"],
                },
            },
            {
                "name": "save_data",
                "func": self.save_data,
                "description": "Save data (provided as JSON rows) to a file. "
                "Supports .csv, .xlsx, .json output.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filepath": {
                            "type": "STRING",
                            "description": "Destination file path.",
                        },
                        "data_json": {
                            "type": "STRING",
                            "description": "JSON string of records (list of dicts).",
                        },
                    },
                    "required": ["filepath", "data_json"],
                },
            },
        ]

    # ------------------------------------------------------------------

    @staticmethod
    def _load_df(filepath: str):
        """Internal helper — load file into a pandas DataFrame."""
        import pandas as pd

        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".csv":
            return pd.read_csv(filepath)
        elif ext in (".xlsx", ".xls"):
            return pd.read_excel(filepath)
        elif ext == ".json":
            return pd.read_json(filepath)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    def load_data(self, filepath: str) -> str:
        """Load a data file and return shape + preview."""
        try:
            df = self._load_df(filepath)
            preview = df.head(10).to_string(index=False)
            return (
                f"Shape: {df.shape[0]} rows × {df.shape[1]} columns\n"
                f"Columns: {', '.join(df.columns)}\n\n"
                f"Preview:\n{preview}"
            )
        except Exception as exc:
            return f"Error loading data: {exc}"

    def query_data(self, filepath: str, expression: str) -> str:
        """Load data and evaluate a pandas expression."""
        try:
            df = self._load_df(filepath)
            result = eval(
                expression, {"__builtins__": {}}, {"df": df, "pd": __import__("pandas")}
            )
            if hasattr(result, "to_string"):
                return str(result.head(20).to_string())
            return str(result)
        except Exception as exc:
            return f"Error evaluating expression: {exc}"

    @staticmethod
    def save_data(filepath: str, data_json: str) -> str:
        """Save JSON records to a file."""
        try:
            import pandas as pd

            records = json.loads(data_json)
            df = pd.DataFrame(records)

            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            ext = os.path.splitext(filepath)[1].lower()
            if ext == ".csv":
                df.to_csv(filepath, index=False)
            elif ext in (".xlsx", ".xls"):
                df.to_excel(filepath, index=False)
            elif ext == ".json":
                df.to_json(filepath, orient="records", force_ascii=False, indent=2)
            else:
                return f"Unsupported output format: {ext}"

            return f"Data saved to {filepath} ({len(df)} rows)."
        except Exception as exc:
            return f"Error saving data: {exc}"
