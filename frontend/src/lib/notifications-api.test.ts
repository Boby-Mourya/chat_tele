import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { notificationsApi } from '@/lib/notifications-api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const item = {
  id: 'notification-1',
  workspaceId: 'workspace-1',
  category: 'lead',
  severity: 'info',
  title: 'New lead captured',
  body: 'A new lead is ready.',
  actionUrl: '/leads',
  actionLabel: 'View leads',
  metadata: {},
  readAt: null,
  createdAt: '2026-09-11T08:00:00Z',
};

describe('notificationsApi', () => {
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

  it('loads the workspace-scoped inbox with session credentials', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([item]));

    await expect(notificationsApi.list(20)).resolves.toEqual([item]);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/notifications?limit=20',
      expect.objectContaining({
        credentials: 'include',
        headers: expect.objectContaining({
          Authorization: 'Bearer session-token',
          'X-Workspace-ID': 'workspace-1',
        }),
      }),
    );
  });

  it('loads unread count and updates individual/all read state', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ count: 3 }))
      .mockResolvedValueOnce(jsonResponse({ ...item, readAt: '2026-09-11T08:10:00Z' }))
      .mockResolvedValueOnce(jsonResponse({ updated: 2 }));

    await expect(notificationsApi.unreadCount()).resolves.toBe(3);
    await expect(notificationsApi.markRead(item.id)).resolves.toEqual(expect.objectContaining({ readAt: '2026-09-11T08:10:00Z' }));
    await expect(notificationsApi.markAllRead()).resolves.toBe(2);

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/notifications/notification-1/read',
      expect.objectContaining({ method: 'PATCH' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/v1/notifications/read-all',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('surfaces authorization failures rather than faking an empty inbox', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Workspace access is unavailable' } }, 403));
    await expect(notificationsApi.list()).rejects.toThrow('Workspace access is unavailable');
  });
});
