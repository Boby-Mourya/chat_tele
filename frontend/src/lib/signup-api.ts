import { ApiError, AUTH_SESSION_EVENT } from '@/lib/api';
import { writeStorage } from '@/lib/storage';
import { persistActiveWorkspace, workspaceDefaults } from '@/lib/workspace-api';
import type { Session } from '@/types';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';
const SESSION_KEY = 'northstar.session';
const WORKSPACE_KEY = 'northstar.workspace';

export interface SignupInput {
  name: string;
  email: string;
  password: string;
  organizationName?: string;
  workspaceInvitationToken?: string;
  termsAccepted: true;
  privacyAccepted: true;
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
  return `Account creation failed (${status})`;
}

function persistSignupSession(value: Session): Session {
  const safe = { ...value };
  delete safe.refreshToken;
  writeStorage(SESSION_KEY, safe);
  window.dispatchEvent(new Event(AUTH_SESSION_EVENT));
  return safe;
}

async function remoteSignup(input: SignupInput): Promise<Session> {
  const response = await fetch(`${API_URL}/auth/signup`, {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    let payload: unknown;
    try { payload = await response.json() as unknown; } catch { payload = undefined; }
    throw new ApiError(responseMessage(payload, response.status), response.status, payload);
  }
  return response.json() as Promise<Session>;
}

async function demoSignup(input: SignupInput): Promise<Session> {
  const organizationName = input.organizationName?.trim().replace(/\s+/g, ' ');
  if (!input.name.trim() || !organizationName || !input.email.trim()) {
    throw new ApiError('Name, organization and business email are required.', 422);
  }
  if (input.password.length < 12) throw new ApiError('Password must be at least 12 characters.', 422);
  const userName = input.name.trim().replace(/\s+/g, ' ');
  const workspaceId = `workspace-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;
  const tenantId = `tenant-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;
  writeStorage(WORKSPACE_KEY, {
    ...workspaceDefaults,
    id: workspaceId,
    tenantId,
    tenantName: organizationName,
    name: organizationName,
    slug: 'default',
    role: 'workspace_admin' as const,
    plan: 'starter',
    whiteLabel: { ...workspaceDefaults.whiteLabel, companyName: organizationName },
  });
  persistActiveWorkspace(workspaceId);
  return {
    accessToken: `demo-signup.${btoa(input.email.toLowerCase())}.token`,
    expiresAt: new Date(Date.now() + 86_400_000).toISOString(),
    user: {
      id: `user-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
      name: userName,
      email: input.email.trim().toLowerCase(),
      role: 'owner',
      emailVerified: true,
    },
  };
}

export const signupApi = {
  async signup(input: SignupInput): Promise<Session> {
    let value: Session;
    try {
      value = await remoteSignup(input);
    } catch (error) {
      if (input.workspaceInvitationToken) throw error;
      if (error instanceof ApiError && [400, 401, 403, 409, 422, 429].includes(error.status)) throw error;
      if (!DEMO_MODE) throw error;
      value = await demoSignup(input);
    }
    return persistSignupSession(value);
  },
};
