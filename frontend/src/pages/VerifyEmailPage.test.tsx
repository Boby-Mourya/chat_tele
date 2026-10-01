import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { VerifyEmailPage } from '@/pages/VerifyEmailPage';
import type { Session } from '@/types';

const unverifiedSession: Session = {
  accessToken: 'access-token',
  expiresAt: '2026-09-11T00:00:00Z',
  user: {
    id: 'user-verify',
    name: 'Verification Owner',
    email: 'owner@example.com',
    role: 'owner',
    emailVerified: false,
  },
};

const verifiedSession: Session = {
  ...unverifiedSession,
  accessToken: 'rotated-access-token',
  user: { ...unverifiedSession.user, emailVerified: true },
};

const mocks = vi.hoisted(() => ({
  session: null as Session | null,
  logout: vi.fn<() => Promise<void>>(),
  resend: vi.fn<(email: string) => Promise<void>>(),
  verify: vi.fn<(token: string) => Promise<{ verified: boolean; alreadyVerified: boolean }>>(),
  refreshSession: vi.fn<() => Promise<Session>>(),
}));

vi.mock('@/components/providers', () => ({
  useAuth: () => ({
    session: mocks.session,
    logout: mocks.logout,
  }),
}));

vi.mock('@/lib/email-verification-api', () => ({
  emailVerificationApi: {
    resend: mocks.resend,
    verify: mocks.verify,
    refreshSession: mocks.refreshSession,
  },
}));

function renderVerification(entry = '/verify-email') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route path="/login" element={<div>Sign in route</div>} />
        <Route path="/" element={<div>Workspace dashboard</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('VerifyEmailPage', () => {
  beforeEach(() => {
    mocks.session = unverifiedSession;
    mocks.logout.mockResolvedValue(undefined);
    mocks.resend.mockResolvedValue(undefined);
    mocks.verify.mockResolvedValue({ verified: true, alreadyVerified: false });
    mocks.refreshSession.mockResolvedValue(verifiedSession);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows the signed-in email and can request a fresh verification message', async () => {
    const user = userEvent.setup();
    renderVerification();

    expect(screen.getByText('owner@example.com')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Resend verification email' }));

    await waitFor(() => expect(mocks.resend).toHaveBeenCalledWith('owner@example.com'));
    expect(screen.getByRole('status')).toHaveTextContent(
      'If that account needs verification, a new email is on the way.',
    );
    expect(screen.getByRole('button', { name: /Resend available in 60s/ })).toBeDisabled();
  });

  it('verifies a fragment link, refreshes the session, and enters the workspace', async () => {
    renderVerification('/verify-email#token=valid-token-value-1234567890');

    await waitFor(() => expect(mocks.verify).toHaveBeenCalledWith('valid-token-value-1234567890'));
    await waitFor(() => expect(mocks.refreshSession).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Workspace dashboard')).toBeInTheDocument();
  });

  it('keeps legacy query-string links compatible and exposes resend recovery on expiry', async () => {
    mocks.verify.mockRejectedValueOnce(new Error('Verification link is invalid or expired'));
    renderVerification('/verify-email?token=expired-token-value-1234567890');

    await waitFor(() => expect(mocks.verify).toHaveBeenCalledWith('expired-token-value-1234567890'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Verification link is invalid or expired');
    expect(screen.getByRole('button', { name: 'Resend verification email' })).toBeEnabled();
  });

  it('verifies from a signed-out browser without requiring a refresh session', async () => {
    mocks.session = null;
    renderVerification('/verify-email#token=valid-signed-out-token-1234567890');

    await waitFor(() => expect(mocks.verify).toHaveBeenCalledTimes(1));
    expect(mocks.refreshSession).not.toHaveBeenCalled();
    expect(await screen.findByText('Verification complete')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Continue to sign in/ })).toHaveAttribute('href', '/login');
  });

  it('signs out an unverified session before switching accounts', async () => {
    const user = userEvent.setup();
    renderVerification();

    await user.click(screen.getByRole('button', { name: 'Use a different account' }));

    await waitFor(() => expect(mocks.logout).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Sign in route')).toBeInTheDocument();
  });
});
