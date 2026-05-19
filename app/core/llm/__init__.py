"""LLM package entrypoint.

Keep package import side effects minimal. Heavy optional integrations such as
LangChain/Transformers must stay behind explicit submodule imports so desktop
startup does not pull them into the cold-start path just by importing
``app.core.llm.*`` helpers from ``web.app``.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _prefer_source_module(module_basename: str) -> None:
	module_name = f"{__name__}.{module_basename}"
	if module_name in sys.modules:
		return

	source_path = Path(__file__).with_name(f"{module_basename}.py")
	if not source_path.exists():
		return

	try:
		spec = importlib.util.spec_from_file_location(module_name, source_path)
		if spec is None or spec.loader is None:
			return
		module = importlib.util.module_from_spec(spec)
		sys.modules[module_name] = module
		spec.loader.exec_module(module)
	except Exception as exc:
		sys.modules.pop(module_name, None)
		logger.debug("[app.core.llm] 源码 %s 预加载失败: %s", module_basename, exc)


_prefer_source_module("ollama_llm_provider")
_prefer_source_module("model_capabilities")
_prefer_source_module("model_mode")
