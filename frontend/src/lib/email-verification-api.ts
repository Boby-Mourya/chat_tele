import { ApiError, AUTH_SESSION_EVENT } from '@/lib/api';
import { readStorage, writeStorage } from '@/lib/storage';
import type { Session } from '@/types';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export interface EmailVerificationResult {
  verified: boolean;
  alreadyVerified: boolean;
}

function session(): Session | null {
  return readStorage<Session | null>(SESSION_KEY, null);
}

function persistSession(value: Session): Session {
  const safe = { ...value };
  delete safe.refreshToken;
  writeStorage(SESSION_KEY, safe);
  window.dispatchEvent(new Event(AUTH_SESSION_EVENT));
  return safe;
}

async function errorFrom(response: Response, fallback: string): Promise<ApiError> {
  let payload: unknown;
  try { payload = await response.json() as unknown; } catch { payload = undefined; }
  if (payload && typeof payload === 'object') {
    const apiError = (payload as { error?: unknown }).error;
    if (apiError && typeof apiError === 'object') {
      const message = (apiError as { message?: unknown }).message;
      if (typeof message === 'string' && message.trim()) return new ApiError(message, response.status, payload);
    }
  }
  return new ApiError(fallback, response.status, payload);
}

export const emailVerificationApi = {
  session,

  async resend(email: string): Promise<void> {
    const response = await fetch(`${API_URL}/auth/email-verification/resend`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase() }),
    });
    if (!response.ok) throw await errorFrom(response, 'Unable to request a verification email.');
  },

  async verify(token: string): Promise<EmailVerificationResult> {
    const response = await fetch(`${API_URL}/auth/email-verification/verify`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    if (!response.ok) throw await errorFrom(response, 'Verification link is invalid or expired.');
    return response.json() as Promise<EmailVerificationResult>;
  },

  async refreshSession(): Promise<Session> {
    const response = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw await errorFrom(response, 'Sign in again to continue.');
    return persistSession(await response.json() as Session);
  },
};
