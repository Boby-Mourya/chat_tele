import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceTeamPanel } from '@/components/WorkspaceTeamPanel';
import type { WorkspaceInvitation, WorkspaceMember } from '@/lib/workspace-team-api';
import type { WorkspaceSettings } from '@/lib/workspace-api';
import type { Agent } from '@/types';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  listMembers: vi.fn(),
  listInvitations: vi.fn(),
  invite: vi.fn(),
  updateMember: vi.fn(),
  removeMember: vi.fn(),
  resendInvitation: vi.fn(),
  revokeInvitation: vi.fn(),
  listAgents: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/api', () => ({
  api: { agents: { list: mocks.listAgents } },
}));

vi.mock('@/lib/workspace-team-api', () => ({
  workspaceTeamApi: {
    listMembers: mocks.listMembers,
    listInvitations: mocks.listInvitations,
    invite: mocks.invite,
    updateMember: mocks.updateMember,
    removeMember: mocks.removeMember,
    resendInvitation: mocks.resendInvitation,
    revokeInvitation: mocks.revokeInvitation,
  },
}));

const workspace: WorkspaceSettings = {
  id: 'workspace-1',
  tenantId: 'tenant-1',
  tenantName: 'Northstar Academy',
  name: 'Admissions',
  slug: 'admissions',
  status: 'active',
  role: 'workspace_admin',
  permissions: ['*'],
  plan: 'business',
  memberCount: 2,
  preferences: {
    timezone: 'Asia/Calcutta',
    defaultLanguage: 'English',
    dateFormat: 'DD/MM/YYYY',
  },
  security: { sensitiveDataMasking: true, securityContact: null },
  whiteLabel: {
    companyName: 'Northstar Academy',
    logoDataUrl: '',
    faviconDataUrl: '',
    appIconDataUrl: '',
    primaryColor: '#146cf6',
    secondaryColor: '#705cf6',
    supportEmail: 'support@example.com',
    supportUrl: 'https://example.com/support',
    browserTitle: 'Northstar',
    customDomain: '',
    dnsStatus: 'not-configured',
    brandedLogin: true,
    brandedDashboard: true,
    brandedWidget: true,
    brandedEmails: true,
    removePlatformBranding: false,
  },
};

const owner: WorkspaceMember = {
  userId: 'owner-1',
  name: 'Workspace Owner',
  email: 'owner@example.com',
  role: 'workspace_admin',
  allAgentsAccess: true,
  agentIds: [],
  joinedAt: '2026-09-01T00:00:00Z',
  isSelf: true,
};

const operator: WorkspaceMember = {
  userId: 'member-2',
  name: 'Support Operator',
  email: 'operator@example.com',
  role: 'operator',
  allAgentsAccess: false,
  agentIds: ['agent-1'],
  joinedAt: '2026-09-02T00:00:00Z',
  isSelf: false,
};

const agent = {
  id: 'agent-1',
  publicId: 'agent-public-1',
  name: 'Admissions Agent',
  description: 'Admissions help',
  instructions: '',
  status: 'active',
  tone: 'professional',
  language: 'English',
  avatar: '',
  conversations: 0,
  resolutionRate: 0,
  knowledgeCount: 0,
  lastUpdated: '2026-09-10T00:00:00Z',
  createdAt: '2026-09-01T00:00:00Z',
  appearance: {},
  model: {},
  security: {},
} as Agent;

function invitation(overrides: Partial<WorkspaceInvitation> = {}): WorkspaceInvitation {
  return {
    id: 'invitation-1',
    email: 'new.member@example.com',
    role: 'manager',
    allAgentsAccess: false,
    agentIds: ['agent-1'],
    status: 'pending',
    expiresAt: '2026-09-17T00:00:00Z',
    lastSentAt: '2026-09-10T00:00:00Z',
    deliveryAttempts: 1,
    deliveryState: 'sent',
    createdAt: '2026-09-10T00:00:00Z',
    ...overrides,
  };
}

describe('WorkspaceTeamPanel', () => {
  beforeEach(() => {
    mocks.listMembers.mockResolvedValue([owner, operator]);
    mocks.listInvitations.mockResolvedValue([]);
    mocks.listAgents.mockResolvedValue([agent]);
    mocks.invite.mockResolvedValue(invitation());
    mocks.updateMember.mockResolvedValue({
      ...operator,
      role: 'manager',
      allAgentsAccess: true,
      agentIds: [],
    });
    mocks.removeMember.mockResolvedValue(undefined);
    mocks.resendInvitation.mockResolvedValue(invitation({ deliveryAttempts: 2 }));
    mocks.revokeInvitation.mockResolvedValue(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('loads server-backed members and sends a restricted invitation', async () => {
    const user = userEvent.setup();
    render(<WorkspaceTeamPanel workspace={workspace} />);

    expect(await screen.findByText('Support Operator')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Invite member' }));
    await user.type(screen.getByLabelText('Email address'), 'NEW.MEMBER@EXAMPLE.COM');
    await user.selectOptions(screen.getByLabelText('Workspace role'), 'manager');
    await user.click(screen.getByRole('checkbox', { name: /Access all agents/i }));
    await user.click(screen.getByRole('checkbox', { name: 'Admissions Agent' }));
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    await waitFor(() => expect(mocks.invite).toHaveBeenCalledWith({
      email: 'new.member@example.com',
      role: 'manager',
      allAgentsAccess: false,
      agentIds: ['agent-1'],
    }));
    expect(await screen.findByText('new.member@example.com')).toBeInTheDocument();
    expect(localStorage.getItem('northstar.workspace.members')).toBeNull();
  });

  it('updates role and agent scope through the backend', async () => {
    const user = userEvent.setup();
    render(<WorkspaceTeamPanel workspace={workspace} />);
    expect(await screen.findByText('Support Operator')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Edit' }));
    await user.selectOptions(screen.getByLabelText('Workspace role'), 'manager');
    await user.click(screen.getByRole('checkbox', { name: /Access all agents/i }));
    await user.click(screen.getByRole('button', { name: 'Save access' }));

    await waitFor(() => expect(mocks.updateMember).toHaveBeenCalledWith('member-2', {
      role: 'manager',
      allAgentsAccess: true,
      agentIds: [],
    }));
  });

  it('supports resend, revoke, and member removal without changing local browser membership', async () => {
    mocks.listInvitations.mockResolvedValueOnce([invitation()]);
    const user = userEvent.setup();
    render(<WorkspaceTeamPanel workspace={workspace} />);
    expect(await screen.findByText('new.member@example.com')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Resend' }));
    await waitFor(() => expect(mocks.resendInvitation).toHaveBeenCalledWith('invitation-1'));
    await user.click(screen.getByRole('button', { name: 'Revoke invitation for new.member@example.com' }));
    await waitFor(() => expect(mocks.revokeInvitation).toHaveBeenCalledWith('invitation-1'));
    await user.click(screen.getByRole('button', { name: 'Remove Support Operator' }));
    await waitFor(() => expect(mocks.removeMember).toHaveBeenCalledWith('member-2'));
    expect(screen.queryByText('Support Operator')).not.toBeInTheDocument();
    expect(localStorage.getItem('northstar.workspace.members')).toBeNull();
  });

  it('loads member data without requesting agent data for read-only member viewers', async () => {
    render(<WorkspaceTeamPanel workspace={{ ...workspace, permissions: ['members.view'] }} />);

    expect(await screen.findByText('Support Operator')).toBeInTheDocument();
    expect(mocks.listMembers).toHaveBeenCalledTimes(1);
    expect(mocks.listInvitations).toHaveBeenCalledTimes(1);
    expect(mocks.listAgents).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Invite member' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove Support Operator' })).not.toBeInTheDocument();
  });
});
