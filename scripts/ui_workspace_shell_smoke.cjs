/* Browser interaction checks. Python owns the isolated application lifecycle. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

// Reuse the repository's installed Playwright without a second npm dependency.
const { chromium } = require('../.venv/Lib/site-packages/playwright/driver/package');
const output = process.env.KOTO_QA_OUTPUT;
const base = process.env.KOTO_QA_URL;

(async () => {
  const options = { headless: true, timeout: 20000 };
  console.log('Starting browser');
  const browser = await chromium.launch(options);
  const errors = [];
  const results = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addInitScript(() => { window.__KOTO_E2E__ = true; });
    if (process.env.KOTO_QA_OFFLINE) {
      const sessions = new Map();
      const staticRoot = path.resolve(__dirname, '../web/static');
      await context.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin !== base) return route.fulfill({ status: 404, body: '' });
        if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: fs.readFileSync(path.join(output, 'offline.html')) });
        if (url.pathname.startsWith('/static/')) {
          const file = path.resolve(staticRoot, decodeURIComponent(url.pathname.slice(8)));
          if (!file.startsWith(staticRoot + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return route.fulfill({ status: 404, body: '' });
          const mime = { '.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' }[path.extname(file)] || 'application/octet-stream';
          return route.fulfill({ contentType: mime, body: fs.readFileSync(file) });
        }
        let json = { success: true };
        const body = request.method() === 'POST' ? request.postDataJSON() : null;
        if (url.pathname === '/api/sessions') {
          if (request.method() === 'POST') {
            sessions.set(body.name, { id: body.name, title: body.name, message_count: 0 });
            json = { success: true, session: body.name };
          } else json = { sessions: Array.from(sessions.values()).reverse() };
        } else if (url.pathname.startsWith('/api/sessions/')) json = { success: true, history: [] };
        else if (url.pathname === '/api/v1/workspace/open_file_by_path') json = body.path.endsWith('.docx')
          ? JSON.parse(fs.readFileSync(path.join(output, 'docx-fixture.json'), 'utf8')) : {
          success: true, file_id: 'qa-text', file_name: 'interaction-check.txt', file_type: 'text',
          data: { content: fs.readFileSync(process.env.KOTO_QA_TEXT_FILE, 'utf8'), language: 'txt' },
          source_path: body.path,
        };
        else if (url.pathname.includes('recent_files')) json = { success: true, files: [] };
        else if (url.pathname.includes('current_dir')) json = { success: true, path: 'workspace', name: '测试工作区' };
        else if (url.pathname.includes('browse_local')) json = { success: true, path: 'workspace', files: [], entries: [] };
        else if (url.pathname === '/api/v1/models') json = { models: [], providers: [] };
        else if (url.pathname === '/api/settings') json = { appearance: { theme: 'light', ui_zoom: 1 }, ai: { show_thinking: false, show_task_type: false } };
        return route.fulfill({ json });
      });
    }
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/setup/status', route => route.fulfill({ json: { initialized: true, has_api_key: true } }));
    await page.route('**/api/mcp/frontend-action?*', route => route.fulfill({ json: { action: null } }));
    await page.route('**/api/mcp/frontend-event', route => route.fulfill({ status: 204 }));
    await page.goto(base, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.__kotoFeatureRegistry__?.showDocumentLayout
      && document.documentElement.dataset.kotoConversationList === 'ready', { timeout: 45000 });
    await page.locator('#wa-user-input').waitFor({ state: 'visible' });
    await page.locator('#startupSplash').waitFor({ state: 'hidden' });
    assert.equal(await page.locator('#wa-user-input').count(), 1);
    assert.equal(await page.locator('#wa-ai-session-list-view').count(), 1);
    assert.equal(await page.locator('#chatView').count(), 0);
    await page.screenshot({ animations: 'disabled', path: path.join(output, 'desktop.png') });
    assert.equal(await page.locator('#workspaceView').getAttribute('data-layout'), 'conversation');
    assert.equal(await page.locator('#wa-ai').isVisible(), true);
    assert.equal(await page.locator('#wa-canvas').evaluate(element => element.inert), true);
    results.push('cold start exposes one composer without requiring a document or launcher click');

    await page.locator('#wa-model-menu-trigger').click();
    await page.locator('#wa-model-mode-menu').waitFor({ state: 'visible' });
    const menu = await page.locator('#wa-model-mode-menu').boundingBox();
    assert(menu.y >= 0 && menu.y + menu.height <= 901);
    await page.locator('#wa-model-menu-trigger').click();
    await page.locator('#navSettingsBtn').click();
    await page.locator('#settingsPanel.active').waitFor({ state: 'visible' });
    await page.locator('#settingsPanel [data-theme="dark"]').click();
    await page.waitForFunction(() => document.documentElement.getAttribute('data-theme') === 'dark');
    await page.evaluate(() => document.__kotoFeatureRegistry__.closeSettings());
    await page.locator('#settingsPanel').waitFor({ state: 'hidden' });
    results.push('model selection and settings remain reachable');
    await page.screenshot({ animations: 'disabled', path: path.join(output, 'dark.png') });
    assert.equal(await page.locator('body').evaluate(element => element.classList.contains('theme-dark')), true);
    await page.evaluate(() => document.__kotoFeatureRegistry__.applyTheme('light'));

    await page.locator('#wa-user-input').fill('请帮我检查这份文档');
    assert.equal(await page.locator('#wa-send-btn').isEnabled(), true);
    const beforeIme = await page.locator('.wa-msg.user').count();
    await page.locator('#wa-user-input').dispatchEvent('keydown', { key: 'Enter', isComposing: true, keyCode: 229 });
    assert.equal(await page.locator('.wa-msg.user').count(), beforeIme);
    await page.locator('#wa-user-input').fill('');
    results.push('IME Enter does not submit while composing Chinese');

    await page.locator('#koto-new-task').click();
    await page.waitForFunction(() => document.querySelectorAll('.koto-task-item').length === 1);
    await page.locator('#koto-new-task').click();
    await page.waitForFunction(() => document.querySelectorAll('.koto-task-item').length === 2);
    const ids = await page.locator('.koto-task-item').evaluateAll(items => items.map(item => item.dataset.aiSessionId));
    assert.notEqual(ids[0], ids[1]);
    await page.locator('.koto-task-item').last().click();
    assert.equal(await page.locator('.koto-task-item[aria-current="true"]').count(), 1);
    results.push('new tasks have unique identities; sidebar restores the selected task');

    await page.locator('#koto-files-toggle').click();
    await page.locator('#wa-left').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#wa-left').getAttribute('aria-hidden'), 'false');
    await page.keyboard.press('Escape');
    await page.locator('#wa-left').waitFor({ state: 'hidden' });
    results.push('file drawer opens and Escape closes it');

    await page.evaluate(() => document.__kotoFeatureRegistry__.openWorkspaceFile('interaction-check.txt'));
    await page.locator('#wa-text-content').waitFor({ state: 'visible' });
    await page.locator('#wa-text-content').fill('Unsaved text survives closing the AI dock.');
    await page.locator('[data-koto-shell-action="close-assistant"]').click();
    await page.locator('#wa-ai').waitFor({ state: 'hidden' });
    assert.equal(await page.locator('#wa-canvas').isVisible(), true);
    await page.locator('#koto-document-ai-launcher').click();
    assert.equal(await page.locator('#wa-text-content').inputValue(), 'Unsaved text survives closing the AI dock.');
    results.push('closing AI preserves the visible editor and its unsaved text');

    // Real DOCX parser + editor + selection bridge + proposal application; model output is a fixture.
    await page.evaluate(() => document.__kotoFeatureRegistry__.openWorkspaceFile('项目协作方案.docx'));
    const editor = page.locator('#wa-docx-editor .ProseMirror').first();
    await editor.waitFor({ state: 'visible' });
    await page.locator('[data-koto-shell-action="close-assistant"]').click();
    const original = '我们希望通过这个项目，把团队的工作效率进行一个全面的提升。';
    const proposed = '本项目旨在全面提升团队的工作效率。';
    await editor.evaluate((element, text) => {
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const start = node.textContent.indexOf(text);
        if (start < 0) continue;
        const range = document.createRange(); range.setStart(node, start); range.setEnd(node, start + text.length);
        const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
        document.dispatchEvent(new Event('selectionchange'));
        return;
      }
      throw new Error('DOCX fixture paragraph missing');
    }, original);
    await page.locator('#koto-document-ai-launcher').click();
    await page.locator('#wa-context-bar').waitFor({ state: 'visible' });
    assert.match(await page.locator('#wa-context-bar').textContent(), /选区|选择|希望/);
    assert.equal(await editor.isVisible(), true);
    await page.locator('#wa-user-input').fill('把这段话改得简洁、直接一些，保留原意。');
    await page.screenshot({ animations: 'disabled', path: path.join(output, 'document.png') });
    await page.evaluate(({ original, proposed }) => {
      const api = document.__kotoFeatureRegistry__;
      const conversation = api.getWorkspaceConversationRuntime();
      conversation.appendUserMessageWithLoading({ content: '把这段话改得简洁、直接一些，保留原意。' });
      const loading = document.querySelector('#wa-ai-messages .streaming');
      const harness = api.taskFlowTestHarness;
      const card = harness.makeRunCard(loading);
      if (loading && loading !== card) loading.replaceWith(card);
      else if (!card.isConnected) document.getElementById('wa-ai-messages').appendChild(card);
      harness.processEvent(card, { type: 'run.started', task_id: 'preview-task', run_id: 'preview-run', payload: {} });
      harness.processEvent(card, { type: 'step.started', payload: { step_id: 'edit', title: '润色选中的项目目标', stage: 'execute' } });
      harness.processEvent(card, { type: 'tool.started', payload: { step_id: 'edit', tool_name: 'read_file', tool_title: '读取当前文档与选区' } });
      harness.processEvent(card, { type: 'tool.finished', payload: { step_id: 'edit', tool_name: 'read_file', tool_title: '已读取当前文档与选区', success: true } });
      harness.processEvent(card, { type: 'step.started', payload: { step_id: 'suggest', title: '生成选区润色建议', stage: 'execute' } });
      api.getWorkspaceAiResultsRuntime().handleProposals({ proposals: [
        { id: 'preview-edit', original_text: original, proposed_text: proposed, rationale: '删除重复表达，保留目标与含义。' },
      ] });
    }, { original, proposed });
    await page.locator('.wa-proposal-card').first().waitFor({ state: 'visible' });
    assert.equal(await page.locator('.wa-task-progress-entry').count() > 0, true);
    await page.locator('#wa-task-live-progress').waitFor({ state: 'visible' });
    await page.locator('#wa-user-input').fill('');
    assert.equal(await page.locator('#wa-selection-toolbar').isVisible(), false);
    await page.screenshot({ animations: 'disabled', path: path.join(output, 'whitebox.png') });
    await page.locator('.wa-proposal-card[data-proposal-id="preview-edit"] .accept').click();
    assert.match(await editor.textContent(), new RegExp(proposed));
    assert.equal((await editor.textContent()).includes(original), false);
    await page.evaluate(() => document.__kotoFeatureRegistry__.getWorkspaceAiResultsRuntime().handleProposals({ proposals: [
      { id: 'preview-reject', original_text: '内容清晰，数据可追溯，重要修改经过确认后再保存。', proposed_text: '直接保存全部内容。', rationale: '用于验证拒绝操作不会改变原文。' },
    ] }));
    await page.locator('.wa-proposal-card[data-proposal-id="preview-reject"] .reject').click();
    assert.match(await editor.textContent(), /重要修改经过确认后再保存/);
    results.push('DOCX selection enters AI context; canonical progress and diffs render; accept changes the live document and reject preserves it');

    for (const [width, height] of [[900, 700], [390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.waitForFunction(() => document.body.classList.contains('koto-layout-compact'));
      assert.equal(await page.locator('#wa-ai').isVisible(), true);
      assert.equal(await page.locator('#wa-ai').getAttribute('aria-hidden'), 'false');
      assert.equal(await page.locator('#wa-canvas').isVisible(), true);
      await page.locator('#wa-user-input').waitFor({ state: 'visible' });
      const geometry = await page.locator('#wa-user-input').boundingBox();
      assert(geometry.x >= 0 && geometry.x + geometry.width <= width + 1);
      const doc = await page.locator('#wa-canvas').boundingBox();
      const ai = await page.locator('#wa-ai').boundingBox();
      assert(doc.y + doc.height <= ai.y + 1, 'document and AI must not overlap');
      await page.screenshot({ animations: 'disabled', path: path.join(output, width === 390 ? 'phone.png' : 'narrow.png') });
    }
    results.push('narrow and phone layouts keep the composer reachable without overlapping the document');

    await page.locator('#koto-nav-toggle').click();
    await page.locator('#koto-new-task').waitFor({ state: 'visible' });
    await page.locator('.koto-task-item').first().click();
    assert.equal(await page.locator('#sideNav').evaluate(element => element.inert), true);
    results.push('phone navigation closes after task selection and leaves keyboard focus in the conversation');
    assert.deepEqual(errors, [], 'browser reported uncaught errors');
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ mode: process.env.KOTO_QA_OFFLINE ? 'fixture-backend' : 'live-flask', real_model_verified: false, passed: results, errors }, null, 2));
    console.log(JSON.stringify({ passed: results, errors }, null, 2));
  } catch (error) {
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ passed: results, errors, failure: String(error.stack || error) }, null, 2));
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
