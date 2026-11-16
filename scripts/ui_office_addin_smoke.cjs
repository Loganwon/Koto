/* Production add-in UI, bridge and host adapters; model/Office SDK fixtures. */
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const { chromium } = require('../.venv/Lib/site-packages/playwright/driver/package');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'build/office-addin-qa');
fs.mkdirSync(output, { recursive: true });
const runtime = fs.mkdtempSync(path.join(output, 'runtime-'));
const backend = spawn(path.join(root, '.venv/Scripts/python.exe'),
  [path.join(__dirname, 'ui_office_addin_backend.py'), runtime],
  { cwd: root, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, windowsHide: true });
const pending = new Map();
let sequence = 0, resolveReady;
const ready = new Promise(resolve => { resolveReady = resolve; });
readline.createInterface({ input: backend.stdout }).on('line', line => {
  let result; try { result = JSON.parse(line); } catch { return; }
  if (result.origin) { resolveReady(result.origin); return; }
  const waiter = pending.get(result.id); if (!waiter) return;
  pending.delete(result.id); clearTimeout(waiter.timer);
  if (result.error) waiter.reject(new Error(result.error)); else waiter.resolve(result);
});
let stderr = '';
backend.stderr.on('data', data => { stderr += data.toString(); });
backend.on('exit', code => {
  for (const waiter of pending.values()) waiter.reject(new Error('Backend exited ' + code + ': ' + stderr));
});
function request(value) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('HTTP handler timeout: ' + value.path)); }, 35000);
    pending.set(id, { resolve, reject, timer }); backend.stdin.write(JSON.stringify({ id, ...value }) + '\n');
  });
}

(async () => {
  let browser;
  const passed = [], errors = [];
  try {
    const origin = await Promise.race([ready, new Promise((_, reject) => setTimeout(() => reject(new Error('Backend startup timeout: ' + stderr)), 20000))]);
    browser = await chromium.launch({ headless: true });
    for (const host of ['wps', 'word']) {
      const context = await browser.newContext({ viewport: { width: 380, height: 860 }, colorScheme: 'light' });
      const fixture = fs.readFileSync(path.join(root, 'companion/tests/' + host + '_sdk_fixture.js'), 'utf8');
      await context.addInitScript({ content: fixture + (host === 'wps'
        ? "\nwindow.fixtureSelection=new FixtureWpsRange(0,fixtureText.indexOf('\\r'));" : '') });
      await context.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url());
        if (url.origin !== origin) return route.fulfill({ status: url.pathname.endsWith('/office.js') ? 200 : 404, body: '' });
        try {
          const response = await request({ method: req.method(), path: url.pathname + url.search,
            headers: await req.allHeaders(), body: req.postData() || '' });
          await route.fulfill({ status: response.status, headers: response.headers, body: Buffer.from(response.body, 'base64') });
        } catch (error) {
          errors.push(host + ': ' + String(error));
          await route.fulfill({ status: 500, body: '' }).catch(() => {});
        }
      });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(host + ': ' + error.message));
      await page.goto(origin + '/ui/?host=' + host, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => document.querySelector('#selection-hint').textContent.includes('已选'));
      const documentName = await page.locator('#target-name').textContent();
      assert.equal(await page.locator('#host-name').textContent(), host === 'wps' ? 'WPS 文字' : 'Word');
      assert.equal(await page.locator('#files-pane').isVisible(), false);
      assert.equal(await page.locator('#wa-canvas').count(), 0);
      await page.screenshot({ animations: 'disabled', path: path.join(output, host + '-entry.png') });
      await page.getByRole('button', { name: '润色文字', exact: true }).click();
      assert.match(await page.locator('#instruction').inputValue(), /保留事实/);
      assert.equal(await page.evaluate(() => fixtureWrites), 0);
      await page.locator('#instruction').dispatchEvent('keydown', { key: 'Enter', isComposing: true, keyCode: 229 });
      await page.locator('#instruction').dispatchEvent('keydown', { key: 'Enter', isComposing: false, keyCode: 229 });
      assert.equal(await page.evaluate(() => fixtureWrites), 0);
      assert.equal(await page.locator('#start').textContent(), '发送');
      await page.locator('#start').click();
      await page.waitForFunction(() => document.querySelector('#start').textContent === '开始');
      assert.equal(await page.evaluate(() => fixtureWrites), 0, 'preparation must remain read-only');
      await page.locator('#start').click();
      await page.waitForFunction(() => document.querySelector('#start').textContent === '继续');
      assert.equal(await page.evaluate(() => fixtureWrites), 1);
      assert.equal(await page.locator('#change-preview').evaluate(element => element.open), true);
      assert.equal(await page.locator('#target-name').textContent(), documentName, 'the task must keep the actual host document name');
      assert.match(await page.locator('#after').textContent(), /营收240万元/);
      assert.equal(await page.locator('#activity-list li[data-status="done"]').count() >= 2, true);
      assert.equal(await page.locator('#activity-list').textContent().then(text => text.includes('写回原文并读回核对')), true);
      await page.screenshot({ animations: 'disabled', path: path.join(output, host + '-editing.png') });
      if (host === 'wps') {
        await page.evaluate(() => {
          window.originalFixtureDocument=window.wps.ActiveDocument;
          window.wps.ActiveDocument={...window.originalFixtureDocument,Name:'另一个文档.docx',FullName:'C:/synthetic/other.docx'};
        });
        await page.locator('#binding-notice').waitFor({ state: 'visible' });
        assert.equal(await page.locator('#target-name').textContent(), documentName);
        assert.match(await page.locator('#binding-notice').textContent(), /本任务仍绑定/);
        await page.evaluate(() => { window.wps.ActiveDocument=window.originalFixtureDocument; });
        await page.locator('#binding-notice').waitFor({ state: 'hidden' });
      }
      await page.locator('#instruction').fill('保留未发送的反馈');
      await page.locator('#files-toggle').click();
      await page.locator('#files-close').click();
      assert.equal(await page.locator('#instruction').inputValue(), '保留未发送的反馈');
      await page.locator('#instruction').fill('把这段拆成两句，保留数字');
      await page.locator('#start').click();
      await page.waitForFunction(() => fixtureWrites === 2 && document.querySelector('#start').textContent === '继续');
      assert.match(await page.locator('#after').textContent(), /增长原因有待进一步分析/);
      for (const width of [320, 480]) {
        await page.setViewportSize({ width, height: 860 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        assert.equal(await page.locator('#instruction').isVisible(), true);
        const box = await page.locator('#start').boundingBox();
        assert(box.y + box.height <= 860 && box.x + box.width <= width);
      }
      await page.evaluate(() => { window.fixtureText = '用户手动修改。' + fixtureText; });
      await page.locator('#instruction').fill('请再精简这处文字');
      await page.locator('#start').click();
      await page.locator('#error').waitFor({ state: 'visible' });
      assert.equal(await page.evaluate(() => fixtureWrites), 2, 'a manual edit must not be overwritten');
      passed.push(host + ': native selection → read-only preparation → native write/readback → visible diff → same-task feedback → conflict protection; 320/380/480px layouts');
      await context.close();
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ mode: 'production-code-with-model-and-SDK-fixtures', passed, errors }, null, 2));
    console.log(JSON.stringify({ passed, errors }, null, 2));
  } catch (error) {
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ passed, errors, failure: String(error.stack || error), stderr }, null, 2));
    throw error;
  } finally {
    if (browser) await browser.close();
    backend.kill();
    for (const waiter of pending.values()) { clearTimeout(waiter.timer); waiter.reject(new Error('QA finished')); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
