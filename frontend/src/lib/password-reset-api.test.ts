import { afterEach, describe, expect, it, vi } from 'vitest';
import { AUTH_SESSION_EVENT } from '@/lib/api';
import { passwordResetApi } from '@/lib/password-reset-api';

describe('passwordResetApi', () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('normalizes email and requests a recovery link without credentials in storage', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ accepted: true }), {
      status: 202,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await passwordResetApi.request('  Owner@Example.COM  ');

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/password-reset/request', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
    }));
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ email: 'owner@example.com' });
  });

  it('submits the token, clears a stale browser session, and emits the auth-session event', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ reset: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'stale-access-token' }));
    const changed = vi.fn();
    window.addEventListener(AUTH_SESSION_EVENT, changed, { once: true });

    const result = await passwordResetApi.confirm(
      'secure-reset-token-value',
      'Replacement-Password-2026!',
      'Replacement-Password-2026!',
    );

    expect(result).toEqual({ reset: true });
    expect(localStorage.getItem('northstar.session')).toBeNull();
    expect(changed).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      token: 'secure-reset-token-value',
      password: 'Replacement-Password-2026!',
      confirmPassword: 'Replacement-Password-2026!',
    });
  });

  it('does not clear a browser session when confirmation fails', async () => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'still-current' }));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { message: 'Password reset link is invalid or expired' },
    }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    })));

    await expect(passwordResetApi.confirm(
      'expired-reset-token-value',
      'Replacement-Password-2026!',
      'Replacement-Password-2026!',
    )).rejects.toThrow('Password reset link is invalid or expired');
    expect(localStorage.getItem('northstar.session')).not.toBeNull();
  });
});
