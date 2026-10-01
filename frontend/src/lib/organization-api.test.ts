import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { organizationApi } from '@/lib/organization-api';
import { activeWorkspaceId, clearActiveWorkspaceSelection, persistActiveWorkspace } from '@/lib/workspace-api';

const jwt = (tid: string) => `x.${btoa(JSON.stringify({ tid }))}.x`;
const current = { accessToken: jwt('org-a'), expiresAt: '2099-01-01T00:00:00Z', user: { id: 'user-a', name: 'User', email: 'user@example.com', role: 'owner', emailVerified: true } };
const selected = { ...current, accessToken: jwt('org-b'), organizationId: 'org-b', organizationName: 'Second', refreshToken: 'not-for-local-storage', user: { ...current.user, role: 'billing_admin' } };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

describe('organizationApi', () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    localStorage.setItem('northstar.session', JSON.stringify(current));
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    clearActiveWorkspaceSelection(); localStorage.clear(); sessionStorage.clear();
    vi.unstubAllGlobals(); vi.clearAllMocks();
  });
  it('lists memberships without an operational workspace header', async () => {
    fetchMock.mockResolvedValueOnce(json({ organizations: [], nextCursor: null }));
    await expect(organizationApi.list()).resolves.toEqual({ organizations: [], nextCursor: null });
    const options = fetchMock.mock.calls[0]?.[1];
    expect(options?.credentials).toBe('include');
    expect(new Headers(options?.headers).has('X-Workspace-ID')).toBe(false);
  });
  it('selects the destination role and never stores refresh credentials', async () => {
    fetchMock.mockResolvedValueOnce(json(selected));
    await organizationApi.select('org-b');
    const stored = JSON.parse(localStorage.getItem('northstar.session') ?? '{}') as Record<string, unknown>;
    expect(stored.accessToken).toBe(selected.accessToken); expect(stored.refreshToken).toBeUndefined();
    expect(activeWorkspaceId()).toBeNull();
  });
  it('clears a removed workspace when reopening the current organization', async () => {
    persistActiveWorkspace('removed-workspace');
    fetchMock.mockResolvedValueOnce(json({ ...selected, accessToken: current.accessToken, organizationId: 'org-a' }));
    await organizationApi.select('org-a'); expect(activeWorkspaceId()).toBeNull();
  });
  it('does not fabricate memberships after an outage', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    await expect(organizationApi.list()).rejects.toThrow('Network unavailable');
  });
  it('does not replay an ambiguous selection and clears mismatched access state', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    await expect(organizationApi.select('org-b')).rejects.toThrow('not retried');
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(localStorage.getItem('northstar.session')).toBeNull();
  });
  it('retains the old account after a definite authorization denial', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: 'Not authorized' }, 403));
    await expect(organizationApi.select('org-b')).rejects.toThrow('Not authorized');
    expect(JSON.parse(localStorage.getItem('northstar.session') ?? '{}').accessToken).toBe(current.accessToken);
  });
  it('rejects a response for a different selected organization', async () => {
    fetchMock.mockResolvedValueOnce(json({ ...selected, organizationId: 'foreign' }));
    await expect(organizationApi.select('org-b')).rejects.toThrow('could not be verified');
    expect(localStorage.getItem('northstar.session')).toBeNull();
  });
});
