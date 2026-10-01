import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { MFAChallengePage } from '@/pages/MFAChallengePage';
import type { Session } from '@/types';

const mocks = vi.hoisted(() => ({
  completeMFA: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useAuth: () => ({
    session: null,
    completeMFA: mocks.completeMFA,
  }),
}));

const completeSession: Session = {
  accessToken: 'verified-access-token',
  expiresAt: new Date(Date.now() + 60_000).toISOString(),
  user: {
    id: 'user-1',
    name: 'MFA Owner',
    email: 'owner@example.com',
    role: 'owner',
    emailVerified: true,
  },
};

function renderChallenge(state?: { challengeToken?: string; from?: string }) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/mfa-challenge', state }]}> 
      <Routes>
        <Route path="/mfa-challenge" element={<MFAChallengePage />} />
        <Route path="/analytics" element={<div>Analytics destination</div>} />
        <Route path="/login" element={<div>Sign in destination</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('MFAChallengePage', () => {
  beforeEach(() => {
    mocks.completeMFA.mockResolvedValue(completeSession);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('completes an authenticator challenge and returns to the protected destination', async () => {
    const user = userEvent.setup();
    renderChallenge({ challengeToken: 'challenge-token', from: '/analytics' });

    await user.type(screen.getByLabelText('Authenticator code'), '123456');
    await user.click(screen.getByRole('button', { name: /Verify and sign in/ }));

    await waitFor(() => expect(mocks.completeMFA).toHaveBeenCalledWith(
      'challenge-token',
      { code: '123456' },
    ));
    expect(await screen.findByText('Analytics destination')).toBeInTheDocument();
  });

  it('supports a one-time recovery code without retaining the password', async () => {
    const user = userEvent.setup();
    renderChallenge({ challengeToken: 'challenge-token' });

    await user.click(screen.getByRole('button', { name: 'Use a recovery code instead' }));
    await user.type(screen.getByLabelText('Recovery code'), 'abcd-efgh-jklm');
    await user.click(screen.getByRole('button', { name: /Verify and sign in/ }));

    await waitFor(() => expect(mocks.completeMFA).toHaveBeenCalledWith(
      'challenge-token',
      { recoveryCode: 'ABCD-EFGH-JKLM' },
    ));
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });

  it('requires a fresh sign-in when the transient challenge is missing', () => {
    renderChallenge();

    expect(screen.getByRole('alert')).toHaveTextContent('sign-in challenge is missing or expired');
    expect(screen.getByRole('button', { name: /Verify and sign in/ })).toBeDisabled();
    expect(screen.getByRole('link', { name: /Back to sign in/ })).toHaveAttribute('href', '/login');
  });
});
