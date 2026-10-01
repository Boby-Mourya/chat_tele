import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { auditApi } from '@/lib/audit-api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const event = {
  id: 'audit-1',
  tenantId: 'tenant-1',
  workspaceId: 'workspace-1',
  actorUserId: 'user-1',
  action: 'workspace.patch',
  entityType: 'workspace',
  entityId: '/workspace',
  category: 'workspace',
  severity: 'info',
  outcome: 'success',
  before: {},
  after: {},
  metadata: { method: 'PATCH', statusCode: 200 },
  requestId: 'request-1',
  ipAddress: '127.0.0.1',
  userAgent: 'Vitest',
  createdAt: '2026-09-11T00:00:00Z',
};

describe('auditApi', () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    localStorage.setItem('northstar.session', JSON.stringify({
      accessToken: 'session-token',
      user: { id: 'u', name: 'User', email: 'user@example.com', role: 'owner' },
      expiresAt: '2099-01-01T00:00:00Z',
    }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('loads filtered audit events with authenticated workspace scope', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([event]));

    const result = await auditApi.list({
      category: 'workspace',
      severity: 'info',
      outcome: 'success',
      search: 'workspace',
      limit: 50,
    });

    expect(result).toEqual([event]);
    const [url, options] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain('/api/v1/audit/events?');
    expect(String(url)).toContain('category=workspace');
    expect(String(url)).toContain('severity=info');
    expect(String(url)).toContain('outcome=success');
    expect(String(url)).toContain('search=workspace');
    expect(options).toEqual(expect.objectContaining({
      credentials: 'include',
      headers: expect.objectContaining({
        Authorization: 'Bearer session-token',
        'X-Workspace-ID': 'workspace-1',
      }),
    }));
  });

  it('exports CSV through the same authorization boundary', async () => {
    fetchMock.mockResolvedValueOnce(new Response('created_at,action\r\n', {
      status: 200,
      headers: { 'Content-Type': 'text/csv' },
    }));

    const blob = await auditApi.exportCsv({ category: 'security' });

    expect(await blob.text()).toContain('created_at,action');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/audit/export?category=security'),
      expect.objectContaining({
        credentials: 'include',
        headers: expect.objectContaining({
          Accept: 'text/csv',
          Authorization: 'Bearer session-token',
          'X-Workspace-ID': 'workspace-1',
        }),
      }),
    );
  });

  it('surfaces HTTP failures and never invents security events', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Insufficient permission' } }, 403));
    await expect(auditApi.list()).rejects.toThrow('Insufficient permission');

    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Audit storage unavailable' } }, 503));
    await expect(auditApi.list()).rejects.toThrow('Audit storage unavailable');

    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    await expect(auditApi.list()).resolves.toEqual([]);
  });
});
