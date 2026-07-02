from __future__ import annotations

import logging
import re
from collections.abc import Iterator

from app.core.agent import llm_provider_helpers
from app.core.agent.lifecycle import (
    AgentEvent,
    AgentRequest,
    RunMetadata,
    RunState,
    evt_code_result,
    evt_error,
    evt_lifecycle_end,
    evt_lifecycle_error,
    evt_lifecycle_start,
    evt_phase,
    evt_plan,
    evt_status_message,
    evt_step_done,
    evt_step_progress,
    evt_step_start,
    evt_stream_chunk,
)

logger = logging.getLogger(__name__)


class EditorCodeActionExecutor:
    """Editor SSE executor for Python/R chart and code actions."""

    @staticmethod
    def supports(request: AgentRequest) -> bool:
        return request.language in {"python", "r"}

    def iter_events(self, request: AgentRequest) -> Iterator[AgentEvent]:
        meta = RunMetadata(session_id=request.session_id)
        meta.start()
        yield evt_lifecycle_start(meta.run_id, meta.session_id)

        try:
            yield from self._run_inner(request, meta)
        except Exception as exc:
            logger.exception("[EditorCodeActionExecutor] failed: %s", exc)
            meta.finish(RunState.FAILED, str(exc))
            yield evt_lifecycle_error(meta.run_id, str(exc))
            yield evt_code_result({
                "error": f"内部错误：{exc}",
                "stdout": "",
                "stderr": "",
                "files": {},
            })
            return

        if not meta.state.is_terminal:
            meta.finish(RunState.SUCCEEDED)
        yield evt_lifecycle_end(meta.run_id, meta.state)

    def _run_inner(
        self,
        request: AgentRequest,
        meta: RunMetadata,
    ) -> Iterator[AgentEvent]:
        if not request.prompt:
            yield evt_error("请输入内容")
            meta.finish(RunState.FAILED, "empty prompt")
            return

        phases = self._resolve_phases(request)
        phase_steps = [
            {
                "id": phase.get("id") or f"step_{idx + 1}",
                "description": phase.get("label") or phase.get("id") or f"步骤 {idx + 1}",
            }
            for idx, phase in enumerate(phases)
        ]
        if phase_steps:
            yield evt_plan(phase_steps)

        analyze_phase = phases[0] if phases else {"id": "understand", "label": "理解需求"}
        analyze_step_id = analyze_phase.get("id", "understand")
        analyze_label = analyze_phase.get("label", "理解需求")

        yield evt_step_start(analyze_step_id, analyze_label)
        yield evt_phase(phases, analyze_step_id, "running")
        yield evt_step_progress(analyze_step_id, "正在分析上下文…")
        yield evt_status_message("正在分析上下文…")

        prompt = self._apply_rag_chunking(request, request.prompt)
        yield from self._run_code_mode(request, prompt, meta)

    def _run_code_mode(
        self,
        request: AgentRequest,
        prompt: str,
        meta: RunMetadata,
    ) -> Iterator[AgentEvent]:
        try:
            from app.core.sandbox import run_python, run_r
        except ImportError as exc:
            yield evt_code_result({
                "error": f"Sandbox 模块加载失败: {exc}",
                "stdout": "",
                "stderr": "",
                "files": {},
            })
            meta.finish(RunState.FAILED, str(exc))
            return

        lang_label = "Python (matplotlib/pandas)" if request.language == "python" else "R (ggplot2)"
        gen_prompt = (
            f"请根据以下任务，编写一段可以直接运行的 {lang_label} 代码。\n"
            "要求：\n"
            "1. 使用 matplotlib 或 pandas 绘图（Python）/ ggplot2（R）\n"
            "2. 将生成的图表保存为当前目录下的 chart.png 文件\n"
            "3. 对于 Python：在代码开头设置 matplotlib.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','Noto Sans CJK SC','WenQuanYi Micro Hei','DejaVu Sans'] 和 matplotlib.rcParams['axes.unicode_minus']=False\n"
            "4. 对于 Python：使用 plt.savefig('chart.png', dpi=220, bbox_inches='tight')\n"
            "5. 对于 R：使用 ggsave('chart.png', dpi=220)\n"
            "5. 不要用 plt.show() 或任何 GUI 调用\n"
            "6. 只输出代码，不要任何 markdown 代码块标记（不要 ```）\n\n"
            f"任务描述：{prompt}\n"
        )
        if request.csv_data:
            gen_prompt += f"\n表格数据（CSV 格式）：\n{request.csv_data}\n"

        yield evt_stream_chunk(f"🤖 正在为你生成 {request.language.upper()} 代码…\n")

        code = llm_provider_helpers.call_llm_sync(
            gen_prompt,
            use_local_only=(request.model_mode == "local"),
        )
        if not code:
            yield evt_code_result({
                "error": "AI 代码生成失败，请检查 API Key 配置。",
                "stdout": "",
                "stderr": "",
                "files": {},
            })
            meta.finish(RunState.FAILED, "code gen failed")
            return

        code = re.sub(r"^```[a-z]*\n?", "", code.strip(), flags=re.MULTILINE)
        code = code.strip().strip("`")

        yield evt_stream_chunk(f"\n```{request.language}\n{code}\n```\n\n▶ 正在执行…\n")

        if request.language == "python":
            result = run_python(code)
        else:
            result = run_r(code)

        yield evt_code_result(result)
        meta.finish(RunState.SUCCEEDED)

    def _resolve_phases(self, request: AgentRequest) -> list[dict[str, str]]:
        try:
            from app.core.editor_skills import get_phases

            action_hint = request.action_type or ""
            return get_phases(action_hint) if action_hint else get_phases("")
        except Exception:
            return [
                {"id": "understand", "label": "理解需求"},
                {"id": "generate", "label": "生成回复"},
            ]

    def _apply_rag_chunking(self, request: AgentRequest, prompt: str) -> str:
        context = request.context
        if not context:
            return prompt

        try:
            from app.core.file.doc_chunker import DocChunker

            if len(context) > DocChunker.CHUNK_THRESHOLD:
                chunks = DocChunker.chunk(context)
                query = request.selection if request.selection else prompt
                retrieved = DocChunker.retrieve(chunks, query=query, top_k=4)
                dc_context = "\n\n---\n\n".join(retrieved)
                return (
                    f"[文档内容（RAG检索片段，共{len(chunks)}段，"
                    f"已检索最相关{len(retrieved)}段）]\n"
                    f"{dc_context}\n[用户请求]: {prompt}"
                )
            return f"{context}\n[用户请求]: {prompt}"
        except Exception:
            return f"{context}\n[用户请求]: {prompt}"
