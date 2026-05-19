# External Planner Integration Plan

## Current State

- Koto file tasks now run through the Koto-native whitebox runtime in `app/core/agent/file_task_runtime.py`.
- Model calls for file tasks are centralized in `app/core/agent/file_task_model.py`.
- Local source checkouts for the external agent projects are present under:
  - `.tmp_external_agents/openclaw`
  - `.tmp_external_agents/hermes-agent`

## Grounded Architecture Findings

### OpenClaw

- Primary shape: TypeScript control plane with a long-lived gateway, plugin runtime, MCP runtime, multi-session routing, and broad channel integration.
- Important docs:
  - `.tmp_external_agents/openclaw/README.md`
  - `.tmp_external_agents/openclaw/VISION.md`
  - `.tmp_external_agents/openclaw/docs/concepts/architecture.md`
  - `.tmp_external_agents/openclaw/docs/tools/plugin.md`
  - `.tmp_external_agents/openclaw/docs/gateway/protocol.md`
- Important source areas:
  - `.tmp_external_agents/openclaw/src/agents/`
  - `.tmp_external_agents/openclaw/extensions/`
  - `.tmp_external_agents/openclaw/packages/`
- Integration judgment:
  - Best used as a planning/control-plane reference and secondary external planner.
  - Not the best first choice for Koto file-task embedding because its center of gravity is gateway/plugin/channel orchestration, not a narrow file-task runtime.

### Hermes

- Primary shape: Python agent runtime with a large synchronous agent loop, explicit tool registry, toolsets, gateway, memory, plugins, MCP, browser tooling, and delegation.
- Important docs:
  - `.tmp_external_agents/hermes-agent/README.md`
  - `.tmp_external_agents/hermes-agent/website/docs/developer-guide/architecture.md`
  - `.tmp_external_agents/hermes-agent/website/docs/developer-guide/agent-loop.md`
  - `.tmp_external_agents/hermes-agent/website/docs/user-guide/features/tools.md`
  - `.tmp_external_agents/hermes-agent/website/docs/user-guide/features/tool-gateway.md`
  - `.tmp_external_agents/hermes-agent/website/docs/user-guide/features/mcp.md`
- Important source areas:
  - `.tmp_external_agents/hermes-agent/run_agent.py`
  - `.tmp_external_agents/hermes-agent/model_tools.py`
  - `.tmp_external_agents/hermes-agent/toolsets.py`
  - `.tmp_external_agents/hermes-agent/tools/`
  - `.tmp_external_agents/hermes-agent/gateway/`
  - `.tmp_external_agents/hermes-agent/plugins/`
- Integration judgment:
  - Best first external planner target for Koto.
  - Its structure maps more naturally onto Koto's file-task need: plan, choose tools, delegate, and return structured tool-use decisions.

## Integration Principles

- Koto remains the control plane.
- External planners do not get direct authority to mutate workspace files.
- External planners may only return structured model responses or a wrapper-produced JSON tool plan.
- Koto still owns:
  - tool allowlisting
  - file writes
  - `file.changed` emission
  - task verification
  - final success or failure judgment

## Phase Plan

### Phase 1: Planner Foundation

Status: implemented.

- Added `app/core/agent/file_task_planner.py`.
- Added a planner adapter registry and two named backends:
  - `hermes`
  - `openclaw`
- Added command-bridge support:
  - explicit request options: `planner_backend`, `planner_command`, `planner_timeout`
  - backend-specific options: `hermes_planner_command`, `openclaw_planner_command`
  - fallback option: `planner_allow_native_fallback`
- Added request normalization in `app/core/agent/file_task_contract.py` so planner fields can be passed top-level or via `options`.
- Wired `FileTaskModelClient` to dispatch to an explicit external planner before the native cloud/local model path.
- Added status inspection route:
  - `GET /api/editor/ai/planner-support`
  - planner support now reports the effective transport (`embedded` or `command`) per backend
  - planner support now also reports supported policies, the default policy, and currently available backends

### Phase 2: Hermes Embedded Bridge

Status: implemented for Hermes, still pending for OpenClaw.

- `HermesPlannerAdapter` now prefers a local in-process bridge when `.tmp_external_agents/hermes-agent/run_agent.py` is present.
- The bridge dynamically loads `run_agent.py`, instantiates `AIAgent`, disables Hermes toolsets, and asks Hermes to return a strict JSON planning object.
- Hermes output is normalized back into Koto's existing `content` and `tool_calls` shape.
- If a planner command is configured, Hermes can still fall back to the existing command transport.

### Phase 3: Wrapper Commands

Status: partial.

- Command-bridge transport remains supported for both backends:
  - reads a JSON payload from stdin
  - invokes an external constrained planner process
  - prints a strict JSON response with `content`, `tool_calls`, and optionally `tool_gap`
- This remains the active path for OpenClaw until a real in-process bridge exists.

### Phase 4: Routing Policy

Status: implemented for the first conservative policy set.

- Add explicit planner selection policy for file tasks:
  - native only
  - prefer Hermes
  - prefer OpenClaw
  - hermes fallback
  - openclaw fallback
- Default policy should remain Koto native first.
- Implemented request options:
  - `planner_policy=auto`
  - `planner_policy=prefer_hermes`
  - `planner_policy=prefer_openclaw`
  - `planner_policy=hermes_fallback`
  - `planner_policy=openclaw_fallback`
- Explicit `planner_backend` still overrides policy selection.
- `planner_policy=auto` is intentionally conservative:
  - keeps native execution for Koto-covered file types such as `docx/xlsx/pptx/pdf/txt/md/csv/json/html`
  - prefers Hermes when the request targets unsupported file types or clearly cross-system/browser-style tasks
  - falls back to native when no external planner backend is currently available

### Phase 5: Capability Registry

Status: partially implemented.

- Added a conservative capability helper in `app/core/agent/file_task_capability.py`.
- Current classifier covers:
  - supported native file types
  - unsupported file-type detection
  - external-system/browser-task hints
- External planners are still only consulted when the request appears to exceed the native file-task surface.
- Remaining work is a richer capability matrix based on tool families and task semantics rather than simple heuristics.

### Phase 6: UI and Observability

Status: implemented for the current planner, capability-gap, and follow-up queue surface.

- Surface planner selection and planner fallback events in the file-task timeline.
- Show whether a task used:
  - native Koto planner
  - Hermes planner bridge
  - OpenClaw planner bridge
- Current backend observability is available through `GET /api/editor/ai/planner-support`, including backend transport.
- `FileTaskRuntime` now emits:
  - `planner.selected`
  - `planner.fallback`
  - `tool.missing`
- `FileTaskModelClient` now annotates responses with planner metadata so runtime events reflect the actual selected backend and fallback path.
- When a planner reports `tool_gap`, `FileTaskRuntime` now synthesizes a machine-readable `next_action_artifact` so the missing capability is preserved as a reusable Koto follow-up spec instead of a transient log message.
- `web/app.py` persists each `next_action_artifact` through `FileTaskFollowupStore` and attaches a `followup_record` to the SSE event payload.
- `GET /api/editor/ai/tool-followups` lists persisted follow-up records.
- `POST /api/editor/ai/tool-followups/<record_id>/status` updates a record status (`open`, `accepted`, `done`, or `dismissed`).
- `web/static/js/workspace-ai-task.js` now renders planner rows, `tool.missing`, the expandable `next_action_artifact`, and the persisted follow-up record/action in both the timeline and final summary so users can inspect and accept the proposed next Koto step.
- Remaining UI work is optional polish rather than missing capability:
  - better localized labels for planner policies/transports
  - richer visual distinction between native planning and external planning

### Phase 7: Legacy Task Path Cleanup

Status: implemented for the file-assistant route and `KotoAgentLoop`.

- `/api/editor/ai/task-stream` is the canonical Koto-native file-task SSE route.
- `/api/editor/ai/stream` rejects `action=ai_task` and points callers to `/api/editor/ai/task-stream`.
- `KotoAgentLoop` no longer contains the old provider-native `_run_task_mode`, old task registry construction, or old non-streaming task LLM loop.
- `RequestValidator` no longer builds the old file-task system prompt for `action_type=ai_task`.
- `TaskAgent` is intentionally retained because `app/core/skills/skill_runner.py` still uses it for non-file-assistant skill execution.

## Command Bridge Contract

Koto sends a JSON object to the configured planner command over stdin with these fields:

- `backend`
- `request`
- `messages`
- `system`
- `tools`

The bridge must print one JSON object to stdout containing at least one of:

- `content`
- `tool_calls`
- `tool_gap`

`tool_calls` must stay compatible with Koto's existing file-task runtime shape.

`tool_gap` is the escape hatch used when the external planner determines that Koto does not currently have a matching native tool for the next required step. It should contain:

- `summary`
- `missing_capability`
- `why_missing`
- `suggested_next_step`
- optional `proposed_tool`

`proposed_tool` is intentionally scoped to the smallest next capability Koto should add, rather than a broad platform redesign.

Koto may then synthesize its own `next_action_artifact` from `tool_gap` to preserve the missing-tool hand-off as a stable internal follow-up spec. At the web boundary, Koto also persists that artifact as a `FileTaskFollowupStore` record so the hand-off survives beyond the SSE stream.

## Embedded Hermes Bridge Contract

- Koto supplies Hermes with:
  - the normalized file-task request
  - the current Koto message state
  - the Koto system/runtime rules
  - the allowlisted Koto tool schemas
- Hermes is constrained to planning-only mode:
  - Hermes toolsets are disabled
  - Hermes does not get write authority over workspace files
  - Hermes must return one JSON object with `content`, `tool_calls`, and optionally `tool_gap`
- Koto remains the execution and verification boundary even when Hermes is selected.

## Missing Tool Hand-Off

- If the next step can be completed with existing Koto tools, the external planner returns normal `tool_calls`.
- If the next step cannot be completed because Koto lacks the needed capability, the external planner must not fake a tool call.
- Instead, it returns `tool_gap` so Koto can:
  - stop the runtime cleanly instead of looping write guards
  - show the user the exact missing capability
  - preserve a concrete next-step recommendation
  - optionally surface a one-tool design proposal for future native implementation
- `FileTaskRuntime` now emits `tool.missing` for this case, synthesizes a `next_action_artifact`, and includes that artifact in `check.finished` and `run.finished`.
- The SSE route persists artifacts into `config/file_task_followups.json` by default, or the path specified by `KOTO_FILE_TASK_FOLLOWUP_PATH`.
- Follow-up records are deduped by stable artifact identity, track occurrence counts, and support status transitions through the tool-followup API.
- `next_action_artifact` currently carries:
  - artifact type/category metadata
  - the original source task and target path
  - the missing capability and why it is missing
  - the recommended next Koto step
  - acceptance criteria for the smallest next native capability
  - optional normalized `proposed_tool`
- The frontend timeline and final summary both render this artifact as an expandable follow-up spec plus its persisted follow-up status/action.

## Current Regression Coverage

- `tests/unit/test_file_task_runtime.py` covers typed runtime events, planner metadata, `tool_gap`, xlsx-to-docx write loops, PPTX write-intent detection, tool catalog coverage, allowlisting, and model-client routing.
- `tests/unit/test_file_task_followup.py` covers stable follow-up upsert/dedupe and status validation.
- `tests/test_ai_stream.py::TestEditorAIStream::test_whitebox_task_stream_surfaces_tool_gap_followup_artifact` covers SSE persistence, follow-up record injection, list API, and status API.
- `tests/test_ai_stream.py::TestEditorAIStream::test_ai_task_action_is_disabled` covers the retired `/api/editor/ai/stream?action=ai_task` route behavior.
- `tests/unit/test_agent_loop_legacy_cleanup.py` guards against reintroducing the old `KotoAgentLoop` task mode.
- `tests/unit/test_workspace_render_perf_guards.py` statically guards the extracted whitebox task renderer and follow-up UI strings/routes.

## Why This Direction

- It preserves Koto's existing verified whitebox write loop.
- It lets external planners improve long-tail task planning without bypassing Koto's tool boundary.
- It avoids early lock-in to either upstream project's internal CLI or gateway protocol.
- It keeps OpenClaw integration decoupled while Hermes proves the external planner pattern first.
- It is testable with small unit slices and route regressions before any broad runtime rollout.