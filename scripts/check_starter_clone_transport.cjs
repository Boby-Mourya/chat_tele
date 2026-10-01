// Targeted transport checks: actual compiled modules, explicit browser/network fixtures.
// This does NOT run React, real cookies, a backend, or the full Vite build.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const vm = require('node:vm');
const { test } = require('node:test');
const { webcrypto } = require('node:crypto');
const root = path.resolve(__dirname, '..');
const tsPath = fs.existsSync(path.join(root, 'frontend/node_modules/typescript'))
  ? path.join(root, 'frontend/node_modules/typescript')
  : path.join(cp.execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), 'typescript');
const ts = require(tsPath);
const W1 = '11111111-1111-4111-8111-111111111111';
const W2 = '22222222-2222-4222-8222-222222222222';
const AGENT = '33333333-3333-4333-8333-333333333333';
function storage() {
  const data = new Map();
  return { data, getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: (key) => data.delete(key) };
}
function fixture() {
  const localStorage = storage(); const sessionStorage = storage(); let calls = [];
  let handle = async () => { throw new TypeError('Network unavailable'); };
  const scope = vm.createContext({ console, localStorage, sessionStorage, crypto: webcrypto, Response,
    DOMException, URL, AbortController, Headers, atob, Event,
    CustomEvent: class extends Event { constructor(type, value) { super(type); this.detail = value?.detail; } },
    window: { dispatchEvent() {} },
    fetch: async (...args) => { calls.push(args); return handle(...args); },
  });
  const modules = new Map();
  function load(name) {
    if (modules.has(name)) return modules.get(name).exports;
    const file = path.join(root, 'frontend/src', name.replace('@/','')+'.ts');
    const source = fs.readFileSync(file, 'utf8').replaceAll('import.meta.env', '({})');
    const result = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } });
    const module = { exports: {} }; modules.set(name,module);
    vm.runInContext('(function(require,module,exports){'+result.outputText+'\n})',scope)(load,module,module.exports);
    return module.exports;
  }
  function signIn(user='user-1', tenant='tenant-1', revision=0) {
    const token='header.'+Buffer.from(JSON.stringify({ tid:tenant,cv:0,jti:String(revision) })).toString('base64url')+'.signature';
    localStorage.setItem('northstar.session',JSON.stringify({accessToken:token,user:{id:user,role:'owner',emailVerified:true}}));
  }
  signIn();
  const workspace=load('@/lib/workspace-api');workspace.persistActiveWorkspace(W1);
  const api=load('@/lib/starter-content-api').starterContentApi;
  const prepare=(name='Sample support',version=1)=>api.prepare('support-template',version,name);
  const pending=()=>api.pending('support-template');
  const good=(p,patch={})=>({requestId:p.idempotencyKey,catalogId:p.catalogId,catalogVersion:p.catalogVersion,agentId:AGENT,
    workspaceId:p.workspaceId,name:p.name,purpose:'support',initialStatus:'draft',sample:true,createdAt:'2026-09-19T00:00:00Z',replayed:false,...patch});
  const respond=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
  return {api,workspace,prepare,pending,good,respond,localStorage,sessionStorage,signIn,calls,setHandle:(fn)=>{handle=fn;}};
}
test('saves a bounded normalized copy request before a mutation',()=>{
 const f=fixture(),p=f.prepare(' Sample   support ');assert.equal(p.name,'Sample support');assert.equal(f.pending().idempotencyKey,p.idempotencyKey);assert.equal(f.calls.length,0);
});
test('reopening or editing retains the original request ID',()=>{
 const f=fixture(),p=f.prepare();assert.equal(f.prepare('Another name').idempotencyKey,p.idempotencyKey);
});
test('storage failure prevents submission',()=>{
 const f=fixture();f.sessionStorage.setItem=()=>{throw new Error('unavailable');};assert.throws(()=>f.prepare(),/No copy was submitted/);assert.equal(f.calls.length,0);
});
for(const name of ['', 'x', 'A'.repeat(121), 'ab\ncd','ab\u200bcd'])test('reject invalid name '+JSON.stringify(name),()=>assert.throws(()=>fixture().prepare(name),/valid name/));
test('sends only request ID, version and name to the current workspace',async()=>{
 const f=fixture(),p=f.prepare();f.setHandle(async()=>f.respond(f.good(p),201));const result=await f.api.submit(p);
 assert.equal(result.agentId,AGENT);const [url,init]=f.calls[0];assert.equal(url,'/api/v1/starter-content/support-template/clone');assert.equal(init.method,'POST');assert.equal(init.headers['X-Workspace-ID'],W1);
 assert.deepEqual(Object.keys(JSON.parse(init.body)).sort(),['catalogVersion','idempotencyKey','name']);assert.equal(f.calls.length,1);
});
test('network uncertainty retains the request and never automatically retries',async()=>{
 const f=fixture(),p=f.prepare();await assert.rejects(f.api.submit(p),e=>e.ambiguous===true);assert.equal(f.calls.length,1);assert.equal(f.pending().idempotencyKey,p.idempotencyKey);
});
for(const status of [401,403,409,410,422,429,500,503])test('truthfully propagates status '+status,async()=>{
 const f=fixture(),p=f.prepare();f.setHandle(async()=>f.respond({detail:'Server refused'},status));await assert.rejects(f.api.submit(p),e=>e.status===status&&e.ambiguous===(status>=500));assert.equal(f.calls.length,1);
});
for(const patch of [{workspaceId:W2},{requestId:'foreign'},{agentId:'../../login'},{purpose:'education'},{initialStatus:'active'},{sample:false},{createdAt:'bad'}, {catalogVersion:2}, {name:'unexpected'}, {replayed:'yes'}])test('reject mismatched or malformed result '+JSON.stringify(patch),async()=>{
 const f=fixture(),p=f.prepare();f.setHandle(async()=>f.respond(f.good(p,patch)));await assert.rejects(f.api.submit(p),e=>e.status===502&&e.ambiguous);
});
test('result lookup is read-only and can recover the original name after an edited retry',async()=>{
 const f=fixture(),p=f.prepare();f.prepare('Different name');const edited=f.pending();f.setHandle(async()=>f.respond(f.good(p,{replayed:true})));const r=await f.api.result(edited);
 assert.equal(r.name,p.name);assert.equal(f.calls[0][1].method,'GET');assert.equal(f.calls[0][1].body,undefined);
});
test('lookup not-found never starts a new copy',async()=>{
 const f=fixture(),p=f.prepare();f.setHandle(async()=>f.respond({detail:'Not found'},404));await assert.rejects(f.api.result(p),e=>e.status===404&&!e.ambiguous);assert.equal(f.calls.length,1);assert.equal(f.calls[0][1].method,'GET');
});
test('a late response cannot be applied to another workspace',async()=>{
 const f=fixture(),p=f.prepare();f.setHandle(async()=>{f.workspace.persistActiveWorkspace(W2);return f.respond(f.good(p));});await assert.rejects(f.api.submit(p),e=>e.name==='AbortError');assert.equal(f.calls.length,1);
});
test('a changed organization is rejected before sending',async()=>{
 const f=fixture(),p=f.prepare();f.signIn('user-1','tenant-2');f.workspace.persistActiveWorkspace(W1);await assert.rejects(f.api.submit(p),e=>e.name==='AbortError');assert.equal(f.calls.length,0);
});
test('same-identity token renewal does not replay a mutation',async()=>{
 const f=fixture(),p=f.prepare();f.setHandle(async()=>{f.signIn('user-1','tenant-1',1);return f.respond(f.good(p));});await assert.rejects(f.api.submit(p),e=>e.status===409&&e.ambiguous);assert.equal(f.calls.length,1);
});
test('abort before submit sends no request',async()=>{
 const f=fixture(),p=f.prepare(),c=new AbortController();c.abort();await assert.rejects(f.api.submit(p,c.signal),e=>e.name==='AbortError');assert.equal(f.calls.length,0);
});
test('a second copy requires an explicit new-copy action with the matching receipt',()=>{
 const f=fixture(),p=f.prepare();assert.throws(()=>f.api.startAnother('support-template','wrong'),/changed/);
 f.api.startAnother('support-template',p.idempotencyKey);assert.notEqual(f.prepare().idempotencyKey,p.idempotencyKey);
});
test('damaged recovery data is not silently replaced with a new request',()=>{
 const f=fixture();f.prepare();const key=[...f.sessionStorage.data.keys()].find(k=>k.startsWith('northstar.starter-copy:'));f.sessionStorage.setItem(key,'{broken');assert.throws(()=>f.prepare(),/damaged/);assert.equal(f.calls.length,0);
});
