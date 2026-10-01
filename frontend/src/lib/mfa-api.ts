import { ApiError, AUTH_SESSION_EVENT, apiConfig } from '@/lib/api';
import { readStorage, writeStorage } from '@/lib/storage';
import type { Session } from '@/types';

const SESSION_KEY = 'northstar.session';

export interface MFAChallenge {
  mfaRequired: true;
  challengeToken: string;
  expiresAt: string;
}

export type LoginResult = Session | MFAChallenge;

export interface MFAStatus {
  configured: boolean;
  enabled: boolean;
  confirmedAt?: string | null;
  unusedRecoveryCodes: number;
}

export interface MFASetupMaterial {
  secret: string;
  otpauthUri: string;
  recoveryCodes: string[];
}

export interface MFAFactor {
  code?: string;
  recoveryCode?: string;
}

export interface MFAProtectedAction extends MFAFactor {
  currentPassword: string;
}

export function isMFAChallenge(value: LoginResult): value is MFAChallenge {
  return 'mfaRequired' in value && value.mfaRequired === true;
}

function responseMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const error = (payload as { error?: unknown }).error;
    if (error && typeof error === 'object') {
      const message = (error as { message?: unknown }).message;
      if (typeof message === 'string' && message.trim()) return message;
    }
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
  }
  return `MFA request failed (${status})`;
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let payload: unknown;
    try { payload = await response.json() as unknown; } catch { payload = undefined; }
    throw new ApiError(responseMessage(payload, response.status), response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function persistSession(value: Session): Session {
  const safe = { ...value };
  delete safe.refreshToken;
  writeStorage(SESSION_KEY, safe);
  window.dispatchEvent(new Event(AUTH_SESSION_EVENT));
  return safe;
}

function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
  window.dispatchEvent(new Event(AUTH_SESSION_EVENT));
}

function currentSession(): Session {
  const value = readStorage<Session | null>(SESSION_KEY, null);
  if (!value?.accessToken) throw new ApiError('Authentication required', 401);
  return value;
}

async function refreshFromCookie(): Promise<Session> {
  const response = await fetch(`${apiConfig.baseUrl}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  try {
    return persistSession(await parse<Session>(response));
  } catch (error) {
    clearSession();
    throw error;
  }
}

async function authenticated<T>(path: string, init?: RequestInit): Promise<T> {
  let active = currentSession();
  const execute = () => fetch(`${apiConfig.baseUrl}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      Authorization: `Bearer ${active.accessToken}`,
      ...(init?.headers ?? {}),
    },
  });
  let response = await execute();
  if (response.status === 401) {
    active = await refreshFromCookie();
    response = await execute();
  }
  return parse<T>(response);
}

async function remoteLogin(email: string, password: string): Promise<LoginResult> {
  const response = await fetch(`${apiConfig.baseUrl}/auth/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
  });
  return parse<LoginResult>(response);
}

function demoLogin(email: string, password: string): Session {
  if (!email.trim() || !password) throw new ApiError('Email and password are required.', 400);
  return {
    accessToken: `demo.${btoa(email)}.token`,
    expiresAt: new Date(Date.now() + 86_400_000).toISOString(),
    user: {
      id: 'user-demo',
      name: email.split('@')[0]?.replace(/[._-]/g, ' ') || 'Northstar User',
      email: email.trim().toLowerCase(),
      role: 'owner',
      emailVerified: true,
    },
  };
}

function canUseDemoFallback(error: unknown): boolean {
  return apiConfig.demoMode && (!(error instanceof ApiError) || error.status === 404 || error.status >= 500);
}

export const mfaApi = {
  async login(email: string, password: string): Promise<LoginResult> {
    try {
      const result = await remoteLogin(email, password);
      return isMFAChallenge(result) ? result : persistSession(result);
    } catch (error) {
      if (error instanceof ApiError && [400, 401, 403, 409, 422, 429].includes(error.status)) throw error;
      if (!apiConfig.demoMode) throw error;
      return persistSession(demoLogin(email, password));
    }
  },

  async verifyChallenge(challengeToken: string, factor: MFAFactor): Promise<Session> {
    const response = await fetch(`${apiConfig.baseUrl}/auth/mfa/verify`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ challengeToken, ...factor }),
    });
    return persistSession(await parse<Session>(response));
  },

  async status(): Promise<MFAStatus> {
    try {
      return await authenticated<MFAStatus>('/auth/mfa/status');
    } catch (error) {
      if (canUseDemoFallback(error)) return { configured: false, enabled: false, unusedRecoveryCodes: 0 };
      throw error;
    }
  },

  async setup(currentPassword: string): Promise<MFASetupMaterial> {
    try {
      return await authenticated<MFASetupMaterial>('/auth/mfa/setup', {
        method: 'POST',
        body: JSON.stringify({ currentPassword }),
      });
    } catch (error) {
      if (canUseDemoFallback(error)) {
        throw new ApiError('MFA setup requires a connected Northstar API.', 503, error);
      }
      throw error;
    }
  },

  async confirm(code: string): Promise<Session> {
    return persistSession(await authenticated<Session>('/auth/mfa/confirm', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }));
  },

  regenerateRecoveryCodes: (input: MFAProtectedAction) => authenticated<{ recoveryCodes: string[] }>('/auth/mfa/recovery-codes', {
    method: 'POST',
    body: JSON.stringify(input),
  }),

  async disable(input: MFAProtectedAction): Promise<Session> {
    return persistSession(await authenticated<Session>('/auth/mfa', {
      method: 'DELETE',
      body: JSON.stringify(input),
    }));
  },
};
