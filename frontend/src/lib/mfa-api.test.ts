import { afterEach, describe, expect, it, vi } from 'vitest';
import { AUTH_SESSION_EVENT } from '@/lib/api';
import { isMFAChallenge, mfaApi } from '@/lib/mfa-api';
import type { Session } from '@/types';

const SESSION_KEY = 'northstar.session';

function session(accessToken: string): Session {
  return {
    accessToken,
    refreshToken: `refresh-${accessToken}`,
    expiresAt: new Date(Date.now() + 60_000).toISOString(),
    user: {
      id: 'user-1',
      name: 'MFA Owner',
      email: 'owner@example.com',
      role: 'owner',
      emailVerified: true,
    },
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('mfaApi', () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('returns an MFA challenge without persisting it as an authenticated session', async () => {
    const challenge = {
      mfaRequired: true as const,
      challengeToken: 'short-lived-mfa-challenge',
      expiresAt: new Date(Date.now() + 300_000).toISOString(),
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(challenge));
    vi.stubGlobal('fetch', fetchMock);

    const result = await mfaApi.login('  Owner@Example.COM  ', 'Password-2026!');

    expect(isMFAChallenge(result)).toBe(true);
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      email: 'owner@example.com',
      password: 'Password-2026!',
    });
  });

  it('persists only the completed MFA session and emits the auth-session event', async () => {
    const complete = session('mfa-access-token');
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(complete));
    vi.stubGlobal('fetch', fetchMock);
    const changed = vi.fn();
    window.addEventListener(AUTH_SESSION_EVENT, changed, { once: true });

    const result = await mfaApi.verifyChallenge('challenge-token', { recoveryCode: 'ABCD-EFGH-JKLM' });

    expect(result.accessToken).toBe('mfa-access-token');
    expect(result.refreshToken).toBeUndefined();
    expect(JSON.parse(localStorage.getItem(SESSION_KEY) ?? '{}').accessToken).toBe('mfa-access-token');
    expect(JSON.parse(localStorage.getItem(SESSION_KEY) ?? '{}').refreshToken).toBeUndefined();
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it('refreshes an expired access session before retrying an authenticated MFA request', async () => {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session('expired-access')));
    const rotated = session('rotated-access');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ error: { message: 'expired' } }, 401))
      .mockResolvedValueOnce(jsonResponse(rotated))
      .mockResolvedValueOnce(jsonResponse({
        configured: true,
        enabled: true,
        confirmedAt: '2026-09-10T10:00:00Z',
        unusedRecoveryCodes: 8,
      }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await mfaApi.status();

    expect(result.enabled).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/v1/auth/refresh');
    const retryInit = fetchMock.mock.calls[2]?.[1] as RequestInit;
    expect((retryInit.headers as Record<string, string>).Authorization).toBe('Bearer rotated-access');
    expect(JSON.parse(localStorage.getItem(SESSION_KEY) ?? '{}').accessToken).toBe('rotated-access');
  });

  it('clears the browser session when the HttpOnly-cookie refresh can no longer restore it', async () => {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session('expired-access')));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ error: { message: 'expired' } }, 401))
      .mockResolvedValueOnce(jsonResponse({ error: { message: 'refresh rejected' } }, 401));
    vi.stubGlobal('fetch', fetchMock);

    await expect(mfaApi.status()).rejects.toThrow('refresh rejected');
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
  });
});
