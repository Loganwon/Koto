from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_task_ledger_import_prefers_source_module():
    sys.modules.pop("app.core.tasks.task_ledger", None)
    sys.modules.pop("app.core.tasks", None)

    module = importlib.import_module("app.core.tasks.task_ledger")

    assert Path(module.__file__).name == "task_ledger.py"
    assert hasattr(module, "TaskLedger")