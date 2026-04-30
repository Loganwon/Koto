# ══════════════════════════════════════════════════════════════
# workflow_engine.py — Koto 工作流编排引擎
#
# 职责：
#   - 统一的 WorkflowExecutor 基类，供所有 workflow skill 继承
#   - SSE 进度事件生成 (step_start / progress / step_done / output / error / done)
#   - 多文件上下文传递（源文件解析 + 模板文件处理）
#   - 临时文件到 session tmp 目录的生命周期管理
#   - LLM 调用辅助（含 online→local 回退链）
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Generator, Optional

from app.core.llm.model_mode import normalize_model_mode

logger = logging.getLogger(__name__)

# ── SSE 事件构建器 ─────────────────────────────────────────────────────────────

def _sse(payload: dict) -> str:
    """构建单条 Server-Sent-Events 数据行。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_status(text: str) -> str:
    return _sse({"type": "status", "text": text})


def sse_progress(current: int, total: int, detail: str = "") -> str:
    return _sse({"type": "progress", "current": current, "total": total, "detail": detail})


def sse_step_start(step: str, label: str) -> str:
    return _sse({"type": "step_start", "step": step, "label": label})


def sse_step_done(step: str, label: str) -> str:
    return _sse({"type": "step_done", "step": step, "label": label})


def sse_output(output_type: str, data: Any, label: str = "") -> str:
    """输出结果事件。output_type: 'xlsx_data' | 'markdown' | 'html' | 'text' | 'docx_file' | 'pptx_file' | 'xlsx_file'"""
    return _sse({"type": "output", "output_type": output_type, "data": data, "label": label})


def sse_error(msg: str) -> str:
    return _sse({"type": "error", "text": msg})


def sse_done(summary: str = "") -> str:
    return _sse({"type": "done", "summary": summary})


# ── LLM 调用辅助 ───────────────────────────────────────────────────────────────

def _resolve_provider_arg(model_mode: str) -> dict:
    """将 model_mode 映射为 get_llm_provider 接受的参数。"""
    normalized_mode = normalize_model_mode(model_mode, default="auto")
    if normalized_mode == "local":
        return {"provider": "ollama"}
    if normalized_mode == "cloud":
        return {"provider": "gemini"}
    if normalized_mode in ("gemini", "openai", "anthropic", "ollama"):
        return {"provider": normalized_mode}
    # "auto" 或其他 → 不指定，由 provider_factory 自动检测
    return {}


def _extract_text(result: Any) -> str:
    """从 provider.generate_content 的返回值中提取纯文本。"""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        # Gemini / OpenAI 返回 dict 时，文本通常在 "text" 或 "content" 键
        return result.get("text") or result.get("content") or str(result)
    return str(result)


def call_llm(prompt: str, system: str = "", model_mode: str = "auto",
             max_tokens: int = 4096, call_timeout: Optional[float] = None) -> str:
    """
    单次 LLM 调用，返回完整回复文本。
    回退链：online → local Ollama。
    """
    from app.core.llm.provider_factory import get_llm_provider

    provider = get_llm_provider(
        **_resolve_provider_arg(model_mode),
        allow_local_fallback=False,
    )

    try:
        result = provider.generate_content(
            prompt,
            system_instruction=system or None,
            max_tokens=max_tokens,
            call_timeout=call_timeout,
        )
        return _extract_text(result)
    except Exception as e:
        logger.warning(f"[WorkflowEngine/LLM] 在线模型失败: {e}，尝试本地模型")
        try:
            local_provider = get_llm_provider(provider="ollama")
            result = local_provider.generate_content(
                prompt,
                system_instruction=system or None,
                max_tokens=max_tokens,
                call_timeout=call_timeout,
            )
            return _extract_text(result)
        except Exception as e2:
            logger.error(f"[WorkflowEngine/LLM] 本地模型也失败: {e2}")
            raise RuntimeError(f"LLM 调用失败: {e2}") from e2


def call_llm_json(prompt: str, system: str = "", model_mode: str = "auto",
                  max_tokens: int = 8192, call_timeout: Optional[float] = None) -> Any:
    """
    调用 LLM 并解析 JSON 输出。自动去除 markdown 代码块标记。
    如果解析失败, 尝试提取最外层 JSON 片段再次解析。
    """
    import re

    # 在 system prompt 末尾强化 JSON-only 指令
    json_system = system
    if system and "json" not in system.lower():
        json_system = system.rstrip() + "\n\n请严格以 JSON 格式输出，不要包含任何 markdown 代码块标记或额外说明。"

    raw = call_llm(
        prompt,
        system=json_system,
        model_mode=model_mode,
        max_tokens=max_tokens,
        call_timeout=call_timeout,
    )
    # 去除 ```json ... ``` 代码块（兼容多种 LLM 输出习惯）
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"\n?```\s*$", "", raw.strip(), flags=re.MULTILINE)
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 尝试提取最外层 JSON 对象或数组
    # 优先匹配数组（工作流常返回列表）
    for pattern in [r"(\[[\s\S]*\])", r"(\{[\s\S]*\})"]:
        m = re.search(pattern, raw)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue

    logger.warning(f"[WorkflowEngine/JSON] JSON 解析失败，返回原始文本: {raw[:200]}")
    return raw  # 降级返回原始文本


# ── 文件解析辅助 ───────────────────────────────────────────────────────────────

def parse_source_file(file_path: str) -> str:
    """
    将任意支持格式的文件解析为纯文本，供 LLM 使用。
    支持: DOCX, XLSX, PPTX, PDF, TXT, CSV, MD
    """
    from pathlib import Path as _Path
    p = _Path(file_path)
    ext = p.suffix.lower()

    try:
        if ext == ".pdf":
            from app.core.file.file_parser import parse_pdf
            result = parse_pdf(str(p), str(uuid.uuid4()))
            return result.get("text", "")

        if ext in (".docx", ".doc"):
            from app.core.file.file_parser import parse_docx
            result = parse_docx(str(p))
            # 提取纯文本（去除 HTML 标签）
            import re
            html = result.get("html", "") or result.get("content", "")
            return re.sub(r"<[^>]+>", " ", html).strip()

        if ext in (".xlsx", ".xls"):
            from app.core.file.file_parser import parse_xlsx
            result = parse_xlsx(str(p), p.name)
            # 组装为 CSV-like 文本
            lines = []
            for sheet_id, sheet in result.get("sheets", {}).items():
                lines.append(f"[Sheet: {sheet.get('name', sheet_id)}]")
                cell_data = sheet.get("cellData", {})
                for row_idx in sorted(cell_data.keys(), key=lambda x: int(x)):
                    row = cell_data[row_idx]
                    max_col = max((int(k) for k in row.keys()), default=-1)
                    cells = []
                    for c in range(max_col + 1):
                        # parse_xlsx uses integer keys for columns
                        cell = row.get(c) or row.get(str(c)) or {}
                        cells.append(str(cell.get("v", "") or ""))
                    lines.append("\t".join(cells))
            return "\n".join(lines)

        if ext in (".pptx", ".ppt"):
            from app.core.file.file_parser import parse_pptx
            slides = parse_pptx(str(p))
            lines = []
            for slide in slides:
                lines.append(f"[Slide {slide.get('slide_index', '?') + 1}]")
                for t in slide.get("texts", []):
                    lines.append(t.get("text", ""))
            return "\n".join(lines)

        if ext in (".txt", ".md", ".markdown", ".csv"):
            return p.read_text(encoding="utf-8", errors="replace")

        return p.read_text(encoding="utf-8", errors="replace")

    except Exception as e:
        logger.warning(f"[WorkflowEngine] 文件解析失败 {file_path}: {e}")
        return ""


# ── 基类 ───────────────────────────────────────────────────────────────────────

class WorkflowExecutor:
    """
    所有工作流 Skill 的基类。

    子类实现 execute(params, yield_event) 方法，通过
    yield_event(sse_*(...)) 发出 SSE 数据。

    使用示例：
        executor = CrossFormatExtractor()
        for chunk in executor.run(params):
            yield chunk   # 直接作为 Flask SSE 响应
    """

    # 子类覆盖
    WORKFLOW_ID: str = "base"
    WORKFLOW_NAME: str = "基础工作流"

    def run(self, params: dict) -> Generator[str, None, None]:
        """
        公开入口：迭代产生 SSE 事件字符串。
        自动封装异常为 sse_error，最后发送 sse_done。
        """
        start = time.time()
        events: list[str] = []

        def _yield(chunk: str):
            events.append(chunk)

        try:
            yield sse_status(f"⚙️ 正在启动 [{self.WORKFLOW_NAME}]…")
            yield from self.execute(params, _yield)
            elapsed = round(time.time() - start, 1)
            yield sse_done(f"{self.WORKFLOW_NAME} 已完成，耗时 {elapsed}s")
        except Exception as exc:
            logger.exception(f"[{self.WORKFLOW_ID}] 工作流执行失败: {exc}")
            yield sse_error(f"工作流执行失败: {exc}")
            yield sse_done("执行异常结束")

    def execute(
        self,
        params: dict,
        yield_event,  # callable(str) -> None，也允许直接 yield
    ) -> Generator[str, None, None]:
        """
        子类覆盖此方法实现工作流逻辑。
        可以 yield 字符串（SSE 数据行），也可以调用 yield_event(...)。
        """
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 execute()")

    # ── 辅助方法，供子类使用 ──────────────────────────────────────────────────

    @staticmethod
    def llm(prompt: str, system: str = "", model_mode: str = "auto") -> str:
        """单次 LLM 文本回复。"""
        return call_llm(prompt, system=system, model_mode=model_mode)

    @staticmethod
    def llm_json(prompt: str, system: str = "", model_mode: str = "auto") -> Any:
        """单次 LLM JSON 回复（自动解析）。"""
        return call_llm_json(prompt, system=system, model_mode=model_mode)

    @staticmethod
    def save_output_file(suffix: str = ".docx") -> Path:
        """创建输出目录并返回输出文件 Path，供工作流保存产出文件。

        输出目录优先使用项目 workspace/tmp，回退到系统临时目录。
        """
        # 定位项目根目录（workflow_engine.py 在 app/core/ 下）
        _engine_file = Path(__file__).resolve()
        _project_root = _engine_file.parent.parent.parent  # app/core/workflow_engine.py -> root
        _workspace_tmp = _project_root / "workspace" / "tmp"
        try:
            _workspace_tmp.mkdir(parents=True, exist_ok=True)
            out_dir = _workspace_tmp
        except OSError:
            import tempfile as _tf
            out_dir = Path(_tf.gettempdir()) / f"koto_wf_{uuid.uuid4().hex[:8]}"
            out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"output_{uuid.uuid4().hex[:8]}{suffix}"

    @staticmethod
    def parse_file(file_path: str) -> str:
        """将文件解析为纯文本。"""
        return parse_source_file(file_path)
