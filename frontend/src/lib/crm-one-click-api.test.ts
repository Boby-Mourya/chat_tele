import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { crmOneClickApi } from '@/lib/crm-one-click-api';

const fetchMock = vi.fn<typeof fetch>();

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('crmOneClickApi', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('northstar.session', JSON.stringify({
      accessToken: 'access-token',
      expiresAt: '2099-01-01T00:00:00Z',
      user: { id: 'user-1', name: 'Owner', email: 'owner@example.com', role: 'owner' },
    }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('starts managed OAuth with authentication and workspace isolation', async () => {
    fetchMock.mockResolvedValueOnce(response({
      authorizationUrl: 'https://accounts.zoho.com/oauth/v2/auth',
      connectionId: 'connection-1',
      provider: 'zoho',
      workspaceId: 'workspace-1',
      responseMode: 'popup',
    }));

    await crmOneClickApi.startOAuth('zoho', { name: 'Zoho India', region: 'in' });

    const [url, options] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/v1/crm/one-click/zoho/start');
    expect(options?.method).toBe('POST');
    expect(options?.headers).toMatchObject({
      Authorization: 'Bearer access-token',
      'X-Workspace-ID': 'workspace-1',
      'Content-Type': 'application/json',
    });
    expect(JSON.parse(String(options?.body))).toEqual({ name: 'Zoho India', region: 'in' });
  });

  it('polls an exact connection and delivery rather than accepting an old certification', async () => {
    fetchMock.mockResolvedValueOnce(response({
      connectionId: 'connection-1',
      deliveryId: 'delivery-1',
      leadId: 'lead-1',
      provider: 'zoho',
      status: 'verified',
      acknowledged: true,
      verificationStatus: 'verified',
      verified: true,
      externalRecordId: 'zoho-lead-1',
    }));

    const value = await crmOneClickApi.acceptanceStatus('connection-1', 'delivery-1');

    expect(value.externalRecordId).toBe('zoho-lead-1');
    expect(fetchMock.mock.calls[0]![0]).toBe(
      '/api/v1/crm/connections/connection-1/acceptance-test/delivery-1',
    );
  });

  it('surfaces structured readiness blockers', async () => {
    fetchMock.mockResolvedValueOnce(response({
      detail: { message: 'CRM is not ready', blockers: ['event_pipeline_not_enabled'] },
    }, 409));

    await expect(crmOneClickApi.acceptanceTest('connection-1')).rejects.toThrow('CRM is not ready');
  });
});
