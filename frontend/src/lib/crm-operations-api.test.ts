import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { crmOperationsApi } from '@/lib/crm-operations-api';

const SESSION_KEY = 'northstar.session';
const ACTIVE_WORKSPACE_KEY = 'northstar.active-workspace-id';

describe('crmOperationsApi', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(SESSION_KEY, JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem(ACTIVE_WORKSPACE_KEY, JSON.stringify('workspace-123'));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('loads operational health through the active Workspace', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      overall_status: 'healthy',
      connection_count: 1,
      healthy_connections: 1,
      attention_connections: 0,
      pending_deliveries: 0,
      retrying_deliveries: 0,
      failed_deliveries: 0,
      open_dead_letters: 0,
      connections: [],
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await crmOperationsApi.health();

    expect(result.overall_status).toBe('healthy');
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/crm/operations/health', expect.objectContaining({
      credentials: 'include',
      headers: expect.objectContaining({
        Accept: 'application/json',
        Authorization: 'Bearer access-token',
        'X-Workspace-ID': 'workspace-123',
      }),
    }));
  });
});
