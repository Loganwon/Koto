---
name: ai-text-interaction
description: 'Enhance AI-text interaction in Koto file assistant. Use when: modifying FloatingToolbar, AIPanel, SocketBridge, DocController; adding new AI actions; editing prompts in _build_editor_prompt or socket_handler PROMPTS; working on selection-to-AI pipeline; debugging streaming SSE or WebSocket flows.'
---

# AI Text Interaction Skill

## Architecture Overview

The Koto file assistant has a 4-module frontend + 2-endpoint backend architecture for AI-text interaction:

### Frontend Modules
1. **FloatingToolbar.js** — Selection detection + action buttons
2. **AIPanel.js** — Right panel: slash commands, streaming chat, proposals, chart rendering
3. **SocketBridge.js** — WebSocket bridge to `/doc` namespace
4. **DocController.js** — Univer document operations (read/write/replace)

### Backend Endpoints
1. **`/api/editor/ai/stream`** (SSE) — Text actions (polish, translate, etc.)
2. **`/api/editor/ai/chart`** (SSE) — Chart code generation + sandbox execution
3. **`/api/editor/ai/chart-rerun`** (JSON) — Direct code execution without LLM
4. **WebSocket `/doc` namespace** — Real-time streaming via `socket_handler.py`

### Source Files
- `web/univer-editor/src/FloatingToolbar.js`
- `web/univer-editor/src/AIPanel.js`
- `web/univer-editor/src/SocketBridge.js`
- `web/univer-editor/src/DocController.js`
- `web/univer-editor/style.css`
- `web/app.py` (functions: `_build_editor_prompt`, `editor_ai_stream`, `editor_ai_chart`, `editor_ai_chart_rerun`)
- `app/core/socket_handler.py` (PROMPTS dict, `on_doc_ai_request`)

## Key Design Principles

1. **Preview-first**: AI output NEVER auto-applies. Always shown in panel first with action buttons.
2. **Streaming**: All text results stream via SSE (`token` events) with typewriter effect.
3. **Full-text context**: `_build_editor_prompt` receives `full_text` so AI can match document tone.
4. **Selection precision**: `selectionRange = {startOffset, endOffset}` tracked for targeted replacement.

## Adding a New AI Action

### Step 1: Register the action
Add to `SLASH_COMMANDS` array in AIPanel.js:
```javascript
{ cmd: '/命令', action: 'action_name', icon: '🔤', hint: '描述' },
```

### Step 2: Add handler in `_onAction()`
In AIPanel.js `_onAction()`, add a new branch:
```javascript
if (actionType === 'action_name') {
  // Get selection or full text as needed
  const selection = this._doc.getSelection();
  this.addMessage('Label', 'user');
  this._sendViaMainAI('action_name', text, selection, '');
  return;
}
```

### Step 3: Add to FloatingToolbar (optional)
Add to `PRIMARY_ACTIONS` or `SECONDARY_ACTIONS` array in FloatingToolbar.js.

### Step 4: Add backend prompt
In `web/app.py`, add a branch to `_build_editor_prompt()`:
```python
elif action == "action_name":
    return "Your prompt template here\n\n" + selection
```

### Step 5: Add result buttons
In AIPanel.js `_buildApplyButtons()`, add handling for the new action type.

## Build Process

After editing frontend files, rebuild with esbuild:
```powershell
cd web/univer-editor
.\node_modules\@esbuild\win32-x64\esbuild.exe main.js --bundle --outdir=../static/univer-dist/assets --format=esm --splitting --loader:.css=css --minify --sourcemap "--define:__VUE_OPTIONS_API__=true" "--define:__VUE_PROD_DEVTOOLS__=false" "--define:__VUE_PROD_HYDRATION_MISMATCH_DETAILS__=false"
```

## Data Flow

```
User selects text → FloatingToolbar._checkSelection()
  → Toolbar appears with action buttons
  → User clicks action
  → AIPanel._onAction(type)
  → AIPanel._sendViaMainAI(type, text, ctx, instruction)
  → POST /api/editor/ai/stream {action, selection, instruction, full_text}
  → SSE: token events → appendStreamChunk()
  → SSE: done event → finalizeStreamMessage() → action buttons
  → User clicks "接受修改" → DocController.replaceRange()
```

## Common Pitfalls

- **Univer 0.5.x limitation**: No `replaceText()` API. All edits go through `_replaceEntireDoc()` (dispose + recreate).
- **Selection tracking**: `fullText.indexOf(selectedText)` may match wrong position if text appears multiple times.
- **Token limits**: Truncate `full_text` to ~8000 chars in prompts to avoid Gemini token limits.
- **esbuild Vue flags**: MUST include `--define` flags or Vue runtime crashes with ReferenceError.
