import { afterEach, describe, expect, it, vi } from 'vitest';
import { channelDeliveriesApi } from '@/lib/channel-deliveries-api';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('channel delivery visibility API client', () => {
  it('loads filtered Workspace-scoped delivery evidence with auth context', async () => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    const delivery = {
      id: 'delivery-1',
      connection_id: 'channel-1',
      connection_name: 'Primary Telegram',
      message_id: 'message-1',
      provider: 'telegram',
      status: 'failed',
      error_code: 'retryable_failure',
      attempt_count: 2,
      dispatch_attempts: 3,
      dispatched_at: '2026-09-12T18:30:00Z',
      processed_at: null,
      next_dispatch_at: '2026-09-12T18:35:00Z',
      created_at: '2026-09-12T18:29:00Z',
      updated_at: '2026-09-12T18:31:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([delivery]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await channelDeliveriesApi.list({
      connectionId: 'channel-1',
      status: 'failed',
      limit: 25,
    });

    expect(result).toEqual([delivery]);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/channels/deliveries?connection_id=channel-1&status=failed&limit=25',
      expect.objectContaining({
        method: 'GET',
        credentials: 'include',
        headers: expect.objectContaining({
          Accept: 'application/json',
          Authorization: 'Bearer access-token',
          'X-Workspace-ID': 'workspace-1',
        }),
      }),
    );
  });

  it('loads safe attempt history for one encoded delivery id', async () => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    const attempts = [{
      id: 'attempt-1',
      delivery_id: 'delivery/1',
      phase: 'provider',
      attempt_number: 2,
      outcome: 'failed',
      error_code: 'provider_retryable',
      created_at: '2026-09-12T18:31:00Z',
    }];
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(attempts), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await channelDeliveriesApi.attempts('delivery/1', 25);

    expect(result).toEqual(attempts);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/channels/deliveries/delivery%2F1/attempts?limit=25',
      expect.objectContaining({
        method: 'GET',
        credentials: 'include',
        headers: expect.objectContaining({
          Accept: 'application/json',
          Authorization: 'Bearer access-token',
          'X-Workspace-ID': 'workspace-1',
        }),
      }),
    );
  });

  it('requeues one dispatch-failed delivery through the managed endpoint', async () => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    const requeued = {
      id: 'delivery/1',
      connection_id: 'channel-1',
      connection_name: 'Primary Telegram',
      message_id: 'message-1',
      provider: 'telegram',
      status: 'queued',
      error_code: null,
      attempt_count: 2,
      dispatch_attempts: 0,
      dispatched_at: null,
      processed_at: null,
      next_dispatch_at: '2026-09-12T18:40:00Z',
      created_at: '2026-09-12T18:29:00Z',
      updated_at: '2026-09-12T18:40:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(requeued), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await channelDeliveriesApi.requeue('delivery/1');

    expect(result).toEqual(requeued);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/channels/deliveries/delivery%2F1/requeue',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        headers: expect.objectContaining({
          Authorization: 'Bearer access-token',
          'X-Workspace-ID': 'workspace-1',
        }),
      }),
    );
  });
});
