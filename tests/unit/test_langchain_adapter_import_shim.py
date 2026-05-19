from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_langchain_adapter_import_prefers_source_module():
    sys.modules.pop("app.core.llm.langchain_adapter", None)
    sys.modules.pop("app.core.llm", None)

    module = importlib.import_module("app.core.llm.langchain_adapter")

    assert Path(module.__file__).name == "langchain_adapter.py"
    assert hasattr(module, "KotoLangChainLLM")
    assert callable(module.KotoLangChainLLM.get_num_tokens)


def test_app_core_llm_package_import_does_not_preload_langchain_adapter():
    sys.modules.pop("app.core.llm.langchain_adapter", None)
    sys.modules.pop("app.core.llm", None)

    importlib.import_module("app.core.llm")

    assert "app.core.llm.langchain_adapter" not in sys.modules