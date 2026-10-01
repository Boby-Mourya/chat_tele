import { afterEach, describe, expect, it, vi } from 'vitest';
import { channelHealthHistoryApi } from '@/lib/channel-health-history-api';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('channel health history API client', () => {
  it('loads Workspace-scoped channel health history with the active auth context', async () => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    const snapshot = {
      id: 'snapshot-1',
      connection_id: 'channel-1',
      status: 'healthy',
      error_code: null,
      checked_at: '2026-09-12T18:30:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([snapshot]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await channelHealthHistoryApi.list('channel-1', 25);

    expect(result).toEqual([snapshot]);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/channels/connections/channel-1/health-history?limit=25',
      expect.objectContaining({
        credentials: 'include',
        headers: expect.objectContaining({
          Accept: 'application/json',
          Authorization: 'Bearer access-token',
          'X-Workspace-ID': 'workspace-1',
        }),
      }),
    );
  });
});
