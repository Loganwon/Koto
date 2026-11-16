# Koto Agent Execution Entrypoint Matrix

Date: 2026-10-22

This matrix records the currently supported Agent execution surfaces after
removing retired monolithic-loop compatibility paths from production.

## Current Executors

| Executor | Current role | Production entrypoints | Keep condition | Migration direction |
| --- | --- | --- | --- | --- |
| `FileTaskRuntime` | Workspace file-task execution, task supervision, tool-step verification, artifact events | `app/core/services/file_task_stream.py`; `/api/editor/ai/task-stream`; workspace task dispatcher routes | Required for file tasks and planned workspace flows | Keep as the file-task owner; pass routing decisions in instead of duplicating classification |
| `EditorQuickActionExecutor` | Lightweight editor SSE quick-action executor for non-code text actions | `app/core/agent/editor_quick_action_executor.py`; routed through `app/core/agent/editor_loop_executor.py` directly; `web/blueprints/editor_ai.py`; `/api/editor/ai/stream` | Required for editor text quick actions while preserving `AgentEvent` wire shape | Keep text-only behavior here and use `app/core/agent/llm_provider_helpers.py` for provider selection |
| `EditorCodeActionExecutor` | Editor SSE Python/R chart and code executor | `app/core/agent/editor_code_action_executor.py`; routed through `app/core/agent/editor_loop_executor.py` directly; `web/blueprints/editor_ai.py`; `/api/editor/ai/stream` when `language` is `python` or `r` | Required for editor code/chart requests while preserving `code_result` wire shape | Keep code generation helpers compatible via `app/core/agent/llm_provider_helpers.py` |
| `DocWebSocketAgentExecutor` | Doc WebSocket chat, selected proposal, doc-tool, live-doc, and code-language executor | `app/core/agent/doc_websocket_agent_executor.py`; routed through `app/core/agent/doc_websocket_loop_executor.py`; `app/core/socket_handler.py` for doc chat, inline doc edits, live doc commits, and Python/R chart requests | Required for doc chat responses, selected proposals, doc tool calls, live-doc commits, and `code_result` while preserving `AgentEvent` and `/doc` WebSocket event shape | Keep as the doc WebSocket execution owner; reuse `EditorCodeActionExecutor` for Python/R sandbox behavior |
| `KernelAgent` + `KernelRuntime` | Production general Agent using one provider-neutral model/tool loop and the fixed `core` tool profile | `web/services/chat_stream/agent_handler.py`; `app/core/agent/kernel_agent_service.py`; `app/core/jobs/job_runner.py`; `app/core/goal/*` | Canonical production path; preserves `AgentStep` compatibility at the facade only | Keep request preparation and transport mapping outside `KernelRuntime`; do not add another fallback loop |

The table above describes the Web/Core application. Embedded Word/WPS now uses `companion/pane_task_session.py`, `NativeDeepEngine` and `NativeBroker` through the installed loopback service. It does not use the Web Kernel loop. Excel/PowerPoint embedded compatibility and the explicitly selected retired floating regression still use `EditingSession`; current workflow calls must never fall through to that API. See [Companion](../companion/README.md).

## Transport Mappers

| Mapper | Current role | Production entrypoints | Keep condition | Migration direction |
| --- | --- | --- | --- | --- |
| `doc_websocket_event_mapper.py` | Maps `AgentEvent` payloads to existing `/doc` WebSocket event names and fields | `app/core/agent/doc_websocket_event_mapper.py`; thin wrapper in `app/core/socket_handler.py` | Required while doc frontend consumes the current WebSocket contract | Keep as the transport contract while replacing the doc executor underneath |

`AgentRequest`, `AgentEvent`, `EventType`, `RunState`, and their constructors are
owned by `app/core/agent/kernel/lifecycle.py`. The old
`app/core/agent/lifecycle.py` compatibility path has been deleted; all code and
tests use the Kernel contract directly.

## Deleted Entrypoints

The old monolithic loop compatibility module has been removed. Do not recreate
imports, shims, or endpoint adapters for deleted agent-loop paths. Route new
work through one of the current executors above.

The retired Agent HTTP blueprint was also removed. Product chat uses
`/api/chat/stream`; workspace tasks use `/api/editor/ai/task-stream`. Internal
jobs and transports obtain the same KernelAgent through
`app.core.agent.kernel_agent_service` and must not expose another Agent API.

`app/core/agent/deep_research.py` was also removed on 2026-07-18 after a full
reference audit found no production entrypoint. The active research/file-generation
flows use `WebSearcher` and Kernel file tools instead.

The standalone `langgraph_agent.py` and `multi_agent.py` loops were removed on
2026-07-18. The development graph endpoint now renders the canonical Kernel
topology. The orphaned deterministic `WorkflowEngine` and its office workflow
catalog have also been removed; they are not a supported execution surface.

## Audit Guard

`scripts/audit_code_baseline.py --json` exposes
`agent_production_entrypoint_hits` for active executors and
`deleted_agent_entrypoint_hits` for removed agent-loop paths. The expected
deleted-path state is:

The expected state is that every list under `deleted_agent_entrypoint_hits` is
empty. The exact deleted identifiers live in the audit script so this matrix
does not reintroduce retired route names as architectural vocabulary.

## Retirement Sequence

1. Preserve the current editor SSE and doc WebSocket event payloads with tests.
2. Keep deleted agent-loop path hits at zero.
3. Keep remaining legacy-named facade modules only where they are active event-contract adapters.
4. Delete adapters only after their production entrypoints have moved and the wire contract is preserved.

## Validation

Before removing or changing any executor boundary, run at least:

```powershell
python -m pytest tests/unit/test_ai_task_chain_architecture.py -q
python -m pytest tests/unit/test_llm_provider_helpers.py -q
python -m pytest tests/unit/test_editor_code_action_executor.py -q
python -m pytest tests/unit/test_editor_quick_action_executor.py -q
python -m pytest tests/unit/test_doc_websocket_agent_executor.py -q
python -m pytest tests/unit/test_doc_websocket_loop_executor.py -q
python -m pytest tests/unit/test_editor_loop_executor.py -q
python -m pytest tests/unit/test_legacy_agent_transport_contract.py -q
python -m pytest tests/unit/test_agent_entrypoint_architecture.py -q
python -m pytest tests/test_ai_stream.py -q --tb=short
python -m pytest tests/unit/test_unified_agent_output_validation.py -q --tb=short
```

For workspace file tasks, add a browser or Playwright smoke test that checks
classification, execution-plan rendering, actual tool choice, and produced
artifacts.
