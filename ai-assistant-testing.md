# AI Assistant Testing

This repo now has a dedicated regression system for the workspace AI assistant and whitebox file-task flow.

The suite is organized into five lanes:

- `smoke`: critical routing and runtime regressions that should stay green on every AI assistant flow change.
- `contracts`: source-level guards for `workspace-assistant.js`, `workspace-task-dispatcher.js`, and related renderer contracts.
- `backend`: Flask `POST /api/editor/ai/task-stream` behavior, SSE event contract, request normalization, and session/memory persistence.
- `runtime`: file-task runtime, planner routing, tool-gap normalization, and provider fallback behavior.
- `browser`: Playwright smoke for the real workspace page, including a mocked `task-stream` response so task cards render without a real model.

## Browser Prerequisites

The `browser` and `release` lanes require Playwright support in the Python test environment.

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
- `python scripts/run_ai_assistant_flow_tests.py browser` and `release` will stop early with an explicit prerequisite message

Two composite lanes are defined in [scripts/run_ai_assistant_flow_tests.py](scripts/run_ai_assistant_flow_tests.py):

- `full`: `smoke + contracts + backend + runtime`
- `release`: `full + browser`

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

Run the browser smoke lane only:

```powershell
python scripts/run_ai_assistant_flow_tests.py browser -vv
```

Run the release lane before merging larger flow changes:

```powershell
python scripts/run_ai_assistant_flow_tests.py release -vv
```

The runner passes extra arguments through to `pytest`, so `-k`, `-x`, `-vv`, or `--headed` can be appended as needed.

## Coverage Map

- Workspace send-message entry and payload wiring: [tests/test_ai_stream.py](tests/test_ai_stream.py)
- Whitebox task-stream SSE contract and persistence: [tests/test_ai_stream.py](tests/test_ai_stream.py)
- File-task runtime and native routing: [tests/unit/test_file_task_runtime.py](tests/unit/test_file_task_runtime.py)
- Provider timeout and local routing behavior: [tests/unit/test_llm_providers.py](tests/unit/test_llm_providers.py) and [tests/unit/test_file_task_runtime.py](tests/unit/test_file_task_runtime.py)
- Browser-level assistant shell and task-card rendering: [tests/e2e/test_workspace_ai_assistant.py](tests/e2e/test_workspace_ai_assistant.py)

## Update Rule

Whenever the AI assistant flow changes, update both:

- the relevant behavior tests
- the lane definition in [scripts/run_ai_assistant_flow_tests.py](scripts/run_ai_assistant_flow_tests.py) if the critical path moved or a new lane is needed

If a flow change is large enough to alter the routing boundary, the minimum expectation is:

1. `smoke` stays green during development.
2. `full` passes before the flow is considered stable.
3. `release` passes before merging any user-visible assistant workflow rewrite.
