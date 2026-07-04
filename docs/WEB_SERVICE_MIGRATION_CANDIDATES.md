# Koto Web Service Migration Candidates

Date: 2026-06-30

This document records the current migration boundary for the web services that
still carry core task-flow logic. It is intentionally conservative: modules are
listed as candidates only after their current owner, dependencies, target owner,
and blocking contract are visible.

## Boundary Rules

- `web.app` must remain an entrypoint, compatibility export surface, and runtime
  glue only.
- `web.runtime_context` is the allowed transition bridge for app-level singletons;
  production modules must not add direct `web.app` imports or `sys.modules["web.app"]`
  lookups.
- Web modules may own Flask, Response, SSE framing, request payload normalization,
  cancellation draining, and UI transport labels.
- Core modules should own routing decisions, model/client decisions, agent execution,
  file-task runtime semantics, artifact contracts, and workflow execution.
- Migration must happen by moving tests and callers first, then moving code. Do
  not move a streaming path until its SSE event contract and task artifact
  persistence are covered by tests.

## Candidate Matrix

| Current module | Current owner | Core dependencies | Target owner | Next move |
| --- | --- | --- | --- | --- |
| `web/file_task_stream.py` | Editor AI file-task SSE adapter. It normalizes request payloads, emits safe SSE frames, persists progress, attaches artifact results, and delegates execution to `FileTaskRuntime`. | `FileTaskRuntime`, `FileTaskRequest`, `FileTaskModelClient`, `task_ledger`, `progress_bus`, `file_task_ui_stream`, `web.runtime_context`. | Keep web transport in `web/file_task_stream.py`; only pure persistence/event normalization helpers should move toward `app/core/agent/file_task_streaming` after contract tests exist. | Add contract tests for terminal events, artifact result attachment, cancellation drain, and recent-summary injection before moving helpers. |
| `web/services/chat_stream/orchestrator.py` | Chat stream setup and dispatch coordinator. It builds context, injects skills, resolves task type and workflow route, performs quick responses, and prepares generation context. | `SmartDispatcher`, skill managers, memory services, RAG services, Flask `Response`, runtime model routing. | Split into an `app/core/routing` chat decision service plus a thin web SSE setup adapter. | Extract a pure route/setup result object first; keep Flask `Response` creation in web. |
| `web/services/chat_stream/agent_handler.py` | AGENT streaming bridge for LangGraphAgent first, UnifiedAgent fallback, local Ollama short path, session save, and memory extraction. | `SmartDispatcher`, `create_langgraph_agent`, `create_agent`, `AgentStepType`, local LLM helpers, Flask `Response`. | `app/core/agent` execution adapter returning normalized agent events; web keeps SSE wrapping and session persistence hooks. | Add event contract tests covering LangGraph success, UnifiedAgent fallback, local-mode failure, and task_final payload shape. |
| `web/services/chat_stream/langgraph_bridge.py` | LangGraph workflow SSE bridge for research document and multi-agent PPT workflows. | `WorkflowEngine`, Flask `Response`, session manager. | `app/core/workflow` stream adapter returning workflow events; web keeps transport. | Add tests for workflow route mapping and error event normalization before moving. |
| `web/services/chat_stream/generate/regular_handler.py` | Main text/CODER generation stream, memory context injection, local fallback, interrupt handling, rating/memory side effects. | `LocalModelRouter`, `model_fallback`, `ContextAnalyzer`, `stream_with_keepalive`, `web.runtime_context`, rating store. | Split generation policy/fallback into `app/core/llm`; keep request/session/SSE handling in web. | Initial pure policy helper now lives in `app.core.llm.chat_generation_policy`; next extract candidate-list/fallback failure classification once stream error tests exist. |
| `web/services/chat_stream/generate/system_handler.py` | SYSTEM task stream around `LocalExecutor`, failure detection, AI fix prompt, and session save. | `LocalExecutor`, `get_utils`, Gemini content generation, Flask/SSE caller contract. | `app/core/system` command execution result service; web keeps SSE and session write. | Add tests for initial failure, fix prompt path, and output sanitization. |
| `web/services/chat_stream/generate/web_search_handler.py` | Web search generation stream, grounded search retry, cloud fallback client selection, and source emission. | `get_web_searcher`, `get_create_client`, `get_utils`, Google genai types. | `app/core/services` web search answer service; web keeps streaming frames. | Extract retry/query-rewrite policy after source payload tests exist. |
| `web/services/chat_stream/generate/research_handler.py` | Deep research stream with keepalive and final session persistence. | Gemini streaming client, `stream_with_keepalive`, safe SSE. | Shared research execution service under `app/core/research` when chat and task workflows share a contract. | Wait until research/PPT workflow route matrix is documented. |
| `web/services/chat_stream/generate/painter_handler.py` | Painter/image generation stream and background worker queue. | Image model client, queue/threading, safe SSE. | Image generation service after output artifact contract is explicit. | Add saved image artifact tests before moving. |
| `web/services/chat_stream/generate/tot_handler.py` | Tree-of-thought stream adapter around `app.core.agent.tree_of_thought`. | `create_tot`, safe SSE, session manager. | Keep web adapter unless ToT becomes a shared workflow executor. | Add route ownership to the workflow/skill matrix before moving. |

## Current Non-Migration Decisions

- Do not move all of `web/file_task_stream.py` into `app/core` now. The file is
  already the web transport boundary for `FileTaskRuntime`; moving it wholesale
  would mix Flask/SSE concerns into core.
- Do not merge `LangGraphAgent` and `UnifiedAgent` while `agent_handler.py` still
  owns fallback behavior and frontend event shape.
- Do not replace `web.runtime_context` during this phase. It is the named bridge
  that keeps production code away from direct `web.app` imports.
- Do not delete chat-stream handlers based only on filename overlap. The migration
  unit is the verified behavior contract, not the directory name.

## Acceptance Guard

The architecture guard must keep this document present and require coverage for:

- `web/file_task_stream.py`
- `web/services/chat_stream/orchestrator.py`
- `web/services/chat_stream/agent_handler.py`
- `web/services/chat_stream/langgraph_bridge.py`
- `web/services/chat_stream/generate/regular_handler.py`
- `web/services/chat_stream/generate/system_handler.py`
- `web/services/chat_stream/generate/web_search_handler.py`
- `FileTaskRuntime`
- `SmartDispatcher`
- `LangGraphAgent`
- `UnifiedAgent`
- `web.runtime_context`
- direct `web.app`
