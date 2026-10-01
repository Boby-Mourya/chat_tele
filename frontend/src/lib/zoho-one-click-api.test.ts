import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { zohoOneClickApi } from '@/lib/zoho-one-click-api';

const fetchMock = vi.fn<typeof fetch>();

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('Zoho one-click API', () => {
  beforeEach(() => {
    localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('loads workspace-scoped one-click readiness without exposing secrets', async () => {
    fetchMock.mockResolvedValueOnce(response({
      platformConfigured: true,
      connected: true,
      status: 'healthy',
      connectionId: 'connection-1',
      autoSyncNewLeads: true,
      autoSyncUpdates: true,
      mappingReady: true,
      routeReady: true,
      liveCertification: { status: 'verified', externalRecordId: 'zoho-lead-1' },
      missingConfiguration: [],
    }));

    const result = await zohoOneClickApi.status();
    expect(result.liveCertification?.externalRecordId).toBe('zoho-lead-1');
    const [url, options] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/v1/crm/zoho/one-click/status');
    expect(options?.headers).toMatchObject({
      Authorization: 'Bearer access-token',
      'X-Workspace-ID': 'workspace-1',
    });
  });

  it('starts OAuth and runs live certification through explicit endpoints', async () => {
    fetchMock
      .mockResolvedValueOnce(response({
        authorizationUrl: 'https://accounts.zoho.com/oauth/v2/auth?state=state',
        connectionId: 'connection-1',
        provider: 'zoho',
      }))
      .mockResolvedValueOnce(response({
        connectionId: 'connection-1',
        mappingId: 'mapping-1',
        routeId: 'route-1',
        liveTest: 'verified',
        externalRecordId: 'zoho-lead-1',
        verifiedFields: ['Email', 'Last_Name'],
      }));

    const started = await zohoOneClickApi.start();
    const certified = await zohoOneClickApi.certify();
    expect(started.authorizationUrl).toContain('accounts.zoho.com');
    expect(certified.liveTest).toBe('verified');
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/crm/zoho/one-click/start',
      '/api/v1/crm/zoho/one-click/certify',
    ]);
  });

  it('surfaces safe backend errors', async () => {
    fetchMock.mockResolvedValueOnce(response({ detail: 'Zoho OAuth application is not configured' }, 503));
    await expect(zohoOneClickApi.start()).rejects.toThrow('Zoho OAuth application is not configured');
  });
});
