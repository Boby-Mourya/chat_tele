import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ForgotPasswordPage } from '@/pages/ForgotPasswordPage';
import { ResetPasswordPage } from '@/pages/ResetPasswordPage';

const mocks = vi.hoisted(() => ({
  request: vi.fn<(email: string) => Promise<void>>(),
  confirm: vi.fn<(token: string, password: string, confirmPassword: string) => Promise<{ reset: boolean }>>(),
}));

vi.mock('@/lib/password-reset-api', () => ({
  passwordResetApi: {
    request: mocks.request,
    confirm: mocks.confirm,
  },
}));

function renderForgot() {
  return render(
    <MemoryRouter initialEntries={['/forgot-password']}>
      <Routes>
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/login" element={<div>Sign in route</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function renderReset(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/forgot-password" element={<div>Request reset route</div>} />
        <Route path="/login" element={<div>Sign in route</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Password recovery pages', () => {
  beforeEach(() => {
    mocks.request.mockResolvedValue(undefined);
    mocks.confirm.mockResolvedValue({ reset: true });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('normalizes a forgot-password email and shows the privacy-safe confirmation', async () => {
    const user = userEvent.setup();
    renderForgot();

    await user.type(screen.getByLabelText('Work email'), 'Owner@Example.COM');
    await user.click(screen.getByRole('button', { name: 'Send reset link' }));

    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith('owner@example.com'));
    expect(screen.getByRole('status')).toHaveTextContent('Recovery request accepted');
    expect(screen.getByRole('status')).toHaveTextContent(
      'this confirmation is the same whether or not an account exists',
    );
  });

  it('keeps a fragment reset token in memory after URL cleanup and completes the reset', async () => {
    const user = userEvent.setup();
    const token = 'valid-reset-token-value-1234567890';
    renderReset(`/reset-password#token=${token}`);

    await user.type(screen.getByLabelText('New password'), 'Replacement-Password-2026!');
    await user.type(screen.getByLabelText('Confirm new password'), 'Replacement-Password-2026!');
    await user.click(screen.getByRole('button', { name: 'Reset password' }));

    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(
      token,
      'Replacement-Password-2026!',
      'Replacement-Password-2026!',
    ));
    expect(await screen.findByRole('status')).toHaveTextContent('Reset complete');
    expect(screen.getByRole('link', { name: /Continue to sign in/ })).toHaveAttribute('href', '/login');
  });

  it('keeps legacy query-string reset links compatible', async () => {
    const user = userEvent.setup();
    const token = 'legacy-reset-token-value-1234567890';
    renderReset(`/reset-password?token=${token}`);

    await user.type(screen.getByLabelText('New password'), 'Replacement-Password-2026!');
    await user.type(screen.getByLabelText('Confirm new password'), 'Replacement-Password-2026!');
    await user.click(screen.getByRole('button', { name: 'Reset password' }));

    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(
      token,
      'Replacement-Password-2026!',
      'Replacement-Password-2026!',
    ));
  });

  it('blocks mismatched passwords before calling the API', async () => {
    const user = userEvent.setup();
    renderReset('/reset-password#token=valid-reset-token-value-1234567890');

    await user.type(screen.getByLabelText('New password'), 'Replacement-Password-2026!');
    await user.type(screen.getByLabelText('Confirm new password'), 'Different-Password-2026!');
    await user.click(screen.getByRole('button', { name: 'Reset password' }));

    expect(screen.getByRole('alert')).toHaveTextContent('Passwords do not match.');
    expect(mocks.confirm).not.toHaveBeenCalled();
  });

  it('shows recovery guidance when the reset token is missing', () => {
    renderReset('/reset-password');

    expect(screen.getByRole('alert')).toHaveTextContent('This reset link cannot be used.');
    expect(screen.getByRole('link', { name: /Request a new reset link/ })).toHaveAttribute(
      'href',
      '/forgot-password',
    );
  });
});
