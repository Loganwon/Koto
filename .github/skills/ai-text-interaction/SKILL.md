---
name: ai-text-interaction
description: 'Enhance AI-text interaction in Koto file assistant. Use when: modifying workspace-assistant.js or workspace assistant templates; adding new AI actions; editing prompts in _build_editor_prompt or socket_handler PROMPTS; working on selection-to-AI pipeline; debugging streaming SSE or WebSocket flows.'
---

# AI Text Interaction Skill

## Architecture Overview

The current Koto file assistant uses a single workspace-assistant frontend surface plus shared backend AI endpoints.

### Frontend Surface
1. **`web/static/js/workspace-assistant.js`** — Main workspace assistant UI, selection actions, streaming chat, proposals, chart rendering
2. **`web/templates/workspace_assistant.html`** — Standalone page shell for `/workspace-assistant`
3. **`web/templates/index.html`** — Embedded workspace assistant host inside the main app
4. **`web/univer-editor/sheets-main.js`** — Separate Sheets runtime bundle source that exports `window.KotoSheetsAPI`

### Backend Endpoints
1. **`/api/editor/ai/stream`** (SSE) — Text actions (polish, translate, etc.)
2. **`/api/editor/ai/chart`** (SSE) — Chart code generation + sandbox execution
3. **`/api/editor/ai/chart-rerun`** (JSON) — Direct code execution without LLM
4. **WebSocket `/doc` namespace** — Real-time streaming via `socket_handler.py`

### Source Files
- `web/static/js/workspace-assistant.js`
- `web/templates/workspace_assistant.html`
- `web/templates/index.html`
- `web/templates/_workspace_model_controls.html`
- `web/univer-editor/sheets-main.js`
- `web/app.py` (functions: `_build_editor_prompt`, `editor_ai_stream`, `editor_ai_chart`, `editor_ai_chart_rerun`)
- `app/core/socket_handler.py` (PROMPTS dict, `on_doc_ai_request`)

## Key Design Principles

1. **Preview-first**: AI output NEVER auto-applies. Always shown in panel first with action buttons.
2. **Streaming**: All text results stream via SSE (`token` events) with typewriter effect.
3. **Full-text context**: `_build_editor_prompt` receives `full_text` so AI can match document tone.
4. **Selection precision**: `selectionRange = {startOffset, endOffset}` tracked for targeted replacement.

## Adding a New AI Action

### Step 1: Register the action
Add the action to the current workspace assistant action registry and UI triggers in `web/static/js/workspace-assistant.js`.

### Step 2: Add handler in `_onAction()`
Update the current workspace assistant action dispatch path so the new action produces the expected SSE or task request payload.

### Step 3: Add UI affordances (optional)
If the action should appear in quick actions, selection menus, or slash-command style helpers, wire it into the current `workspace-assistant.js` UI flow.

### Step 4: Add backend prompt
In `web/app.py`, add a branch to `_build_editor_prompt()`:
```python
elif action == "action_name":
    return "Your prompt template here\n\n" + selection
```

### Step 5: Add result buttons
Update the workspace assistant result rendering path so the new action offers the right accept/apply affordances.

## Build Process

After editing sheet-runtime files, rebuild with the runtime pipeline:
```powershell
cd web/univer-editor
npm run build
```

This command builds:
- Sheets bundle (`sheets-main.js`, `sheets-main.css`)
- stale asset cleanup (removes old legacy bundles)

## Data Flow

```
User selects text → workspace-assistant selection handler
  → Quick actions / assistant UI appears
  → User clicks action
  → workspace-assistant request dispatcher
  → POST /api/editor/ai/stream {action, selection, instruction, full_text}
  → SSE: token events → stream renderer updates UI
  → SSE: done event → finalize response and show action buttons
  → User clicks "接受修改" → workspace-assistant applies the result into the active file view
```

## Common Pitfalls

- **Legacy source split is gone**: `web/univer-editor/src/*` is no longer the live file assistant surface. Current behavior lives in `web/static/js/workspace-assistant.js`.
- **Selection tracking**: `fullText.indexOf(selectedText)` style fallbacks can still match the wrong position if text repeats.
- **Token limits**: Truncate `full_text` to a safe size in prompts to avoid model token blowups.
- **Sheets assets are still live**: Do not remove `web/static/univer-dist/assets/sheets-main.js` or `sheets-main.css`; the workspace assistant still loads them.
