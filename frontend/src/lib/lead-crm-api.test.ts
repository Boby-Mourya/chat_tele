import { afterEach, describe, expect, it, vi } from 'vitest';
import { leadCrmApi } from '@/lib/lead-crm-api';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('lead CRM API client', () => {
  it('saves and validates a provider field mapping', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        connection_id: 'crm-1', object_name: 'Leads', version: 1, status: 'draft', mapping: { fields: { email: 'Email' } }, validation: {}, schema_hash: null,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ valid: true, schemaHash: 'schema-1' }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    await leadCrmApi.putMapping('crm-1', { object_name: 'Leads', mapping: { fields: { email: 'Email' } } });
    await leadCrmApi.validateMappings('crm-1');

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/crm/connections/crm-1/mappings', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ object_name: 'Leads', mapping: { fields: { email: 'Email' } } }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/crm/connections/crm-1/mappings/validate', expect.objectContaining({ method: 'POST' }));
  });

  it('creates, updates, and deletes a tenant-scoped CRM route', async () => {
    const route = {
      id: 'route-1', name: 'Qualified leads', enabled: true, priority: 100, version: 1,
      conditions: { qualificationStatus: 'qualified' }, connection_ids: ['crm-1'],
      created_at: '2026-09-08T00:00:00Z', updated_at: '2026-09-08T00:00:00Z',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(route), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...route, enabled: false, version: 2 }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await leadCrmApi.createRoute({ name: route.name, priority: 100, conditions: route.conditions, connection_ids: ['crm-1'] });
    await leadCrmApi.updateRoute('route-1', { enabled: false });
    await leadCrmApi.deleteRoute('route-1');

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/crm/routes', expect.objectContaining({ method: 'POST' }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/crm/routes/route-1', expect.objectContaining({ method: 'PATCH' }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/v1/crm/routes/route-1', expect.objectContaining({ method: 'DELETE' }));
  });

  it('runs and reads workspace-scoped CRM health history endpoints with the active auth context', async () => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'access-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    const snapshot = {
      id: 'snapshot-1',
      connection_id: 'crm-1',
      status: 'healthy',
      checks: { api: 'ok' },
      latency_ms: 24,
      checked_at: '2026-09-12T09:00:00Z',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(snapshot), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify([snapshot]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    await leadCrmApi.runHealthCheck('crm-1');
    await leadCrmApi.healthHistory('crm-1', 25);

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/crm/connections/crm-1/health-check', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        Authorization: 'Bearer access-token',
        'X-Workspace-ID': 'workspace-1',
      }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/crm/connections/crm-1/health-history?limit=25', expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer access-token',
        'X-Workspace-ID': 'workspace-1',
      }),
    }));
  });
});
