import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { invitationDeliveryNotice, workspaceTeamApi, type WorkspaceInvitation } from '@/lib/workspace-team-api';
import { persistActiveWorkspace } from '@/lib/workspace-api';

const access = { role: 'operator' as const, allAgentsAccess: false, agentIds: [] };
const invitation: WorkspaceInvitation = { id: 'i1', email: 'member@example.com', ...access, status: 'pending',
  deliveryAttempts: 1, deliveryState: 'sent', lastSentAt: '2026-09-19T00:00:00Z', createdAt: '2026-09-19T00:00:00Z', expiresAt: '2026-09-26T00:00:00Z' };
function result(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }); }
function identity(tenant = 't1', jti = 'old') {
  localStorage.setItem('northstar.session', JSON.stringify({ accessToken: `header.${btoa(JSON.stringify({ tid: tenant, cv: 0, jti }))}.signature`,
    user: { id: 'u1', role: 'owner', emailVerified: true } }));
}

describe('team client reliability', () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => { identity(); persistActiveWorkspace('w1'); vi.stubGlobal('fetch', fetchMock); });
  afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); });

  it('preserves the existing member endpoints and request shape', async () => {
    fetchMock.mockResolvedValueOnce(result({}));
    await workspaceTeamApi.updateMember('target', access);
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/workspace/members/target', expect.objectContaining({
      method: 'PATCH', body: JSON.stringify(access),
    }));
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await workspaceTeamApi.removeMember('target');
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/workspace/members/target', expect.objectContaining({ method: 'DELETE' }));
  });
  it('does not replay a write when the token changes', async () => {
    fetchMock.mockImplementationOnce(async () => { identity('t1', 'renewed'); return result(invitation); });
    await expect(workspaceTeamApi.invite({ ...access, email: invitation.email })).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it('discards a response for an earlier workspace', async () => {
    fetchMock.mockImplementationOnce(async () => { persistActiveWorkspace('w2'); return result([]); });
    await expect(workspaceTeamApi.listMembers()).rejects.toMatchObject({ name: 'AbortError' });
  });
  it('discards a response from an earlier organization', async () => {
    fetchMock.mockImplementationOnce(async () => { identity('t2'); return result([]); });
    await expect(workspaceTeamApi.listMembers()).rejects.toMatchObject({ name: 'AbortError' });
  });
  it('passes caller cancellation to the read', async () => {
    const controller = new AbortController(); fetchMock.mockResolvedValueOnce(result([]));
    await workspaceTeamApi.listMembers(controller.signal);
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/workspace/members', expect.objectContaining({ signal: controller.signal, cache: 'no-store' }));
  });
  it('preserves backend conflicts and does not fabricate a successful mutation', async () => {
    fetchMock.mockResolvedValueOnce(result({ detail: 'Member access changed' }, 409));
    await expect(workspaceTeamApi.updateMember('target', access)).rejects.toMatchObject({ status: 409, message: 'Member access changed' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it.each(['failed', 'not-sent'] as const)('does not present %s mail as sent', (deliveryState) => {
    const notice = invitationDeliveryNotice({ ...invitation, deliveryState });
    expect(notice.tone).not.toBe('success'); expect(notice.message).toContain('saved');
  });
  it('reports email success only for the current pending invitation', () => {
    expect(invitationDeliveryNotice(invitation).tone).toBe('success');
    expect(invitationDeliveryNotice({ ...invitation, status: 'revoked' }).tone).toBe('info');
  });
});
