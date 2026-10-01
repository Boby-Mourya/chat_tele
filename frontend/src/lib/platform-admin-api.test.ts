import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { platformAdminApi } from '@/lib/platform-admin-api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('platformAdminApi', () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'session-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('checks access without exposing authorization failures to normal navigation', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Platform administrator access required' } }, 403));
    await expect(platformAdminApi.canAccess()).resolves.toBe(false);

    fetchMock.mockResolvedValueOnce(jsonResponse({ authorized: true, email: 'admin@example.com' }));
    await expect(platformAdminApi.canAccess()).resolves.toBe(true);
  });

  it('loads authenticated workspace-aware overview and tenant search', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      tenants: 2,
      workspaces: 3,
      users: 4,
      agents: 5,
      conversations: 6,
      leads: 7,
      subscriptions: { trial: 0, active: 2, pastDue: 0, suspended: 0, cancelled: 0 },
      operations: {
        status: 'healthy', failedIngestionJobs: 0, unpublishedOutboxEvents: 0,
        oldestUnpublishedEventAt: null, quarantinedEvents: 0, channelIssues: 0,
        crmConnectionIssues: 0, crmDeliveryIssues: 0, openCrmDeadLetters: 0,
        criticalAuditEvents24h: 0,
      },
    }));
    const overview = await platformAdminApi.overview();
    expect(overview.tenants).toBe(2);
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/platform-admin/overview', expect.objectContaining({
      credentials: 'include',
      headers: expect.objectContaining({
        Authorization: 'Bearer session-token',
      }),
    }));
    expect(fetchMock.mock.calls[0]?.[1]?.headers).not.toHaveProperty('X-Workspace-ID');

    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }));
    await platformAdminApi.tenants('North Star');
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/platform-admin/tenants?limit=50&offset=0&search=North+Star',
      expect.any(Object),
    );
  });

  it('surfaces server and network failures for control-plane data', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Access denied' } }, 403));
    await expect(platformAdminApi.overview()).rejects.toThrow('Access denied');

    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    await expect(platformAdminApi.tenants()).rejects.toThrow('Network unavailable');
  });

  it('loads server-owned platform capabilities without workspace scoping', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      email: 'support@example.com',
      permissions: ['platform.tenants.read', 'platform.support.impersonate'],
    }));
    await expect(platformAdminApi.permissions()).resolves.toEqual({
      email: 'support@example.com',
      permissions: ['platform.tenants.read', 'platform.support.impersonate'],
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/platform-admin/permissions',
      expect.objectContaining({ credentials: 'include' }),
    );
  });
});
