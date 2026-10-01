import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { workspaceAPIKeyApi } from '@/lib/workspace-api-keys';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('workspaceAPIKeyApi', () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'session-token' }));
    // The active workspace key is namespaced by the authenticated session.
    sessionStorage.setItem('northstar.active-workspace::demo', 'workspace-1');
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('lists, creates, and revokes keys through the active workspace backend', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse([{
        id: 'key-1',
        name: 'Production 1',
        prefix: 'nsk_live_example',
        createdAt: '2026-09-10T00:00:00Z',
        lastUsedAt: null,
        scopes: ['conversations:read'],
      }]))
      .mockResolvedValueOnce(jsonResponse({
        id: 'key-2',
        name: 'Production 2',
        prefix: 'nsk_live_created',
        secret: 'nsk_live_created-secret',
        createdAt: '2026-09-11T00:00:00Z',
        lastUsedAt: null,
      }, 201))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    const listed = await workspaceAPIKeyApi.list();
    expect(listed).toHaveLength(1);

    const created = await workspaceAPIKeyApi.create('  Production   2  ', ['conversations:read']);
    expect(created.secret).toBe('nsk_live_created-secret');

    await workspaceAPIKeyApi.revoke('key-2');

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/workspace/api-keys', expect.objectContaining({
      method: 'GET',
      headers: expect.objectContaining({
        Authorization: 'Bearer session-token',
        'X-Workspace-ID': 'workspace-1',
      }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/workspace/api-keys', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ name: 'Production 2', scopes: ['conversations:read'] }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/v1/workspace/api-keys/key-2', expect.objectContaining({
      method: 'DELETE',
    }));
    expect(localStorage.getItem('northstar.workspace.api-keys')).toBeNull();
  });

  it('does not silently fall back to demo keys for authorization failures', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Insufficient permission' } }, 403));

    await expect(workspaceAPIKeyApi.list()).rejects.toThrow('Insufficient permission');
    expect(localStorage.getItem('northstar.workspace.api-keys')).toBeNull();
  });
});
