// Actual transport modules in a Node VM; storage/network/browser primitives are
// explicit fixtures. This is not React, real-cookie or full-application testing.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const cp = require('node:child_process');
const root = path.resolve(__dirname, '..');
const local = path.join(root, 'frontend/node_modules/typescript');
const ts = require(fs.existsSync(local) ? local : path.join(cp.execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), 'typescript'));
const support = process.env.MEMBERSHIP_CHECK_SUPPORT_ROOT || root;
function storage() {
  const data = new Map();
  return { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: (key) => data.delete(key), clear: () => data.clear() };
}
function response(value, status = 200) { return new Response(JSON.stringify(value), {status, headers:{'Content-Type':'application/json'}}); }
function fixture() {
  const localStorage = storage(); const sessionStorage = storage(); const calls = [];
  const context = vm.createContext({console, Response, Headers, DOMException, AbortController, URL, URLSearchParams,
    localStorage, sessionStorage, atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    CustomEvent: class {constructor(type, init) { this.type=type; this.detail=init?.detail; }},
    Event: class {constructor(type) {this.type=type;}},
    window: {dispatchEvent: () => true},
    fetch: (...args) => {calls.push(args); return context.reply(...args);},
    reply: async () => response([])});
  const cache = new Map([['@/lib/api', { AUTH_SESSION_EVENT: 'northstar:session-changed' }]]);
  function load(id) {
    if (cache.has(id)) return cache.get(id);
    const relative = 'frontend/src/' + id.slice(2) + '.ts';
    const file = path.join(id === '@/lib/workspace-team-api' ? root : support, relative);
    const source = fs.readFileSync(file,'utf8').replace(/import\.meta\.env/g, '({VITE_DEMO_MODE:"false"})');
    const compiled = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2022}}).outputText;
    const exports = {}; const module={exports}; cache.set(id,exports);
    vm.runInContext(`(function(require,module,exports){${compiled}\n})`,context,{filename:file})(load,module,exports);
    cache.set(id,module.exports); return module.exports;
  }
  const api = load('@/lib/workspace-team-api'); const workspace=load('@/lib/workspace-api');
  function identity({user='u1',tenant='t1',role='owner',cv=0,jti='a',verified=true}={}) {
    const token = 'header.' + Buffer.from(JSON.stringify({tid:tenant,cv,jti})).toString('base64url') + '.signature';
    localStorage.setItem('northstar.session',JSON.stringify({accessToken:token, user:{id:user,role,emailVerified:verified}})); return token;
  }
  identity(); workspace.persistActiveWorkspace('w1');
  return { ...api, workspace, context, calls, identity, localStorage };
}
const access = { role:'operator',allAgentsAccess:false,agentIds:[] };
const invite = {id:'i1',email:'invitee@example.com',status:'pending',deliveryState:'sent'};
const methods = [
  ['invite', h => h.workspaceTeamApi.invite({...access,email:invite.email})],
  ['update', h => h.workspaceTeamApi.updateMember('u2',access)],
  ['remove', h => h.workspaceTeamApi.removeMember('u2')],
  ['resend', h => h.workspaceTeamApi.resendInvitation('i1')],
  ['revoke', h => h.workspaceTeamApi.revokeInvitation('i1')],
];
test('member read uses authenticated workspace and no-store', async()=>{
  const h=fixture();await h.workspaceTeamApi.listMembers();assert.equal(h.calls.length,1);
  assert.equal(h.calls[0][0],'/api/v1/workspace/members');assert.equal(h.calls[0][1].headers['X-Workspace-ID'],'w1');
  assert.ok(h.calls[0][1].headers.Authorization);assert.equal(h.calls[0][1].cache,'no-store');
});
test('edit and delete preserve the existing endpoint contracts',async()=>{
  const h=fixture();h.context.reply=async()=>response({});
  await h.workspaceTeamApi.updateMember('u/2',access);assert.equal(h.calls[0][0],'/api/v1/workspace/members/u%2F2');
  assert.deepEqual(JSON.parse(h.calls[0][1].body),access);
  h.context.reply=async()=>new Response(null,{status:204});await h.workspaceTeamApi.removeMember('u/2');
  assert.equal(h.calls[1][0],'/api/v1/workspace/members/u%2F2');
});
for(const [name,invoke] of methods) {
  test(`${name}: network failure never replays mutation`,async()=>{
    const h=fixture();h.context.reply=async()=>{throw new TypeError('network unavailable');};
    await assert.rejects(invoke(h),/network unavailable/);assert.equal(h.calls.length,1);
  });
  test(`${name}: token rotation after submission reports uncertain outcome`,async()=>{
    const h=fixture();h.context.reply=async()=>{h.identity({jti:'new'});return response({});};
    await assert.rejects(invoke(h),{name:'AbortError'});assert.equal(h.calls.length,1);
  });
}
for(const change of [{user:'u2'},{tenant:'t2'},{role:'member'},{cv:1},{verified:false}]) {
  test(`read rejects changed identity ${JSON.stringify(change)}`,async()=>{
    const h=fixture();h.context.reply=async()=>{h.identity(change);return response([]);};
    await assert.rejects(h.workspaceTeamApi.listMembers(),{name:'AbortError'});
  });
}
test('same-identity renewal does not turn GET into mutation or discard data',async()=>{
  const h=fixture();h.context.reply=async()=>{h.identity({jti:'new'});return response([{userId:'u2'}]);};
  assert.equal((await h.workspaceTeamApi.listMembers())[0].userId,'u2');assert.equal(h.calls.length,1);
});
test('workspace change during JSON decoding discards old member data',async()=>{
  const h=fixture();h.context.reply=async()=>({ok:true,status:200,json:async()=>{h.workspace.persistActiveWorkspace('w2');return [];}});
  await assert.rejects(h.workspaceTeamApi.listMembers(),{name:'AbortError'});
});
test('cancelled read is stopped before fetch',async()=>{
  const h=fixture();const controller=new AbortController();controller.abort();
  await assert.rejects(h.workspaceTeamApi.listMembers(controller.signal),{name:'AbortError'});assert.equal(h.calls.length,0);
});
test('caller cancellation is passed into fetch',async()=>{
  const h=fixture();const controller=new AbortController();await h.workspaceTeamApi.listInvitations(controller.signal);
  assert.equal(h.calls[0][1].signal,controller.signal);
});
for(const status of [401,403,409,422,500,503]) test(`HTTP ${status} is not fabricated success`,async()=>{
  const h=fixture();h.context.reply=async()=>response({detail:'denied'},status);
  await assert.rejects(h.workspaceTeamApi.invite({...access,email:invite.email}), error=>error.status===status && error.message==='denied');
  assert.equal(h.calls.length,1);
});
test('empty successful GET is rejected as invalid service response',async()=>{
  const h=fixture();h.context.reply=async()=>new Response(null,{status:204});
  await assert.rejects(h.workspaceTeamApi.listMembers(), error=>error.status===502);
});
for(const [state,tone] of [['sent','success'],['failed','error'],['not-sent','info']]) test(`delivery ${state} is presented truthfully`,()=>{
  const h=fixture();const value=h.invitationDeliveryNotice({...invite,deliveryState:state});assert.equal(value.tone,tone);
  if(state!=='sent') assert.match(value.message,/saved/);
});
for(const state of ['accepted','declined','revoked','expired']) test(`terminal ${state} is not reported as sent`,()=>{
  const h=fixture();const value=h.invitationDeliveryNotice({...invite,status:state});assert.equal(value.tone,'info');assert.match(value.message,new RegExp(state));
});
test('public invitation preview does not send account/workspace headers',async()=>{
  const h=fixture();h.context.reply=async()=>response({});await h.workspaceInvitationApi.preview('opaque-invitation-proof');
  assert.equal(h.calls[0][1].headers.Authorization,undefined);assert.equal(h.calls[0][1].headers['X-Workspace-ID'],undefined);
});
test('invitation-session activation does not retain refresh credentials',()=>{
  const h=fixture();h.activateWorkspaceInvitationSession({accessToken:'next',refreshToken:'must-not-be-stored',expiresAt:'later',user:{id:'u1'},workspaceId:'w-new'});
  assert.equal(JSON.parse(h.localStorage.getItem('northstar.session')).refreshToken,undefined);
  assert.equal(h.workspace.activeWorkspaceId(),'w-new');
});
