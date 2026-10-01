// Actual workspace transport in a Node VM with explicit browser/storage/fetch fixtures.
// Does not stand in for React rendering, real refresh cookies or backend authorization.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const cp = require('node:child_process');
const root = path.resolve(__dirname, '..');
let compiler;
try { compiler = require.resolve('typescript', { paths: [root, path.join(root, 'frontend')] }); }
catch { compiler = path.join(cp.execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), 'typescript'); }
const ts = require(compiler);

function host() {
  const storage = () => {
    const values = new Map();
    return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), removeItem: (key) => values.delete(key), clear: () => values.clear() };
  };
  const localStorage = storage(), sessionStorage = storage(), window = new EventTarget();
  const calls = [], queue = [], emitted = [];
  window.addEventListener('northstar:workspace-changed', (event) => emitted.push(event.detail));
  const context = vm.createContext({ localStorage, sessionStorage, window, Event, CustomEvent, AbortController, DOMException, TypeError, Error,
    structuredClone, atob: (value) => Buffer.from(value, 'base64').toString('binary'),
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (!queue.length) throw new Error('Missing response fixture');
      const item = queue.shift();
      if (item instanceof Error) throw item;
      return typeof item === 'function' ? item() : item;
    } });
  const modules = new Map();
  function load(relative) {
    if (modules.has(relative)) return modules.get(relative);
    const filename = path.join(root, 'frontend/src', relative);
    const input = fs.readFileSync(filename, 'utf8').replaceAll('import.meta.env', '({VITE_API_URL:"/api/v1",VITE_DEMO_MODE:"false"})');
    const js = ts.transpileModule(input, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    const module = { exports: {} }; modules.set(relative, module.exports);
    vm.runInContext(`(function(require,module,exports){${js}\n})`, context, { filename })(
      (id) => { assert.ok(id.startsWith('@/')); return load(id.slice(2) + '.ts'); }, module, module.exports);
    return module.exports;
  }
  function session({ tenant = 'tenant-1', user = 'user-1', role = 'owner', cv = 0, verified = true, serial = 1 } = {}) {
    const token = 'test.' + Buffer.from(JSON.stringify({ tid: tenant, sub: user, role, cv, jti: serial })).toString('base64url') + '.signature';
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: token, user: { id: user, role, emailVerified: verified } }));
    return token;
  }
  session();
  const ws = load('lib/workspace-api.ts'); ws.persistActiveWorkspace('workspace-1');
  return { ws, session, localStorage, sessionStorage, calls, queue, emitted };
}
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

test('ordinary access-token rotation preserves the UI context key', () => {
  const h = host(), before = h.ws.workspacePresentationKey();
  h.session({ serial: 2 });
  assert.equal(h.ws.workspacePresentationKey(), before);
  assert.equal(h.ws.activeWorkspaceId(), 'workspace-1');
});
for (const [name, change] of Object.entries({ organization: { tenant: 'tenant-2' }, identity: { user: 'user-2' }, role: { role: 'member' }, credential: { cv: 1 }, verification: { verified: false } })) {
  test(`${name} change invalidates the UI context`, () => {
    const h = host(), before = h.ws.workspacePresentationKey();
    h.session(change); assert.notEqual(h.ws.workspacePresentationKey(), before);
  });
}
test('sign-out invalidates the UI context', () => {
  const h = host(); h.localStorage.clear();
  assert.equal(h.ws.workspacePresentationKey(), 'signed-out');
});
test('context keys do not contain bearer tokens', () => {
  const h = host(), token = h.session();
  assert.ok(!h.ws.workspacePresentationKey().includes(token));
});
test('malformed token parsing does not throw or grant access', async () => {
  const h = host(); h.localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'invalid', user: { id: 'user-1' } }));
  assert.doesNotThrow(() => h.ws.workspacePresentationKey());
  h.queue.push(json({ detail: 'Invalid token' }, 401));
  await assert.rejects(h.ws.workspaceApi.list(), /Invalid token/);
});
test('GET retries once after an external same-identity token refresh', async () => {
  const h = host(); let next;
  h.queue.push(() => { next = h.session({ serial: 2 }); return json({ old: true }); }, json({ id: 'workspace-1', fresh: true }));
  const result = await h.ws.workspaceApi.get();
  assert.equal(result.fresh, true); assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].init.headers.Authorization, `Bearer ${next}`);
  assert.equal(h.calls[0].init.headers['X-Workspace-ID'], h.calls[1].init.headers['X-Workspace-ID']);
});
test('a second refresh during GET is not an infinite retry', async () => {
  const h = host();
  h.queue.push(() => { h.session({ serial: 2 }); return json({}); }, () => { h.session({ serial: 3 }); return json({}); });
  await assert.rejects(h.ws.workspaceApi.get(), (error) => error.name === 'AbortError');
  assert.equal(h.calls.length, 2);
});
test('GET never retries into another workspace', async () => {
  const h = host(); h.queue.push(() => { h.session({ serial: 2 }); h.ws.persistActiveWorkspace('workspace-2'); return json({}); });
  await assert.rejects(h.ws.workspaceApi.get(), (error) => error.name === 'AbortError');
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].init.headers['X-Workspace-ID'], 'workspace-1');
});
for (const [name, change] of Object.entries({ organization: { tenant: 'other' }, role: { role: 'member' }, credentials: { cv: 4 }, verification: { verified: false } })) {
  test(`GET never retries after ${name} context changes`, async () => {
    const h = host(); h.queue.push(() => { h.session(change); return json({}); });
    await assert.rejects(h.ws.workspaceApi.get(), (error) => error.name === 'AbortError');
    assert.equal(h.calls.length, 1);
  });
}
test('workspace creation is never automatically replayed', async () => {
  const h = host(); h.queue.push(() => { h.session({ serial: 2 }); return json({ id: 'created' }); });
  await assert.rejects(h.ws.workspaceApi.create({ name: 'Workspace', slug: 'workspace' }), (error) => error.name === 'AbortError');
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].init.method, 'POST');
  assert.equal(h.ws.activeWorkspaceId(), 'workspace-1');
});
test('workspace settings mutation is never replayed or falsely broadcast', async () => {
  const h = host(); h.queue.push(() => { h.session({ serial: 2 }); return json({ id: 'workspace-1' }); });
  await assert.rejects(h.ws.workspaceApi.update({ name: 'Changed' }), (error) => error.name === 'AbortError');
  assert.equal(h.calls.length, 1); assert.equal(h.emitted.length, 0);
});
test('invitation POST is not replayed after a token change', async () => {
  const h = host(); h.queue.push(() => { h.session({ serial: 2 }); return json({}); });
  await assert.rejects(h.ws.workspaceApi.inviteMember('staff@example.com', 'viewer'), (error) => error.name === 'AbortError');
  assert.equal(h.calls.length, 1);
});
test('cancelled workspace list stops before issuing a request', async () => {
  const h = host(), controller = new AbortController(); controller.abort();
  await assert.rejects(h.ws.workspaceApi.list(controller.signal), (error) => error.name === 'AbortError');
  assert.equal(h.calls.length, 0);
});
test('late response is discarded when a cancelled fetch fixture still resolves', async () => {
  const h = host(), controller = new AbortController();
  h.queue.push(() => { controller.abort(); return json([]); });
  await assert.rejects(h.ws.workspaceApi.list(controller.signal), (error) => error.name === 'AbortError');
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].init.signal, controller.signal);
});
test('workspace list does not inherit an operational workspace header', async () => {
  const h = host(); h.queue.push(json([])); await h.ws.workspaceApi.list();
  assert.equal('X-Workspace-ID' in h.calls[0].init.headers, false);
  assert.equal(h.calls[0].init.credentials, 'include'); assert.equal(h.calls[0].init.cache, 'no-store');
});
for (const status of [400, 401, 403, 409, 428, 429]) {
  test(`HTTP ${status} is not considered a transient metadata outage`, () => {
    const h = host(); assert.equal(h.ws.retryableWorkspaceRead(new h.ws.WorkspaceRequestError('Denied', status)), false);
  });
}
test('network and service outages are recoverable reads, not fabricated success', async () => {
  const h = host();
  assert.equal(h.ws.retryableWorkspaceRead(new TypeError('Offline')), true);
  assert.equal(h.ws.retryableWorkspaceRead(new h.ws.WorkspaceRequestError('Unavailable', 503)), true);
  h.queue.push(new TypeError('Offline'));
  await assert.rejects(h.ws.workspaceApi.list(), /Offline/); assert.equal(h.calls.length, 1);
});
test('cancellation is never treated as a recoverable service failure', () => {
  const h = host(); assert.equal(h.ws.retryableWorkspaceRead(new DOMException('Aborted', 'AbortError')), false);
});
test('unchanged unauthorized tokens are not refreshed or retried by this transport', async () => {
  const h = host(); h.queue.push(json({ detail: 'Expired' }, 401));
  await assert.rejects(h.ws.workspaceApi.get(), /Expired/); assert.equal(h.calls.length, 1);
});
