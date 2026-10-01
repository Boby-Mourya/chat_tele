import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { starterContentApi, type PendingStarterClone } from '@/lib/starter-content-api';
import { persistActiveWorkspace } from '@/lib/workspace-api';

const workspace = '11111111-1111-4111-8111-111111111111';
const agent = '22222222-2222-4222-8222-222222222222';
const fetchMock = vi.fn<typeof fetch>();
function response(request: PendingStarterClone, patch: Record<string, unknown> = {}) {
  return new Response(JSON.stringify({ requestId: request.idempotencyKey, catalogId: request.catalogId,
    catalogVersion: request.catalogVersion, agentId: agent, workspaceId: workspace, name: request.name,
    purpose: 'support', initialStatus: 'draft', sample: true, createdAt: '2026-09-19T00:00:00Z', replayed: false, ...patch }),
  { status: 200, headers: { 'Content-Type': 'application/json' } });
}
describe('starter template clone transport', () => {
  beforeEach(() => {
    localStorage.clear(); sessionStorage.clear(); fetchMock.mockReset();
    const claims = btoa(JSON.stringify({ tid: 'organization-1', cv: 0 }));
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: `header.${claims}.signature`,
      user: { id: 'user-1', role: 'owner', emailVerified: true } }));
    persistActiveWorkspace(workspace); vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); });
  it('retains the same saved request after a name edit', () => {
    const original = starterContentApi.prepare('support-template', 1, 'Sample support');
    expect(starterContentApi.prepare('support-template', 1, 'Different name').idempotencyKey).toBe(original.idempotencyKey);
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it('creates through the real scoped endpoint with only the permitted input', async () => {
    const request = starterContentApi.prepare('support-template', 1, 'Sample support');
    fetchMock.mockResolvedValueOnce(response(request));
    await expect(starterContentApi.submit(request)).resolves.toMatchObject({ agentId: agent });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/starter-content/support-template/clone', expect.objectContaining({
      method: 'POST', credentials: 'include', headers: expect.objectContaining({ 'X-Workspace-ID': workspace }),
      body: JSON.stringify({ idempotencyKey: request.idempotencyKey, catalogVersion: 1, name: 'Sample support' }),
    }));
  });
  it('does not retry an ambiguous request or lose its recovery ID', async () => {
    const request = starterContentApi.prepare('support-template', 1, 'Sample support');
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    await expect(starterContentApi.submit(request)).rejects.toMatchObject({ ambiguous: true });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(starterContentApi.pending('support-template')?.idempotencyKey).toBe(request.idempotencyKey);
  });
  it('checks a saved result with GET instead of creating again', async () => {
    const request = starterContentApi.prepare('support-template', 1, 'Sample support');
    fetchMock.mockResolvedValueOnce(response(request, { replayed: true }));
    await expect(starterContentApi.result(request)).resolves.toMatchObject({ replayed: true });
    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/starter-content/clone-requests/${request.idempotencyKey}`,
      expect.objectContaining({ method: 'GET', body: undefined }));
  });
  it('rejects a foreign-workspace receipt', async () => {
    const request = starterContentApi.prepare('support-template', 1, 'Sample support');
    fetchMock.mockResolvedValueOnce(response(request, { workspaceId: agent }));
    await expect(starterContentApi.submit(request)).rejects.toMatchObject({ status: 502 });
  });
  it('discards a response after the selected workspace changes', async () => {
    const request = starterContentApi.prepare('support-template', 1, 'Sample support');
    fetchMock.mockImplementationOnce(async () => { persistActiveWorkspace(agent); return response(request); });
    await expect(starterContentApi.submit(request)).rejects.toMatchObject({ name: 'AbortError' });
  });
  it('requires an explicit completed-request reset for another copy', () => {
    const request = starterContentApi.prepare('support-template', 1, 'Sample support');
    expect(() => starterContentApi.startAnother('support-template', 'wrong')).toThrow();
    starterContentApi.startAnother('support-template', request.idempotencyKey);
    expect(starterContentApi.prepare('support-template', 1, 'Second copy').idempotencyKey).not.toBe(request.idempotencyKey);
  });
});
