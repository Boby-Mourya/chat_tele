import { afterEach, describe, expect, it, vi } from 'vitest';
import { emailVerificationApi } from '@/lib/email-verification-api';

const verifiedSession = {
  accessToken: 'rotated-access-token',
  refreshToken: 'server-refresh-token',
  expiresAt: '2026-09-11T00:00:00.000Z',
  user: {
    id: 'user-verify',
    name: 'Verification Owner',
    email: 'owner@example.com',
    role: 'owner' as const,
    emailVerified: true,
  },
};

describe('emailVerificationApi', () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('verifies a token and refreshes the browser session without persisting the refresh token', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ verified: true, alreadyVerified: false }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(verifiedSession), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }));
    vi.stubGlobal('fetch', fetchMock);

    const verification = await emailVerificationApi.verify('secure-verification-token-value');
    const session = await emailVerificationApi.refreshSession();

    expect(verification).toEqual({ verified: true, alreadyVerified: false });
    expect(session.user.emailVerified).toBe(true);
    expect(session.refreshToken).toBeUndefined();
    const persisted = JSON.parse(localStorage.getItem('northstar.session') ?? '{}') as {
      refreshToken?: string;
      user?: { emailVerified?: boolean };
    };
    expect(persisted.refreshToken).toBeUndefined();
    expect(persisted.user?.emailVerified).toBe(true);
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/auth/email-verification/verify', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/auth/refresh', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
    }));
  });

  it('normalizes the email sent to the resend endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ accepted: true }), {
      status: 202,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await emailVerificationApi.resend('  Owner@Example.COM  ');

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ email: 'owner@example.com' });
  });

  it('surfaces the backend verification error message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { message: 'Verification link is invalid or expired' },
    }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    })));

    await expect(emailVerificationApi.verify('expired-verification-token-value')).rejects.toThrow(
      'Verification link is invalid or expired',
    );
  });
});
