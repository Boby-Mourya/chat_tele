import { readStorage, writeStorage } from '@/lib/storage';

export type DnsStatus = 'not-configured' | 'pending' | 'verified';
export type WorkspaceRole = 'workspace_admin' | 'manager' | 'operator' | 'analyst' | 'viewer';
export interface WorkspacePreferences { timezone: string; defaultLanguage: string; dateFormat: 'DD/MM/YYYY' | 'MM/DD/YYYY' | 'YYYY-MM-DD' }
export interface WorkspaceSecurityPolicy { sensitiveDataMasking: boolean; securityContact: string | null }
export interface WhiteLabelSettings {
  companyName: string; logoDataUrl: string; faviconDataUrl: string; appIconDataUrl: string;
  primaryColor: string; secondaryColor: string; supportEmail: string | null; supportUrl: string;
  browserTitle: string; customDomain: string; dnsStatus: DnsStatus; brandedLogin: boolean;
  brandedDashboard: boolean; brandedWidget: boolean; brandedEmails: boolean; removePlatformBranding: boolean;
}
export interface WorkspaceSettings {
  id: string; tenantId?: string; tenantName?: string; name: string; slug: string;
  status?: 'active' | 'archived'; role?: WorkspaceRole; permissions?: string[];
  plan: string; memberCount: number; preferences: WorkspacePreferences; whiteLabel: WhiteLabelSettings;
  security: WorkspaceSecurityPolicy;
  brandingPublished?: boolean; brandingWarnings?: string[]; educationCreateUpsellLeads?: boolean;
}
export interface WorkspaceTeamMember { id: string; name: string; email: string; role: WorkspaceRole; tenantRole: 'owner' | 'admin' | 'billing_admin' | 'security_admin' | 'member' | 'analyst'; status: 'active' }
export interface WorkspaceTeamInvitation { id: string; email: string; role: WorkspaceRole; status: 'invited'; expiresAt: string; createdAt: string }
export interface WorkspaceTeam { members: WorkspaceTeamMember[]; invitations: WorkspaceTeamInvitation[] }
export type WorkspacePatch = Partial<Pick<WorkspaceSettings, 'name' | 'slug' | 'preferences' | 'whiteLabel' | 'educationCreateUpsellLeads' | 'security'>>;
export interface WorkspaceCreate { name: string; slug: string; timezone?: string; defaultLanguage?: string; dateFormat?: WorkspacePreferences['dateFormat'] }
const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true';
const STORAGE_KEY = 'northstar.workspace';
const SESSION_KEY = 'northstar.session';
export const WORKSPACE_CHANGED_EVENT = 'northstar:active-workspace-changed';
export class WorkspaceRequestError extends Error {
  constructor(message: string, readonly status: number) { super(message); this.name = 'WorkspaceRequestError'; }
}
const defaults: WorkspaceSettings = {
  id: 'workspace-demo', name: 'Northstar Workspace', slug: 'northstar', plan: 'business', memberCount: 1,
  educationCreateUpsellLeads: false, brandingPublished: false,
  preferences: { timezone: 'Asia/Calcutta', defaultLanguage: 'English', dateFormat: 'DD/MM/YYYY' },
  security: { sensitiveDataMasking: true, securityContact: null },
  whiteLabel: { companyName: 'Northstar AI', logoDataUrl: '', faviconDataUrl: '', appIconDataUrl: '',
    primaryColor: '#0c0b0b', secondaryColor: '#6b6b70', supportEmail: null, supportUrl: '',
    browserTitle: 'Northstar AI', customDomain: '', dnsStatus: 'not-configured', brandedLogin: false,
    brandedDashboard: true, brandedWidget: false, brandedEmails: false, removePlatformBranding: false },
};
function localWorkspace(): WorkspaceSettings {
  const saved = readStorage<Partial<WorkspaceSettings>>(STORAGE_KEY, {});
  return { ...defaults, ...saved, preferences: { ...defaults.preferences, ...saved.preferences }, security: { ...defaults.security, ...saved.security }, whiteLabel: { ...defaults.whiteLabel, ...saved.whiteLabel } };
}
function storedSession() { return readStorage<{ accessToken?: string; user?: { id?: string; role?: string; emailVerified?: boolean } } | null>(SESSION_KEY, null); }
export function workspaceSessionScope(): string {
  const current = storedSession();
  if (!current?.accessToken) return 'signed-out';
  // The untrusted claim is a cache namespace only. The server authenticates every request.
  try {
    const claims = JSON.parse(atob(current.accessToken.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/'))) as { tid?: unknown };
    return `${current.user?.id ?? ''}:${typeof claims.tid === 'string' ? claims.tid : 'unknown'}`;
  } catch { return `${current.user?.id ?? ''}:demo`; }
}
/** A cache/UI identity, never authorization. Ordinary token rotation keeps this key
 * stable; organization, role, credential-version and verification changes do not.
 */
export function workspacePresentationKey(): string {
  const current = storedSession();
  if (!current?.accessToken) return 'signed-out';
  let credentialVersion = 0;
  try {
    const claims = JSON.parse(atob(current.accessToken.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/'))) as { cv?: unknown };
    if (typeof claims.cv === 'number' && Number.isSafeInteger(claims.cv) && claims.cv >= 0) credentialVersion = claims.cv;
  } catch { /* Malformed tokens still have to pass server authentication. */ }
  return JSON.stringify([workspaceSessionScope(), current.user?.role ?? '', credentialVersion, current.user?.emailVerified !== false]);
}

export function retryableWorkspaceRead(error: unknown): boolean {
  return error instanceof WorkspaceRequestError ? error.status >= 500 : error instanceof TypeError;
}

let memorySelection: { scope: string; id: string } | null = null;
export function activeWorkspaceId(): string | null {
  const scope = workspaceSessionScope();
  try { return sessionStorage.getItem(`northstar.active-workspace:${scope}`) ?? (memorySelection?.scope === scope ? memorySelection.id : null); } catch { return memorySelection?.scope === scope ? memorySelection.id : null; }
}
export function persistActiveWorkspace(workspaceId: string): void {
  memorySelection = { scope: workspaceSessionScope(), id: workspaceId };
  try { sessionStorage.setItem(`northstar.active-workspace:${workspaceSessionScope()}`, workspaceId); } catch { /* A storage-disabled browser can still use its in-memory provider. */ }
  window.dispatchEvent(new CustomEvent(WORKSPACE_CHANGED_EVENT, { detail: workspaceId }));
}
export function clearActiveWorkspaceSelection(): void {
  memorySelection = null;
  try { sessionStorage.removeItem(`northstar.active-workspace:${workspaceSessionScope()}`); } catch { /* Memory state is still cleared. */ }
  window.dispatchEvent(new CustomEvent(WORKSPACE_CHANGED_EVENT, { detail: null }));
}
async function remote<T>(path: string, method: 'GET' | 'POST' | 'PATCH', body?: unknown, includeWorkspace = true, signal?: AbortSignal): Promise<T> {
  const identity = workspacePresentationKey();
  const workspaceId = activeWorkspaceId();
  const checkContext = () => {
    if (signal?.aborted || identity !== workspacePresentationKey() || (includeWorkspace && workspaceId !== activeWorkspaceId())) {
      throw new DOMException('Workspace context changed', 'AbortError');
    }
  };
  // Retry a read once only when another request has already refreshed the same
  // identity. Never obtain a new session here or replay a write of uncertain outcome.
  for (let attempt = 0; attempt < 2; attempt += 1) {
    checkContext();
    const token = storedSession()?.accessToken;
    const response = await fetch(`${API_URL}${path}`, {
      method, signal, cache: 'no-store', credentials: 'include',
      headers: { Accept: 'application/json', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(includeWorkspace && workspaceId ? { 'X-Workspace-ID': workspaceId } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload: unknown = await response.json().catch(() => undefined);
    checkContext();
    if (token !== storedSession()?.accessToken) {
      if (method === 'GET' && attempt === 0) continue;
      throw new DOMException('Session changed during the request. Reload to verify its outcome before retrying.', 'AbortError');
    }
    if (!response.ok) {
      const value = payload as { error?: { message?: string }; detail?: unknown } | undefined;
      throw new WorkspaceRequestError(value?.error?.message ?? (typeof value?.detail === 'string' ? value.detail : `Workspace request failed (${response.status})`), response.status);
    }
    if (payload === undefined) throw new WorkspaceRequestError('The server returned an invalid workspace response', 502);
    return payload as T;
  }
  throw new DOMException('Session changed repeatedly; reload your workspace', 'AbortError');
}
function demoFallback(error: unknown): boolean {
  if (!DEMO_MODE || (error instanceof DOMException && error.name === 'AbortError')) return false;
  return !(error instanceof WorkspaceRequestError && [400, 401, 403, 409, 422, 428, 429].includes(error.status));
}
export const workspaceApi = {
  async get(): Promise<WorkspaceSettings> {
    try { return await remote<WorkspaceSettings>('/workspace', 'GET'); }
    catch (error) { if (demoFallback(error)) return localWorkspace(); throw error; }
  },
  async update(patch: WorkspacePatch): Promise<WorkspaceSettings> {
    // DNS verification and hostname provisioning are not client-editable branding fields.
    const body: Record<string, unknown> = { ...patch };
    if (patch.whiteLabel) {
      const writable: Partial<WhiteLabelSettings> = { ...patch.whiteLabel };
      delete writable.dnsStatus; delete writable.customDomain; body.whiteLabel = writable;
    }
    try {
      const value = await remote<WorkspaceSettings>('/workspace', 'PATCH', body);
      window.dispatchEvent(new CustomEvent('northstar:workspace-changed', { detail: value }));
      return value;
    } catch (error) {
      if (!demoFallback(error)) throw error;
      const current = localWorkspace();
      const value = { ...current, ...patch, preferences: { ...current.preferences, ...patch.preferences }, security: { ...current.security, ...patch.security }, whiteLabel: { ...current.whiteLabel, ...patch.whiteLabel } };
      writeStorage(STORAGE_KEY, value);
      window.dispatchEvent(new CustomEvent('northstar:workspace-changed', { detail: value }));
      return value;
    }
  },
  async list(signal?: AbortSignal): Promise<WorkspaceSettings[]> {
    try { return await remote<WorkspaceSettings[]>('/workspaces', 'GET', undefined, false, signal); }
    catch (error) { if (demoFallback(error)) return [localWorkspace()]; throw error; }
  },
  async create(input: WorkspaceCreate): Promise<WorkspaceSettings> {
    return remote<WorkspaceSettings>('/workspaces', 'POST', input, false);
  },
  async getTeam(): Promise<WorkspaceTeam> {
    try { return await remote<WorkspaceTeam>('/workspace/team', 'GET'); }
    catch (error) { if (demoFallback(error)) return { members: [], invitations: [] }; throw error; }
  },
};
export const workspaceDefaults = defaults;
