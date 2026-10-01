import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  activateWorkspaceInvitationSession,
  workspaceInvitationApi,
  workspaceTeamApi,
} from '@/lib/workspace-team-api';

const fetchMock = vi.fn<typeof fetch>();

function response(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('workspace team API', () => {
  beforeEach(() => {
    localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    localStorage.setItem('northstar.session', JSON.stringify({
      accessToken: 'access-token',
      expiresAt: '2026-09-11T00:00:00Z',
      user: { id: 'user-1', name: 'Owner', email: 'owner@example.com', role: 'owner' },
    }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('applies bearer and active-workspace headers to team administration requests', async () => {
    fetchMock.mockResolvedValueOnce(response([]));

    await workspaceTeamApi.listMembers();

    const [url, options] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/v1/workspace/members');
    expect(options?.headers).toMatchObject({
      Authorization: 'Bearer access-token',
      'X-Workspace-ID': 'workspace-1',
    });
  });

  it('keeps invitation tokens out of URLs and workspace headers', async () => {
    fetchMock.mockResolvedValueOnce(response({ invitationId: 'invitation-1' }));

    await workspaceInvitationApi.preview('secret-invitation-token');

    const [url, options] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/v1/workspace-invitations/preview');
    expect(options?.body).toBe(JSON.stringify({ token: 'secret-invitation-token' }));
    expect(options?.headers).not.toHaveProperty('Authorization');
    expect(options?.headers).not.toHaveProperty('X-Workspace-ID');
  });

  it('authenticates acceptance without coupling it to a stale workspace header', async () => {
    fetchMock.mockResolvedValueOnce(response({ workspaceId: 'workspace-invited' }));

    await workspaceInvitationApi.accept('secret-invitation-token');

    const [, options] = fetchMock.mock.calls[0]!;
    expect(options?.headers).toMatchObject({ Authorization: 'Bearer access-token' });
    expect(options?.headers).not.toHaveProperty('X-Workspace-ID');
  });

  it('stores only the safe session and activates the accepted workspace', () => {
    const listener = vi.fn();
    window.addEventListener('northstar:auth-session', listener);

    activateWorkspaceInvitationSession({
      accessToken: 'new-access-token',
      refreshToken: 'development-only-refresh-token',
      expiresAt: '2026-09-11T00:00:00Z',
      tenantId: 'tenant-2',
      tenantSlug: 'academy',
      workspaceId: 'workspace-2',
      user: {
        id: 'user-1',
        name: 'Owner',
        email: 'owner@example.com',
        role: 'member',
        emailVerified: true,
      },
    });

    expect(JSON.parse(localStorage.getItem('northstar.session') ?? '{}')).toEqual({
      accessToken: 'new-access-token',
      expiresAt: '2026-09-11T00:00:00Z',
      user: {
        id: 'user-1',
        name: 'Owner',
        email: 'owner@example.com',
        role: 'member',
        emailVerified: true,
      },
    });
    expect(JSON.parse(localStorage.getItem('northstar.active-workspace-id') ?? 'null')).toBe('workspace-2');
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener('northstar:auth-session', listener);
  });
});
