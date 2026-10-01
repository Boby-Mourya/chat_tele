import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { WorkspacePage } from '@/pages/WorkspacePage';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  getTeam: vi.fn(),
  inviteMember: vi.fn(),
  update: vi.fn(),
  pushToast: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useAuth: () => ({
    session: {
      accessToken: 'access-token',
      expiresAt: '2026-09-11T00:00:00Z',
      user: {
        id: 'owner-user',
        name: 'Workspace Owner',
        email: 'owner@example.com',
        role: 'owner',
        emailVerified: true,
      },
    },
  }),
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/workspace-api', () => ({
  workspaceApi: {
    get: mocks.get,
    getTeam: mocks.getTeam,
    inviteMember: mocks.inviteMember,
    update: mocks.update,
  },
}));

const workspace = {
  id: 'workspace-1',
  name: 'Northstar Workspace',
  slug: 'northstar',
  plan: 'business',
  memberCount: 1,
  permissions: ['*'],
  preferences: { timezone: 'Asia/Calcutta', defaultLanguage: 'English', dateFormat: 'DD/MM/YYYY' as const },
  whiteLabel: {
    companyName: 'Northstar AI', logoDataUrl: '', faviconDataUrl: '', appIconDataUrl: '',
    primaryColor: '#146cf6', secondaryColor: '#705cf6', supportEmail: 'support@northstar.ai',
    supportUrl: 'https://northstar.ai/support', browserTitle: 'Northstar AI', customDomain: '',
    dnsStatus: 'not-configured' as const, brandedLogin: true, brandedDashboard: true, brandedWidget: true,
    brandedEmails: true, removePlatformBranding: false,
  },
};

const initialTeam = {
  members: [{
    id: 'owner-user',
    name: 'Workspace Owner',
    email: 'owner@example.com',
    role: 'workspace_admin' as const,
    tenantRole: 'owner' as const,
    status: 'active' as const,
  }],
  invitations: [],
};

describe('Workspace team section', () => {
  beforeEach(() => {
    mocks.get.mockResolvedValue(workspace);
    mocks.getTeam.mockResolvedValue(initialTeam);
    mocks.inviteMember.mockResolvedValue({
      ...initialTeam,
      invitations: [{
        id: 'invite-1',
        email: 'analyst@example.com',
        role: 'analyst',
        status: 'invited',
        createdAt: '2026-09-10T10:00:00Z',
        expiresAt: '2026-09-17T10:00:00Z',
      }],
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('loads the server team and sends invitations through the workspace API', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={['/?section=team']}><WorkspacePage /></MemoryRouter>);

    expect(await screen.findByText('Workspace Owner')).toBeInTheDocument();
    expect(mocks.getTeam).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Invite member' }));
    await user.type(screen.getByLabelText('Email address'), 'ANALYST@EXAMPLE.COM');
    await user.selectOptions(screen.getByLabelText('Role'), 'analyst');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    await waitFor(() => expect(mocks.inviteMember).toHaveBeenCalledWith('analyst@example.com', 'analyst'));
    expect(await screen.findByText('analyst@example.com')).toBeInTheDocument();
    expect(mocks.pushToast).toHaveBeenCalledWith('Invitation sent to analyst@example.com');
  });
});
