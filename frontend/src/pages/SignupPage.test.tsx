import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { SignupInput } from '@/lib/signup-api';
import { LoginPage } from '@/pages/LoginPage';
import { SignupPage } from '@/pages/SignupPage';
import type { Session } from '@/types';

const unverifiedSession: Session = {
  accessToken: 'access-token',
  expiresAt: '2026-09-11T00:00:00Z',
  user: {
    id: 'user-signup',
    name: 'Sakshee Jha',
    email: 'sakshee@example.com',
    role: 'owner',
    emailVerified: false,
  },
};

const mocks = vi.hoisted(() => ({
  signup: vi.fn<(input: SignupInput) => Promise<Session>>(),
  login: vi.fn<(email: string, password: string) => Promise<Session>>(),
}));

vi.mock('@/components/providers', () => ({
  useAuth: () => ({
    session: null,
    signup: mocks.signup,
    login: mocks.login,
    logout: vi.fn(),
  }),
}));

function renderSignup(initialEntry = '/signup') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/verify-email" element={<div>Email verification route</div>} />
        <Route path="/" element={<div>Workspace dashboard</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

async function fillValidSignup(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Your name'), '  Sakshee   Jha  ');
  await user.type(screen.getByLabelText('Organization'), '  NorthStar   Academy  ');
  await user.type(screen.getByLabelText('Business email'), 'SAKSHEE@EXAMPLE.COM');
  await user.type(screen.getByLabelText('Password'), 'Signup-Password-2026!');
}

describe('SignupPage', () => {
  beforeEach(() => {
    mocks.signup.mockResolvedValue(unverifiedSession);
    mocks.login.mockResolvedValue({
      ...unverifiedSession,
      user: { ...unverifiedSession.user, emailVerified: true },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('requires Terms and Privacy acceptance before creating an account', async () => {
    const user = userEvent.setup();
    renderSignup();
    await fillValidSignup(user);

    await user.click(screen.getByRole('button', { name: 'Create account' }));

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Accept the Terms and Privacy Policy to create your account.',
    );
    expect(mocks.signup).not.toHaveBeenCalled();
  });

  it('normalizes form values, creates the account, and enters email verification', async () => {
    const user = userEvent.setup();
    renderSignup();
    await fillValidSignup(user);
    await user.click(screen.getByRole('checkbox', { name: /Terms of Service/i }));
    await user.click(screen.getByRole('checkbox', { name: /Privacy Policy/i }));

    await user.click(screen.getByRole('button', { name: 'Create account' }));

    await waitFor(() => expect(mocks.signup).toHaveBeenCalledWith({
      name: 'Sakshee Jha',
      organizationName: 'NorthStar Academy',
      email: 'sakshee@example.com',
      password: 'Signup-Password-2026!',
      termsAccepted: true,
      privacyAccepted: true,
    }));
    expect(await screen.findByText('Email verification route')).toBeInTheDocument();
  });

  it('accepts a workspace invitation without creating a new organization', async () => {
    const user = userEvent.setup();
    const token = 'workspace-invitation-token-with-more-than-thirty-two-characters';
    renderSignup(`/signup#invite=${token}`);

    expect(screen.getByRole('heading', { name: 'Join your workspace' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Organization')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Your name'), 'Invited Member');
    await user.type(screen.getByLabelText('Business email'), 'MEMBER@EXAMPLE.COM');
    await user.type(screen.getByLabelText('Password'), 'Invited-Password-2026!');
    await user.click(screen.getByRole('checkbox', { name: /Terms of Service/i }));
    await user.click(screen.getByRole('checkbox', { name: /Privacy Policy/i }));
    await user.click(screen.getByRole('button', { name: 'Join workspace' }));

    await waitFor(() => expect(mocks.signup).toHaveBeenCalledWith({
      name: 'Invited Member',
      workspaceInvitationToken: token,
      email: 'member@example.com',
      password: 'Invited-Password-2026!',
      termsAccepted: true,
      privacyAccepted: true,
    }));
  });

  it('allows a demo/already-verified signup session to enter the workspace', async () => {
    mocks.signup.mockResolvedValueOnce({
      ...unverifiedSession,
      user: { ...unverifiedSession.user, emailVerified: true },
    });
    const user = userEvent.setup();
    renderSignup();
    await fillValidSignup(user);
    await user.click(screen.getByRole('checkbox', { name: /Terms of Service/i }));
    await user.click(screen.getByRole('checkbox', { name: /Privacy Policy/i }));
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByText('Workspace dashboard')).toBeInTheDocument();
  });

  it('shows an actionable duplicate-account error returned by the signup API', async () => {
    mocks.signup.mockRejectedValueOnce(new Error('An account with this email already exists'));
    const user = userEvent.setup();
    renderSignup();
    await fillValidSignup(user);
    await user.click(screen.getByRole('checkbox', { name: /Terms of Service/i }));
    await user.click(screen.getByRole('checkbox', { name: /Privacy Policy/i }));

    await user.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('An account with this email already exists');
  });

  it('connects the existing login page Create an account link to /signup', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<div>Signup route</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole('link', { name: 'Create an account' }));

    expect(await screen.findByText('Signup route')).toBeInTheDocument();
  });
});
