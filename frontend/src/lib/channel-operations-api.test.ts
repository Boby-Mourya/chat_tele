import { afterEach, describe, expect, it, vi } from 'vitest';
import { channelOperationsApi } from '@/lib/channel-operations-api';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('channel operations health API client', () => {
  it('loads the active Workspace channel operations summary with auth context', async () => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    const health = {
      overall_status: 'attention',
      connection_count: 1,
      healthy_connections: 0,
      attention_connections: 1,
      pending_deliveries: 2,
      retrying_deliveries: 1,
      failed_deliveries: 1,
      pending_webhook_events: 3,
      failed_webhook_events: 1,
      rejected_webhook_events: 2,
      stale_webhook_events: 1,
      connections: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(health), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await channelOperationsApi.health();

    expect(result).toEqual(health);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/channels/operations/health',
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
