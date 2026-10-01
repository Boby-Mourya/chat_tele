import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { persistActiveWorkspace, workspaceApi, workspacePresentationKey, WorkspaceRequestError, retryableWorkspaceRead } from '@/lib/workspace-api';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
function session(serial = 1, cv = 0, role = 'owner') {
  const accessToken = `test.${btoa(JSON.stringify({ tid: 'tenant-1', cv, jti: serial }))}.fixture`;
  localStorage.setItem('northstar.session', JSON.stringify({ accessToken, user: { id: 'user-1', role, emailVerified: true } }));
  return accessToken;
}
const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => { session(); persistActiveWorkspace('workspace-1'); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => { vi.unstubAllGlobals(); vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear(); });

describe('workspace read refresh and write fences', () => {
  it('keeps token rotation out of the presentation identity', () => {
    const key = workspacePresentationKey(); session(2); expect(workspacePresentationKey()).toBe(key);
    session(3, 1); expect(workspacePresentationKey()).not.toBe(key);
  });
  it('keeps role changes in the presentation identity', () => {
    const key = workspacePresentationKey(); session(2, 0, 'member'); expect(workspacePresentationKey()).not.toBe(key);
  });
  it('retries a read once after another request refreshes the same identity', async () => {
    fetchMock.mockImplementationOnce(async () => { session(2); return json({ id: 'old' }); });
    fetchMock.mockResolvedValueOnce(json({ id: 'fresh' }));
    await expect(workspaceApi.get()).resolves.toEqual({ id: 'fresh' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [, init] of fetchMock.mock.calls) expect(init?.headers).toEqual(expect.objectContaining({ 'X-Workspace-ID': 'workspace-1' }));
  });
  it('does not replay a potentially completed mutation', async () => {
    fetchMock.mockImplementationOnce(async () => { session(2); return json({ id: 'created' }); });
    await expect(workspaceApi.create({ name: 'New workspace', slug: 'new-workspace' })).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it('cancels reads without calling the network', async () => {
    const controller = new AbortController(); controller.abort();
    await expect(workspaceApi.list(controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it('does not treat authorization failures as transient outages', () => {
    expect(retryableWorkspaceRead(new WorkspaceRequestError('Denied', 403))).toBe(false);
    expect(retryableWorkspaceRead(new WorkspaceRequestError('Unavailable', 503))).toBe(true);
  });
});
