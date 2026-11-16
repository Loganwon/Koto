// Isolated transport regression: recovery notices and native chooser timeout.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const listeners = new Map(), notices = [], timers = [];
let failures = 3, generation = 'one', expired = false;
const sandbox = {
  crypto: require('node:crypto').webcrypto, AbortController,
  CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
  document: { documentElement: { dataset: {} }, getElementById: () => null },
  window: {
    KOTO_EMBEDDED: {host: 'word'},
    addEventListener: (event, callback) => listeners.set(event, callback),
    dispatchEvent: event => { if (event.type === 'kotoconnection') notices.push(event.detail); },
  },
  Event: class { constructor(type) { this.type = type; } },
  KotoNative: { ready: async () => {}, observe: () => new Promise(() => {}) },
  setTimeout: (fn, ms) => { timers.push(ms); if (ms < 1000) setImmediate(fn); return ms; },
  clearTimeout: () => {},
  fetch: async path => {
    if (path === '/host/poll') return new Promise(() => {});
    if (path === '/host/bootstrap') return {ok: true, json: async () => ({token: 'test', generation})};
    if (path === '/host/attach') return {ok: true, json: async () => ({channel: generation})};
    if (expired) { expired = false; generation = 'two'; return {ok: false, status: 403}; }
    if (path === '/api/status' && failures-- > 0) throw new Error('temporary network failure');
    return {ok: true, json: async () => ({})};
  },
};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), sandbox);
(async () => {
  await listeners.get('DOMContentLoaded')();
  const api = sandbox.window.pywebview.api;
  await assert.rejects(api.status());
  assert.equal(notices.at(-1).state, 'reconnecting');
  await api.status();
  assert.equal(notices.at(-1).state, 'connected');
  expired = true;
  await api.status();
  assert.equal(notices.at(-1).state, 'reset');
  await api.status();
  assert.equal(notices.at(-1).state, 'reset', 'background successes must preserve restart warning');
  await api.choose_folder();
  assert.ok(timers.includes(240000));
  assert.equal(notices.at(-1).state, 'connected', 'a deliberate new operation acknowledges reset');
})().catch(error => { console.error(error); process.exitCode = 1; });
