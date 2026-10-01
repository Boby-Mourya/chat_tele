import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { crmWorkflowApi } from '@/lib/crm-workflow-api';

const fetchMock = vi.fn<typeof fetch>();

describe('crm workflow API', () => {
  beforeEach(() => {
    localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    localStorage.setItem('northstar.session', JSON.stringify({
      accessToken: 'workflow-access-token',
      expiresAt: '2026-09-14T00:00:00Z',
      user: {
        id: 'user-1',
        name: 'Workspace Owner',
        email: 'owner@example.com',
        role: 'owner',
      },
    }));
    localStorage.setItem(
      'northstar.active-workspace-id',
      JSON.stringify('workspace-crm-1'),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('requests the live workflow with bearer and active-workspace scope', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      generatedAt: '2026-09-13T05:30:00Z',
      workspaceId: 'workspace-crm-1',
      readiness: { ready: false, stages: [] },
      counts: {
        resolvedConversations: 0,
        localLeads: 0,
        leadsWithoutDelivery: 0,
        totalDeliveries: 0,
        inFlightDeliveries: 0,
        verifiedDeliveries: 0,
        attentionDeliveries: 0,
        openDeadLetters: 0,
        byStatus: {},
      },
      connections: [],
      recentJourneys: [],
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));

    await crmWorkflowApi.get(50);

    const [url, options] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/v1/crm/workflow?limit=50');
    expect(options?.headers).toMatchObject({
      Authorization: 'Bearer workflow-access-token',
      'X-Workspace-ID': 'workspace-crm-1',
    });
    expect(options?.credentials).toBe('include');
  });

  it('surfaces the normalized API error message', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      error: { message: 'Insufficient permission' },
    }), {
      status: 403,
      headers: { 'Content-Type': 'application/json' },
    }));

    await expect(crmWorkflowApi.get()).rejects.toThrow('Insufficient permission');
  });
});
