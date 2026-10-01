import type { Session } from '@/types';
import { clearActiveWorkspaceSelection } from '@/lib/workspace-api';

export interface OrganizationSummary { id: string; name: string; role: string; selected: boolean }
export interface OrganizationList { organizations: OrganizationSummary[]; nextCursor: string | null }
export interface OrganizationSession extends Session { organizationId: string; organizationName: string }

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';
const SESSION_EVENT = 'northstar:session-changed';
let selectionPending = false;

export class OrganizationRequestError extends Error {
  constructor(message: string, readonly status: number) { super(message); this.name = 'OrganizationRequestError'; }
}
function token(): string | null {
  try { return (JSON.parse(localStorage.getItem(SESSION_KEY) ?? 'null') as Session | null)?.accessToken ?? null; }
  catch { return null; }
}
function checkToken(expected: string): void {
  if (token() !== expected) throw new OrganizationRequestError('The signed-in account changed. Reload organizations.', 409);
}
function invalidateAmbiguousSession(): void {
  // A response may already have changed the HttpOnly cookie. Do not retain a
  // mismatched access token or silently replace a newer sign-in in another tab.
  try { clearActiveWorkspaceSelection(); localStorage.removeItem(SESSION_KEY); } finally { window.dispatchEvent(new Event(SESSION_EVENT)); }
}
function errorMessage(payload: unknown, status: number): string {
  const value = payload as { detail?: unknown; error?: { message?: unknown } } | null;
  const message = value?.error?.message ?? value?.detail;
  return typeof message === 'string' ? message : status === 401
    ? 'Your session expired. Sign in again to select an organization.'
    : `Organization request failed (${status})`;
}
function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function validSession(value: unknown, organizationId: string, userId: string): value is OrganizationSession {
  return object(value) && value.organizationId === organizationId && typeof value.organizationName === 'string'
    && typeof value.accessToken === 'string' && value.accessToken.length > 0
    && typeof value.expiresAt === 'string' && Number.isFinite(Date.parse(value.expiresAt))
    && object(value.user) && value.user.id === userId && typeof value.user.name === 'string'
    && typeof value.user.email === 'string' && value.user.emailVerified === true
    && typeof value.user.role === 'string' && ['owner', 'admin', 'billing_admin', 'security_admin', 'member', 'analyst'].includes(value.user.role);
}

async function list(after?: string | null, signal?: AbortSignal): Promise<OrganizationList> {
  const expected = token();
  if (!expected) throw new OrganizationRequestError('Sign in to view your organizations.', 401);
  const response = await fetch(`${API_URL}/me/organizations${after ? `?after=${encodeURIComponent(after)}` : ''}`, {
    credentials: 'include', cache: 'no-store', signal,
    headers: { Accept: 'application/json', Authorization: `Bearer ${expected}` },
  });
  checkToken(expected);
  const payload: unknown = await response.json().catch(() => null);
  checkToken(expected);
  if (!response.ok) throw new OrganizationRequestError(errorMessage(payload, response.status), response.status);
  if (!object(payload) || !Array.isArray(payload.organizations)
    || !(payload.nextCursor === null || typeof payload.nextCursor === 'string')
    || !payload.organizations.every((item: unknown) => object(item) && typeof item.id === 'string'
      && typeof item.name === 'string' && typeof item.role === 'string' && typeof item.selected === 'boolean')) {
    throw new OrganizationRequestError('The organization service returned an invalid response.', 502);
  }
  return payload as unknown as OrganizationList;
}

async function select(organizationId: string): Promise<OrganizationSession> {
  if (selectionPending) throw new OrganizationRequestError('An organization change is already in progress.', 409);
  const expected = token();
  if (!expected) throw new OrganizationRequestError('Sign in to select an organization.', 401);
  const userId = (JSON.parse(localStorage.getItem(SESSION_KEY) ?? 'null') as Session | null)?.user?.id;
  if (!userId) throw new OrganizationRequestError('Sign in again to confirm your account identity.', 401);
  selectionPending = true;
  const perform = async () => {
    checkToken(expected);
    let response: Response;
    try {
      response = await fetch(`${API_URL}/auth/select-organization`, {
        method: 'POST', credentials: 'include', cache: 'no-store',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: `Bearer ${expected}` },
        body: JSON.stringify({ organizationId }),
      });
    } catch {
      invalidateAmbiguousSession();
      throw new OrganizationRequestError('The organization change could not be confirmed. Sign in again; it was not retried.', 503);
    }
    const payload: unknown = await response.json().catch(() => null);
    if (token() !== expected) {
      if (response.ok) invalidateAmbiguousSession();
      throw new OrganizationRequestError('The account changed during selection. Sign in again to confirm the active organization.', 409);
    }
    if (!response.ok) throw new OrganizationRequestError(errorMessage(payload, response.status), response.status);
    if (!validSession(payload, organizationId, userId)) {
      invalidateAmbiguousSession();
      throw new OrganizationRequestError('The session response could not be verified. Sign in again.', 502);
    }
    const safe = { ...payload };
    delete safe.refreshToken;
    try {
      // Do not copy the old workspace or cached branding into the selected org.
      localStorage.removeItem('northstar.active-workspace-id');
      localStorage.removeItem('northstar.workspace');
      localStorage.setItem(SESSION_KEY, JSON.stringify(safe));
      if (token() !== safe.accessToken) throw new Error('Session persistence failed');
      clearActiveWorkspaceSelection();
    } catch {
      invalidateAmbiguousSession();
      throw new OrganizationRequestError('Browser storage could not save the new account session. Sign in again.', 503);
    }
    window.dispatchEvent(new Event(SESSION_EVENT));
    return safe;
  };
  try {
    // Prevent two cooperating tabs selecting organizations simultaneously. The
    // server-side one-time refresh proof still controls uncooperative clients.
    return typeof navigator !== 'undefined' && navigator.locks
      ? await navigator.locks.request('northstar:organization-selection', perform) : await perform();
  } finally { selectionPending = false; }
}

export const organizationApi = { list, select };
