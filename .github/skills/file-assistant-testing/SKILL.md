---
name: file-assistant-testing
description: 'Test Koto file assistant features. Use when: writing tests for AI panel, floating toolbar, chart generation, find-replace, or reference search; setting up Playwright E2E tests; creating mock LLM fixtures; debugging test failures in the file assistant.'
---

# File Assistant Testing Skill

## Test Architecture

```
tests/
  conftest.py              ← Flask app + Playwright + mock LLM fixtures
  test_ai_stream.py        ← Backend SSE endpoint tests (no browser)
  test_sandbox.py           ← Sandbox code execution tests (no browser)
  test_floating_toolbar.py  ← Playwright: selection → toolbar → actions
  test_ai_panel.py          ← Playwright: AI panel streaming + proposals
  test_find_replace.py      ← Playwright: find-replace UI interaction
  test_chart_flow.py        ← Playwright: chart generation full flow
```

## Running Tests

```powershell
# Backend API tests only (fast, no browser)
cd C:\Users\12524\Desktop\Koto
.venv\Scripts\python -m pytest tests/test_ai_stream.py tests/test_sandbox.py -v

# E2E with Playwright (needs app running)
.venv\Scripts\python -m pytest tests/test_floating_toolbar.py --headed -v

# With mock LLM (no real API calls)
.venv\Scripts\python -m pytest tests/ -v -k "mock"
```

## Mock LLM Pattern

```python
@pytest.fixture
def mock_llm(monkeypatch):
    """Replace real LLM calls with deterministic outputs."""
    def fake_stream(model, contents, config=None):
        class FakeChunk:
            def __init__(self, text):
                self.text = text
        if '润色' in contents:
            yield FakeChunk('这是润色后的优雅文本。')
        elif '替换' in contents:
            yield FakeChunk('{"replacements": [{"from": "你好", "to": "您好"}], "summary": "共1处"}')
        elif '引用' in contents:
            yield FakeChunk('1. 【论文】示例研究 — 关键发现\n   链接：https://example.com')
        else:
            yield FakeChunk('AI 回复内容。')
    
    monkeypatch.setattr(
        'web.app.client.models.generate_content_stream',
        fake_stream
    )
```

## Key Test Patterns

### Backend SSE Test
```python
def test_polish_with_full_context(client):
    resp = client.post('/api/editor/ai/stream', json={
        'action': 'polish',
        'selection': '这段文字需要润色。',
        'full_text': '这是一篇关于技术的文章。这段文字需要润色。后面还有更多内容。',
    })
    assert resp.status_code == 200
    assert resp.content_type == 'text/event-stream'
    events = [json.loads(line.split('data: ')[1]) 
              for line in resp.data.decode().split('\n\n') 
              if line.startswith('data: ')]
    assert any(e['type'] == 'token' for e in events)
    assert events[-1]['type'] == 'done'
```

### Playwright E2E Test
```python
async def test_toolbar_appears_on_selection(page):
    await page.goto('http://localhost:5000/editor')
    await page.wait_for_selector('#center-doc', timeout=10000)
    
    # Simulate text selection
    editor = page.locator('#center-doc')
    await editor.click()
    await page.keyboard.type('Hello World Test Text')
    await page.keyboard.press('Home')
    await page.keyboard.down('Shift')
    for _ in range(10):
        await page.keyboard.press('ArrowRight')
    await page.keyboard.up('Shift')
    
    # Check toolbar appears
    toolbar = page.locator('#floating-ai-toolbar')
    await expect(toolbar).to_be_visible(timeout=3000)
```

### Chart Rerun Test
```python
def test_chart_rerun_executes_code(client):
    resp = client.post('/api/editor/ai/chart-rerun', json={
        'code': 'import matplotlib.pyplot as plt\nplt.plot([1,2,3])\nplt.savefig("chart.png")\nplt.close()',
        'lang': 'python',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['error'] is None or data['error'] == ''
    assert 'chart.png' in data.get('files', {})
```

## SSE Event Parsing Helper
```python
def parse_sse_events(response_data: bytes) -> list[dict]:
    """Parse SSE response into list of event dicts."""
    events = []
    for line in response_data.decode('utf-8').split('\n\n'):
        line = line.strip()
        if line.startswith('data: '):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events
```

## What to Test for Each Feature

| Feature | Backend Test | E2E Test |
|---------|-------------|----------|
| Polish with context | SSE returns tokens + done | Diff view appears, accept button works |
| Find & Replace | SSE returns JSON replacements | Preview list renders, checkboxes work |
| Reference Search | SSE returns formatted references | Insert button adds footnote |
| Chart Generation | SSE returns code + image events | Image renders, download works |
| Chart Rerun | JSON returns files | New image replaces old |
| Toolbar Pin | N/A | Toolbar stays visible after pin |
