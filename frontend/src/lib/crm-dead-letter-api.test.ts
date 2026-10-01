import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { crmDeadLetterApi } from '@/lib/crm-dead-letter-api';

const SESSION_KEY = 'northstar.session';
const ACTIVE_WORKSPACE_KEY = 'northstar.active-workspace-id';

describe('crmDeadLetterApi replay', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(SESSION_KEY, JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem(ACTIVE_WORKSPACE_KEY, JSON.stringify('workspace-123'));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('posts replay through the active Workspace with the current bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      dead_letter_id: 'dead-letter-1',
      delivery_id: 'delivery-1',
      dead_letter_status: 'resolved',
      delivery_status: 'retrying',
      replayed_at: '2026-09-12T09:15:00Z',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await crmDeadLetterApi.replay('dead-letter-1');

    expect(result.delivery_status).toBe('retrying');
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/crm/dead-letters/dead-letter-1/replay', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
      headers: expect.objectContaining({
        Accept: 'application/json',
        Authorization: 'Bearer access-token',
        'X-Workspace-ID': 'workspace-123',
      }),
    }));
  });
});
