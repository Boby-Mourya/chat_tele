import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { LoginPage } from '@/pages/LoginPage';

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useAuth: () => ({
    session: null,
    login: mocks.login,
  }),
}));

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/login', state: { from: '/analytics' } }]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/mfa-challenge" element={<ChallengeStateProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

function ChallengeStateProbe() {
  const location = useLocation();
  const state = location.state as { challengeToken?: string; from?: string } | null;
  return <div>
    <span>Challenge route reached</span>
    <span>{state?.challengeToken}</span>
    <span>{state?.from}</span>
  </div>;
}

describe('LoginPage MFA handoff', () => {
  beforeEach(() => {
    mocks.login.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('routes an MFA-required password login to the transient challenge page', async () => {
    const user = userEvent.setup();
    mocks.login.mockResolvedValue({
      mfaRequired: true,
      challengeToken: 'short-lived-challenge-token',
      expiresAt: new Date(Date.now() + 300_000).toISOString(),
    });
    renderLogin();

    await user.type(screen.getByLabelText('Work email'), 'owner@example.com');
    await user.type(screen.getByLabelText('Password'), 'Password-2026!');
    await user.click(screen.getByRole('button', { name: /Sign in/ }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith('owner@example.com', 'Password-2026!'));
    expect(await screen.findByText('Challenge route reached')).toBeInTheDocument();
    expect(screen.getByText('short-lived-challenge-token')).toBeInTheDocument();
    expect(screen.getByText('/analytics')).toBeInTheDocument();
  });
});
