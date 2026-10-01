// Isolated module execution: mocked storage/fetch; not Vite, React or live billing.
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const vm = require('node:vm');
const ts = require(require.resolve('typescript', { paths: [resolve(__dirname, '../frontend'), resolve(__dirname, '..')] }));
const { test } = require('node:test');
const assert = require('node:assert/strict');
const source = readFileSync(resolve(__dirname, '../frontend/src/lib/billing-api.ts'), 'utf8');
const compiled = ts.transpileModule(source.replaceAll('import.meta.env', '__env'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, strict: true },
  reportDiagnostics: true,
});
assert.equal((compiled.diagnostics ?? []).filter(x=>x.category===ts.DiagnosticCategory.Error).length,0);
function host() {
  let token = 'account-one'; const calls=[]; const queue=[];
  const exports={}; const context = {
    exports, __env: {}, URL,
    require(name) { assert.equal(name, '@/lib/storage'); return { readStorage: () => token ? { accessToken: token } : null }; },
    fetch: async (path,init) => { calls.push([path,init]); assert.ok(queue.length,'Unexpected duplicate request'); return queue.shift()(path,init); },
  };
  vm.runInNewContext(compiled.outputText,context,{filename:'actual-billing-module.js'});
  return { api: exports.billingApi, calls, queue, setToken(value){token=value;} };
}
const response=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
const data={id:'server-subscription',tenantId:'organization-one',plan:'free',status:'active'};
test('uses server subscription; no operational workspace header or cache',async()=>{
 const h=host(); h.queue.push(()=>response(data)); assert.deepEqual(await h.api.getSubscription('enterprise'),data);
 const [path,init]=h.calls[0]; assert.equal(path,'/api/v1/billing/subscription'); assert.equal(init.headers.Authorization,'Bearer account-one');
 assert.equal(init.headers['X-Workspace-ID'],undefined); assert.equal(init.cache,'no-store'); assert.equal(init.credentials,'include');
});
test('fetches authoritative entitlements',async()=>{
 const h=host();const ent={plan:'free',limits:{agents:1},features:{crm:false}}; h.queue.push(()=>response(ent));
 assert.deepEqual(await h.api.getEntitlements('enterprise'),ent); assert.equal(h.calls[0][0],'/api/v1/billing/entitlements');
});
for(const status of [401,403,409,429,500,502,503]) test(`HTTP ${status} is not replaced with demo data`,async()=>{
 const h=host(); h.queue.push(()=>response({error:{message:'Unavailable'}},status),()=>response({detail:'Unavailable'},status));
 await assert.rejects(h.api.getSubscription('business'),e=>e.status===status&&e.message==='Unavailable');
 await assert.rejects(h.api.getEntitlements('legacy'),e=>e.status===status&&e.message==='Unavailable');
 assert.equal(h.calls.length,2);
});
for (const plan of ['free','business','legacy']) test(`${plan}: network failure never synthesizes active or unlimited plan`,async()=>{
 const h=host();h.queue.push(()=>{throw new TypeError('Offline')},()=>{throw new TypeError('Offline')});
 await assert.rejects(h.api.getSubscription(plan),/Offline/); await assert.rejects(h.api.getEntitlements(plan),/Offline/);
});
test('preserves authenticated checkout, portal, cancellation and reactivation contracts',async()=>{
 const h=host();h.queue.push(()=>response({url:'https://checkout.stripe.com/pay'}),()=>response({url:'https://billing.stripe.com/session'}),()=>response({...data,status:'cancelled'}),()=>response(data));
 await h.api.createCheckout('professional'); await h.api.createPortal(); await h.api.cancelSubscription(); await h.api.reactivateSubscription();
 assert.deepEqual(h.calls.map(c=>c[0]),['/api/v1/billing/checkout','/api/v1/billing/portal','/api/v1/billing/cancel','/api/v1/billing/reactivate']);
 assert.ok(h.calls.every(c=>c[1].method==='POST'));assert.equal(h.calls[0][1].body,'{"plan":"professional"}');assert.equal(h.calls[2][1].body,'{"confirmation":"CANCEL"}');
});
test('billing mutation failures do not retry automatically',async()=>{
 const h=host();h.queue.push(()=>{throw new Error('Offline')}); await assert.rejects(h.api.cancelSubscription(),/Offline/);assert.equal(h.calls.length,1);
});
test('no credential means no network call',async()=>{
 const h=host();h.setToken(null); await assert.rejects(h.api.getSubscription(),e=>e.status===401);assert.equal(h.calls.length,0);
});
test('account change fences a completed mutation response without replay',async()=>{
 const h=host();h.queue.push(()=>{h.setToken('other');return response(data)}); await assert.rejects(h.api.cancelSubscription(),e=>e.status===409&&e.message.includes('may already have completed'));assert.equal(h.calls.length,1);
});
test('account context is checked after delayed body parsing',async()=>{
 const h=host();h.queue.push(()=>({ok:true,status:200,json:async()=>{h.setToken(null);return data;}}));await assert.rejects(h.api.getSubscription(),e=>e.status===409);
});
for (const body of ['<html>proxy</html>','null','[]','"active"']) test(`invalid success body rejected: ${body}`,async()=>{
 const h=host();h.queue.push(()=>new Response(body,{status:200}));await assert.rejects(h.api.getSubscription(),e=>e.status===502);
});
for(const url of ['javascript:alert(1)','http://billing.example.test','//billing.example.test','https://user:pass@billing.example.test','not-a-url'])test(`unsafe redirect rejected: ${url}`,async()=>{
 const h=host();h.queue.push(()=>response({url}));await assert.rejects(h.api.createPortal(),e=>e.status===502);
});
