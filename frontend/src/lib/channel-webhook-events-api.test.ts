import { afterEach, describe, expect, it, vi } from 'vitest';
import { channelWebhookEventsApi } from '@/lib/channel-webhook-events-api';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('channel webhook activity API client', () => {
  it('loads filtered Workspace-scoped webhook evidence with auth context', async () => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    const event = {
      id: 'event-1',
      connection_id: 'channel-1',
      provider: 'telegram',
      event_type: 'message.received',
      verification_status: 'verified',
      processing_status: 'failed',
      attempt_count: 2,
      error_code: 'processing_failed',
      can_requeue: true,
      correlation_id: 'corr-1',
      received_at: '2026-09-12T13:00:00Z',
      processed_at: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([event]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await channelWebhookEventsApi.list({
      connectionId: 'channel/1',
      processingStatus: 'failed',
      provider: 'telegram',
      limit: 25,
    });

    expect(result).toEqual([event]);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/channels/webhook-events?connection_id=channel%2F1&processing_status=failed&provider=telegram&limit=25',
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

  it('requeues one server-approved failed webhook through the managed endpoint', async () => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    const requeued = {
      id: 'event/1',
      connection_id: 'channel-1',
      provider: 'telegram',
      event_type: 'message.received',
      verification_status: 'verified',
      processing_status: 'received',
      attempt_count: 2,
      error_code: null,
      can_requeue: false,
      correlation_id: 'corr-1',
      received_at: '2026-09-12T13:00:00Z',
      processed_at: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(requeued), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await channelWebhookEventsApi.requeue('event/1');

    expect(result).toEqual(requeued);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/channels/webhook-events/event%2F1/requeue',
      expect.objectContaining({
        method: 'POST',
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
