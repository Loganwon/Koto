# AI Assistant Testing

This repo now has a dedicated regression system for the workspace AI assistant and whitebox file-task flow.

The suite is organized into eight lanes:

- `smoke`: critical routing and runtime regressions that should stay green on every AI assistant flow change.
- `contracts`: source-level guards for the bundled TypeScript workspace task chain (`ai-review.ts`, `task-dispatcher.ts`, `task-runner.ts`, and related renderer contracts).
- `backend`: Flask `POST /api/editor/ai/task-stream` behavior, SSE event contract, request normalization, and session/memory persistence.
- `runtime`: file-task runtime, planner routing, tool-gap normalization, and provider fallback behavior.
- `matrix`: task-family routing matrix, recipe coverage, and completion-contract guards for common write/read task families.
- `browser-mock`: Playwright smoke for the real workspace page, including a mocked `task-stream` response so task cards render without a real model. The old `browser` name remains as a compatibility alias.
- `mcp`: MCP route, WebSocket, frontend-action, and stdio bridge contract checks.
- `evaluation`: deterministic offline checks of intent, streaming and execution/judging contracts for daily regression runs. Fixed model responses exercise the application path but do not measure real model quality. Set `KOTO_LIVE_EVALUATION=1` to run the same lane with real LLM calls and AI-as-Judge.

Important distinction: `browser-mock` is not a real frontend file-task execution. It verifies browser UI wiring and mocked task-card rendering only. A real frontend/MCP validation must open the live Koto page, submit from the UI, observe visible task progress, verify produced files, and separately prove MCP `initialize`, `tools/list`, and at least one `tools/call`.

## Browser Prerequisites

The `browser-mock`, `browser` alias, `test-ready`, and `release` lanes require Playwright support in the Python test environment.

Install the Python packages:

```powershell
pip install pytest-playwright playwright
```

Install the browser runtime once on the machine:

```powershell
python -m playwright install chromium
```

If those prerequisites are missing:

- direct `pytest tests/e2e/...` runs will skip browser tests instead of failing with a missing `page` fixture error
- `python scripts/run_ai_assistant_flow_tests.py browser-mock`, `browser`, `test-ready`, and `release` will stop early with an explicit prerequisite message

Two composite lanes are defined in [scripts/run_ai_assistant_flow_tests.py](../scripts/run_ai_assistant_flow_tests.py):

- `full`: `smoke + contracts + backend + runtime + matrix`
- `release`: `full + browser-mock`
- `test-ready`: `smoke + mcp + browser-mock`

## Commands

List the suite catalog:

```powershell
python scripts/run_ai_assistant_flow_tests.py --list
```

Run the fast critical checks after any AI assistant flow change:

```powershell
python scripts/run_ai_assistant_flow_tests.py smoke -vv
```

Run the full non-browser regression pack:

```powershell
python scripts/run_ai_assistant_flow_tests.py full -vv
```

Run the task-family matrix only:

```powershell
python scripts/run_ai_assistant_flow_tests.py matrix -vv
```

Run the mocked browser smoke lane only:

```powershell
python scripts/run_ai_assistant_flow_tests.py browser-mock -vv
```

Run the MCP contract lane only:

```powershell
python scripts/run_ai_assistant_flow_tests.py mcp -vv
```

Run the test-ready preflight before a real frontend/MCP manual pass:

```powershell
python scripts/run_ai_assistant_flow_tests.py test-ready -vv
```

Run the offline evaluation contract lane (no model quality claim):

```powershell
.\.venv\Scripts\python.exe scripts/run_ai_assistant_flow_tests.py evaluation -vv
```

Run the live-model quality evaluation lane:

```powershell
$env:KOTO_LIVE_EVALUATION = "1"
.\.venv\Scripts\python.exe scripts/run_ai_assistant_flow_tests.py evaluation -vv
```

The execution cases request cloud model mode, so live evaluation requires valid configured cloud credentials and a reachable endpoint. The judge uses the canonical configured Koto runtime gateway. The default offline fixtures replace both the one-shot and streaming generation entrypoints only when live evaluation is disabled, and reject accidental native-provider calls. A passing offline lane is not evidence of real model accuracy, editing quality or provider availability.

Run the release lane before merging larger flow changes:

```powershell
python scripts/run_ai_assistant_flow_tests.py release -vv
```

The runner passes extra arguments through to `pytest`, so `-k`, `-x`, `-vv`, or `--headed` can be appended as needed.

All lanes run with `KOTO_SKIP_BACKGROUND_RUNTIME=1`. This keeps task-stream and
browser-mock assertions isolated from production schedulers, model warmups, and
file watchers; it does not replace a real desktop startup or live-frontend test.

## Coverage Map

- Workspace send-message entry and payload wiring: [tests/test_ai_stream.py](../tests/test_ai_stream.py) and [tests/unit/test_ai_task_chain_architecture.py](../tests/unit/test_ai_task_chain_architecture.py)
- Whitebox task-stream SSE contract and persistence: [tests/test_ai_stream.py](../tests/test_ai_stream.py)
- File-task runtime and native routing: [tests/unit/test_file_task_runtime.py](../tests/unit/test_file_task_runtime.py)
- File-task safety, deterministic classification, and routing-contract coverage: [tests/unit/test_file_task_safety_matrix.py](../tests/unit/test_file_task_safety_matrix.py), [tests/unit/test_file_task_classification_policy.py](../tests/unit/test_file_task_classification_policy.py), [tests/unit/test_file_task_classification_architecture.py](../tests/unit/test_file_task_classification_architecture.py), and [tests/unit/test_file_task_routing_decision_contract.py](../tests/unit/test_file_task_routing_decision_contract.py)
- Provider timeout and local routing behavior: [tests/unit/test_llm_providers.py](../tests/unit/test_llm_providers.py) and [tests/unit/test_file_task_runtime.py](../tests/unit/test_file_task_runtime.py)
- Browser-level assistant shell and mocked task-card rendering: [tests/e2e/test_workspace_ai_assistant.py](../tests/e2e/test_workspace_ai_assistant.py)
- MCP route, frontend-action, WebSocket, and stdio bridge contracts: [tests/unit/test_mcp_integration.py](../tests/unit/test_mcp_integration.py)

## Update Rule

Whenever the AI assistant flow changes, update both:

- the relevant behavior tests
- the lane definition in [scripts/run_ai_assistant_flow_tests.py](../scripts/run_ai_assistant_flow_tests.py) if the critical path moved or a new lane is needed

If a flow change is large enough to alter the routing boundary, the minimum expectation is:

1. `smoke` stays green during development.
2. `full` passes before the flow is considered stable.
3. `release` passes before merging any user-visible assistant workflow rewrite.

When the claim is "tested from the Koto frontend" or "MCP is truly connected", do not use `release` or `browser-mock` as the final evidence. Treat them as preflight checks before the live UI and MCP smoke.
