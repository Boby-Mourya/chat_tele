import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { analyticsApi } from '@/lib/analytics-api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const summary = {
  period: 'Last 7 days',
  conversations: 12,
  conversationsDelta: 10,
  resolutionRate: 75,
  resolutionDelta: 5,
  avgResponseSeconds: 1.2,
  satisfaction: 4.5,
  chart: [{ label: 'Sep 10', conversations: 12, resolved: 9 }],
  topQuestions: [],
  channels: [{ channel: 'Widget', value: 100 }],
  agents: { total: 3, active: 2, support: 1, leadGeneration: 1, education: 1 },
  leads: { created: 4, qualified: 2, converted: 1, qualificationRate: 50, conversionRate: 25 },
  crm: { deliveries: 2, verified: 1, failed: 1, successRate: 50 },
  education: { students: 8, activeEnrollments: 7, conversations: 5, activityEvents: 3 },
};

describe('analyticsApi', () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'session-token', user: { id: 'u', name: 'User', email: 'user@example.com', role: 'owner' }, expiresAt: '2099-01-01T00:00:00Z' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('loads the selected period with authenticated workspace scope', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(summary));

    const result = await analyticsApi.summary(7);

    expect(result).toEqual(summary);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/analytics/summary?days=7', expect.objectContaining({
      credentials: 'include',
      headers: expect.objectContaining({
        Authorization: 'Bearer session-token',
        'X-Workspace-ID': 'workspace-1',
      }),
    }));
  });

  it('surfaces authorization failures instead of inventing analytics', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Insufficient permission' } }, 403));

    await expect(analyticsApi.summary(30)).rejects.toThrow('Insufficient permission');
  });

  it('keeps demo analytics available when the backend is unavailable', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));

    const result = await analyticsApi.summary(90);

    expect(result.period).toBe('Last 90 days');
    expect(result.agents?.total).toBeGreaterThan(0);
    expect(result.leads).toBeDefined();
    expect(result.crm).toBeDefined();
    expect(result.education).toBeDefined();
  });
});
