import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/storage', () => ({
  readStorage: vi.fn(() => ({ accessToken: 'token-123' })),
}));

vi.mock('@/lib/workspace-api', () => ({
  activeWorkspaceId: vi.fn(() => 'workspace-1'),
}));

import { educationSalesSettingsApi } from '@/lib/education-sales-settings-api';

describe('educationSalesSettingsApi', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('loads the workspace-scoped Education sales routing setting', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ createUpsellLeads: false }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await educationSalesSettingsApi.get();

    expect(result).toEqual({ createUpsellLeads: false });
    const [url, options] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain('/education/settings/sales-routing');
    expect(options).toMatchObject({ method: 'GET', credentials: 'include' });
    expect(options.headers).toMatchObject({
      Authorization: 'Bearer token-123',
      'X-Workspace-ID': 'workspace-1',
    });
  });

  it('persists the explicit opt-in using PATCH without touching generic workspace settings', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ createUpsellLeads: true }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await educationSalesSettingsApi.update({ createUpsellLeads: true });

    expect(result).toEqual({ createUpsellLeads: true });
    const [url, options] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain('/education/settings/sales-routing');
    expect(options).toMatchObject({
      method: 'PATCH',
      credentials: 'include',
      body: JSON.stringify({ createUpsellLeads: true }),
    });
    expect(options.headers).toMatchObject({
      Authorization: 'Bearer token-123',
      'X-Workspace-ID': 'workspace-1',
      'Content-Type': 'application/json',
    });
  });

  it('fails closed when the backend refuses the workspace setting request', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ error: { message: 'Forbidden' } }),
    }));

    await expect(educationSalesSettingsApi.update({ createUpsellLeads: true })).rejects.toMatchObject({
      status: 403,
    });
  });
});
