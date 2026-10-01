import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { WorkspaceInvitationPage } from '@/pages/WorkspaceInvitationPage';
import type { Session } from '@/types';

const invitationToken = 'workspace-invitation-token-with-more-than-thirty-two-characters';

const invitedSession = {
  accessToken: 'invited-access-token',
  expiresAt: '2026-09-11T00:00:00Z',
  tenantId: 'tenant-invited',
  tenantSlug: 'northstar-academy',
  workspaceId: 'workspace-invited',
  user: {
    id: 'user-invited',
    name: 'Invited User',
    email: 'invitee@example.com',
    role: 'member' as const,
    emailVerified: true,
  },
};

const mocks = vi.hoisted(() => ({
  auth: {
    session: null as Session | null,
    logout: vi.fn<() => Promise<void>>(),
  },
  preview: vi.fn(),
  accept: vi.fn(),
  signup: vi.fn(),
  decline: vi.fn(),
  activate: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useAuth: () => mocks.auth,
}));

vi.mock('@/lib/workspace-team-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/workspace-team-api')>(
    '@/lib/workspace-team-api',
  );
  return {
    ...actual,
    activateWorkspaceInvitationSession: mocks.activate,
    workspaceInvitationApi: {
      preview: mocks.preview,
      accept: mocks.accept,
      signup: mocks.signup,
      decline: mocks.decline,
    },
  };
});

function preview(existingUser = false) {
  return {
    invitationId: 'invitation-1',
    email: 'invitee@example.com',
    tenantId: 'tenant-invited',
    tenantName: 'Northstar Academy',
    tenantSlug: 'northstar-academy',
    workspaceId: 'workspace-invited',
    workspaceName: 'Admissions',
    role: 'operator' as const,
    allAgentsAccess: false,
    agentCount: 2,
    expiresAt: '2026-09-17T12:00:00Z',
    existingUser,
  };
}

function renderInvitation() {
  window.history.replaceState(
    null,
    '',
    `/workspace-invitation#token=${encodeURIComponent(invitationToken)}`,
  );
  return render(
    <MemoryRouter initialEntries={['/workspace-invitation']}>
      <Routes>
        <Route path="/workspace-invitation" element={<WorkspaceInvitationPage />} />
        <Route path="/login" element={<div>Sign in route</div>} />
        <Route path="/verify-email" element={<div>Email verification route</div>} />
        <Route path="/" element={<div>Workspace dashboard</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('WorkspaceInvitationPage', () => {
  beforeEach(() => {
    sessionStorage.clear();
    mocks.auth.session = null;
    mocks.auth.logout.mockResolvedValue();
    mocks.preview.mockResolvedValue(preview());
    mocks.accept.mockResolvedValue(invitedSession);
    mocks.signup.mockResolvedValue(invitedSession);
    mocks.decline.mockResolvedValue({ declined: true });
  });

  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  it('captures the fragment token, removes it from the browser URL, and completes invited signup', async () => {
    const user = userEvent.setup();
    renderInvitation();

    expect(window.location.hash).toBe('');
    expect(await screen.findByText('Join Admissions')).toBeInTheDocument();
    expect(mocks.preview).toHaveBeenCalledWith(invitationToken);

    await user.type(screen.getByLabelText('Full name'), '  Invited   User  ');
    await user.type(screen.getByLabelText('Password'), 'Invitation-Password-2026!');
    await user.type(screen.getByLabelText('Confirm password'), 'Invitation-Password-2026!');
    await user.click(screen.getByRole('checkbox', { name: /Terms of Service/i }));
    await user.click(screen.getByRole('checkbox', { name: /Privacy Policy/i }));
    await user.click(screen.getByRole('button', { name: /Create account and join/i }));

    await waitFor(() => expect(mocks.signup).toHaveBeenCalledWith({
      token: invitationToken,
      name: 'Invited User',
      password: 'Invitation-Password-2026!',
      termsAccepted: true,
      privacyAccepted: true,
    }));
    expect(mocks.activate).toHaveBeenCalledWith(invitedSession);
    expect(sessionStorage.getItem('northstar.pending-workspace-invitation')).toBeNull();
    expect(await screen.findByText('Workspace dashboard')).toBeInTheDocument();
  });

  it('lets the matching signed-in and verified account explicitly accept the workspace', async () => {
    mocks.auth.session = {
      accessToken: 'existing-access-token',
      expiresAt: '2026-09-11T00:00:00Z',
      user: {
        id: 'existing-user',
        name: 'Existing Invitee',
        email: 'INVITEE@example.com',
        role: 'member',
        emailVerified: true,
      },
    };
    mocks.preview.mockResolvedValueOnce(preview(true));
    const user = userEvent.setup();
    renderInvitation();

    expect(await screen.findByText('Signed in as')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Accept and open workspace/i }));

    await waitFor(() => expect(mocks.accept).toHaveBeenCalledWith(invitationToken));
    expect(mocks.signup).not.toHaveBeenCalled();
    expect(mocks.activate).toHaveBeenCalledWith(invitedSession);
  });

  it('sends an existing but unverified invited account to email verification first', async () => {
    mocks.auth.session = {
      accessToken: 'unverified-access-token',
      expiresAt: '2026-09-11T00:00:00Z',
      user: {
        id: 'existing-user',
        name: 'Existing Invitee',
        email: 'invitee@example.com',
        role: 'member',
        emailVerified: false,
      },
    };
    mocks.preview.mockResolvedValueOnce(preview(true));
    const user = userEvent.setup();
    renderInvitation();

    expect(await screen.findByRole('alert')).toHaveTextContent('Verify your email first');
    await user.click(screen.getByRole('button', { name: /Verify email to continue/i }));

    expect(mocks.accept).not.toHaveBeenCalled();
    expect(await screen.findByText('Email verification route')).toBeInTheDocument();
    expect(sessionStorage.getItem('northstar.pending-workspace-invitation')).toBe(invitationToken);
  });

  it('does not accept with a different signed-in account and supports account switching', async () => {
    mocks.auth.session = {
      accessToken: 'wrong-access-token',
      expiresAt: '2026-09-11T00:00:00Z',
      user: {
        id: 'wrong-user',
        name: 'Wrong User',
        email: 'wrong@example.com',
        role: 'owner',
        emailVerified: true,
      },
    };
    mocks.preview.mockResolvedValueOnce(preview(true));
    const user = userEvent.setup();
    renderInvitation();

    expect(await screen.findByRole('alert')).toHaveTextContent('invitation belongs to invitee@example.com');
    await user.click(screen.getByRole('button', { name: 'Sign out and switch account' }));

    await waitFor(() => expect(mocks.auth.logout).toHaveBeenCalledTimes(1));
    expect(mocks.accept).not.toHaveBeenCalled();
    expect(await screen.findByText('Sign in route')).toBeInTheDocument();
    expect(sessionStorage.getItem('northstar.pending-workspace-invitation')).toBe(invitationToken);
  });

  it('blocks invited-account creation while another account is signed in', async () => {
    mocks.auth.session = {
      accessToken: 'wrong-access-token',
      expiresAt: '2026-09-11T00:00:00Z',
      user: {
        id: 'wrong-user',
        name: 'Wrong User',
        email: 'wrong@example.com',
        role: 'owner',
        emailVerified: true,
      },
    };
    mocks.preview.mockResolvedValueOnce(preview(false));
    const user = userEvent.setup();
    renderInvitation();

    expect(await screen.findByRole('alert')).toHaveTextContent('invitation belongs to invitee@example.com');
    expect(screen.queryByRole('button', { name: /Create account and join/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Sign out and switch account' }));

    await waitFor(() => expect(mocks.auth.logout).toHaveBeenCalledTimes(1));
    expect(mocks.signup).not.toHaveBeenCalled();
    expect(await screen.findByText('Sign in route')).toBeInTheDocument();
  });

  it('invalidates the local token after declining the invitation', async () => {
    const user = userEvent.setup();
    renderInvitation();
    expect(await screen.findByText('Join Admissions')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Decline invitation' }));

    await waitFor(() => expect(mocks.decline).toHaveBeenCalledWith(invitationToken));
    expect(await screen.findByText('Invitation declined')).toBeInTheDocument();
    expect(sessionStorage.getItem('northstar.pending-workspace-invitation')).toBeNull();
  });
});
