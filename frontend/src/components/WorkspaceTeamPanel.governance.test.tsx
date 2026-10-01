import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { WorkspaceTeamPanel } from '@/components/WorkspaceTeamPanel';
import { workspaceDefaults } from '@/lib/workspace-api';
import type { WorkspaceMember } from '@/lib/workspace-team-api';

const mocks = vi.hoisted(() => ({ listMembers: vi.fn(), listInvitations: vi.fn(), invite: vi.fn(), updateMember: vi.fn(),
  removeMember: vi.fn(), resendInvitation: vi.fn(), revokeInvitation: vi.fn(), pushToast: vi.fn(), listAgents: vi.fn() }));
vi.mock('@/components/providers', () => ({ useToast: () => ({ pushToast: mocks.pushToast }) }));
vi.mock('@/lib/api', () => ({ AUTH_SESSION_EVENT: 'northstar:session-changed', api: { agents: { list: mocks.listAgents } } }));
vi.mock('@/lib/workspace-team-api', async (original) => ({
  ...await original<typeof import('@/lib/workspace-team-api')>(),
  workspaceTeamApi: { listMembers: mocks.listMembers, listInvitations: mocks.listInvitations, invite: mocks.invite,
    updateMember: mocks.updateMember, removeMember: mocks.removeMember, resendInvitation: mocks.resendInvitation,
    revokeInvitation: mocks.revokeInvitation },
}));
const workspace = { ...workspaceDefaults, id: 'w1', permissions: ['members.view', 'members.manage', 'members.invite'] };
const self: WorkspaceMember = { userId: 'self', name: 'Owner', email: 'owner@example.com', role: 'workspace_admin',
  allAgentsAccess: true, agentIds: [], joinedAt: '2026-09-19T00:00:00Z', isSelf: true };
const target: WorkspaceMember = { ...self, userId: 'target', name: 'Target', email: 'target@example.com', isSelf: false, role: 'viewer' };

describe('member editor governance', () => {
  beforeEach(() => { mocks.listMembers.mockResolvedValue([self, target]); mocks.listInvitations.mockResolvedValue([]); mocks.listAgents.mockResolvedValue([]); });
  afterEach(() => { cleanup(); vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear(); });
  it('uses the existing member update contract', async () => {
    mocks.updateMember.mockResolvedValue(target);
    render(<WorkspaceTeamPanel workspace={workspace} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save access' }));
    await waitFor(() => expect(mocks.updateMember).toHaveBeenCalledWith('target', { role: 'viewer', allAgentsAccess: true, agentIds: [] }));
  });
  it('keeps the edit dialog after a conflict and offers explicit reload', async () => {
    mocks.updateMember.mockRejectedValue(new Error('Member access changed'));
    render(<WorkspaceTeamPanel workspace={workspace} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save access' }));
    const reload = await screen.findByRole('button', { name: 'Discard draft and reload team' });
    expect(reload).toBeTruthy(); expect(screen.getByRole('dialog')).toBeTruthy();
    expect(mocks.updateMember).toHaveBeenCalledTimes(1);
  });
  it('does not show invitation delivery failure as success', async () => {
    mocks.invite.mockResolvedValue({ id: 'i1', email: 'new@example.com', role: 'operator', allAgentsAccess: true, agentIds: [], status: 'pending',
      deliveryState: 'failed', deliveryAttempts: 1, lastSentAt: null, createdAt: '2026-09-19T00:00:00Z', expiresAt: '2026-09-26T00:00:00Z' });
    render(<WorkspaceTeamPanel workspace={workspace} />);
    await screen.findByRole('button', { name: 'Edit' });
    fireEvent.click(screen.getByRole('button', { name: 'Invite member' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Email address'), { target: { value: 'new@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send invitation' }));
    await waitFor(() => expect(mocks.pushToast).toHaveBeenCalledWith(expect.stringContaining('email delivery failed'), 'error'));
  });
  it('does not use wildcard text as member administration authority', async () => {
    render(<WorkspaceTeamPanel workspace={{ ...workspace, permissions: ['*'] }} />);
    await screen.findByText('Your current role cannot view team membership.');
    expect(screen.queryByRole('button', { name: 'Invite member' })).toBeNull();
    expect(mocks.listMembers).not.toHaveBeenCalled();
  });
  it('guards duplicate submissions while a mutation is pending', async () => {
    mocks.updateMember.mockReturnValue(new Promise(() => undefined));
    render(<WorkspaceTeamPanel workspace={workspace} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const form = document.getElementById('workspace-member-edit-form')!;
    fireEvent.submit(form); fireEvent.submit(form);
    expect(mocks.updateMember).toHaveBeenCalledTimes(1);
  });
});
