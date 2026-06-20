from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _unload_llm_package() -> None:
    root = str(_repo_root())
    sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != root]
    sys.path.insert(0, root)

    sys.modules.pop("app.core.llm.langchain_adapter", None)

    llm_pkg = sys.modules.get("app.core.llm")
    if llm_pkg is not None and hasattr(llm_pkg, "langchain_adapter"):
        delattr(llm_pkg, "langchain_adapter")


def test_langchain_adapter_import_prefers_source_module():
    _unload_llm_package()

    module = importlib.import_module("app.core.llm.langchain_adapter")

    assert Path(module.__file__).resolve() == (
        _repo_root() / "app" / "core" / "llm" / "langchain_adapter.py"
    ).resolve()
    assert hasattr(module, "KotoLangChainLLM")
    assert callable(module.KotoLangChainLLM.get_num_tokens)


def test_app_core_llm_package_import_does_not_preload_langchain_adapter():
    _unload_llm_package()

    importlib.import_module("app.core.llm")

    assert "app.core.llm.langchain_adapter" not in sys.modules
