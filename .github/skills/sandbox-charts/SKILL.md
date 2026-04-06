---
name: sandbox-charts
description: 'Work with Koto sandbox code execution and chart generation. Use when: modifying sandbox.py; adding chart types; debugging Python/R code execution; working on /api/editor/ai/chart or chart-rerun endpoints; editing chart rendering in AIPanel._sendViaChart; troubleshooting matplotlib/pandas output.'
---

# Sandbox & Chart Generation Skill

## Architecture

### Backend: sandbox.py
Location: `app/core/sandbox.py`

- `run_python(code, timeout=30)` — Execute Python with matplotlib auto-capture
- `run_r(code, timeout=30)` — Execute R with ggplot2 auto-capture
- `_run_in_tempdir(lang, cmd, timeout)` — Shared subprocess runner

### Endpoints
- `POST /api/editor/ai/chart` — LLM generates code → sandbox executes → SSE returns images
- `POST /api/editor/ai/chart-rerun` — User-modified code → sandbox executes → JSON returns images

### Frontend: AIPanel.js
- `_sendViaChart(dataContext, instruction)` — SSE stream handler for chart generation
- `_rerunChartCode(code, chartWrap)` — Direct code execution with result rendering

## Chart Generation Flow

```
User selects data → clicks "📊 可视化"
  → AIPanel._sendViaChart(data, '')
  → POST /api/editor/ai/chart {data_context, instruction, lang: 'python'}
  → Backend: LLM generates Python code
  → SSE event {type: 'code', text: '...'}
  → Frontend: Shows collapsible code block with Edit button
  → Backend: Sandbox executes code
  → SSE event {type: 'image', name: 'chart.png', data: 'base64...'}
  → Frontend: Renders <img> with download button
```

## Code Edit & Rerun Flow

```
User clicks "✏️ 编辑" on code block
  → textarea replaces <pre>, "▶ 重新运行" button appears
  → User modifies code
  → clicks "▶ 重新运行"
  → POST /api/editor/ai/chart-rerun {code, lang: 'python'}
  → Backend: sandbox.run_python(code)
  → JSON response: {stdout, stderr, files: {name: base64}, error}
  → Frontend: Removes old images, renders new results
```

## Python Preamble (auto-injected by sandbox.py)

```python
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as _plt
_fig_counter = [0]
_orig_show = _plt.show
def _auto_show(*args, **kwargs):
    _fig_counter[0] += 1
    _plt.savefig(f'figure_{_fig_counter[0]}.png')
    _plt.close('all')
_plt.show = _auto_show
```

## Security Model
- Fresh temp directory per execution (auto-deleted)
- Process killed on timeout (30s default)
- 512KB output size limit
- **No network isolation** (relies on container in production)

## Adding New Chart Types

1. Add chart type to the LLM prompt in `_build_editor_prompt()` for the `chart` action
2. Ensure the code prompt includes specific library imports
3. Test that `plt.savefig()` or `ggsave()` produces output in the temp directory

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| No images generated | Code uses `plt.show()` instead of `plt.savefig()` | Preamble auto-patches, but check |
| Chinese text garbled | Missing font config | Add `matplotlib.rcParams['font.sans-serif']` in code prompt |
| Timeout | Heavy computation | Increase timeout parameter |
| Import error | Missing package | Install in the Python environment |
