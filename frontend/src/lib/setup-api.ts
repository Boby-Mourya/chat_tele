import { api } from '@/lib/api';
import { activeWorkspaceId } from '@/lib/workspace-api';

export interface OrganizationProfile {
  organizationType: 'institution' | 'business'; displayName: string; organizationSubtype: string;
  category: string; country: string; city: string; timezone: string; preferredLanguage: string;
  dateFormat: 'DD/MM/YYYY' | 'MM/DD/YYYY' | 'YYYY-MM-DD'; contactName: string; contactEmail: string;
  phone: string; website: string | null; description: string; teachingFocus: string;
  programCategories: string[]; learnerVolumeBand: string; teamSizeBand: string;
  useCases: Array<'education' | 'support' | 'lead_generation'>; workspaceName: string; workspaceSlug: string;
}
export type BrandingChoice = 'unseen' | 'customize' | 'keep_default' | 'deferred';
export interface OnboardingState {
  revision: number; profile?: Partial<OrganizationProfile>; draft?: Partial<OrganizationProfile>;
  profileComplete: boolean; profileRequired: boolean; brandingChoice: BrandingChoice;
  choiceAt: string | null; catalogGrants: string[]; onboardingVersion: number;
}
export interface StarterItem { id: string; version: number; title: string; kind: string; sample: boolean; content: string }
export interface SetupBootstrap {
  organization: { id: string; name: string; role: string }; workspaceId: string | null;
  capabilities: { organization: string[]; workspace: string[] }; onboarding: OnboardingState;
  starterContent: StarterItem[];
  plan: { name: string; status: string; workspaceLimit: number | null; agentLimit: number | null;
    memberLimit: number | null; monthlyConversationLimit: number | null; monthlyTokenLimit: number | null;
    storageLimitBytes: number | null; dashboardCustomize: boolean; customDomain: boolean;
    brandedEmail: boolean; removePlatformMark: boolean };
  usage: { workspaces: number; agents: number; members: number; pendingSeats: number;
    conversationsMonthly: number; tokensMonthly: number; storageBytes: number } | null;
  brand: Record<string, unknown>;
}
export const emptyProfile: OrganizationProfile = {
  organizationType: 'institution', displayName: '', organizationSubtype: '', category: '', country: '', city: '',
  timezone: 'Asia/Kolkata', preferredLanguage: 'English', dateFormat: 'DD/MM/YYYY', contactName: '', contactEmail: '',
  phone: '', website: null, description: '', teachingFocus: '', programCategories: [], learnerVolumeBand: '',
  teamSizeBand: '', useCases: [], workspaceName: '', workspaceSlug: 'default',
};
const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
export class SetupRequestError extends Error {
  constructor(message: string, readonly status: number) { super(message); this.name = 'SetupRequestError'; }
}
function messageFor(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const value = payload as { detail?: unknown; error?: { message?: unknown } };
    if (typeof value.error?.message === 'string') return value.error.message;
    if (typeof value.detail === 'string') return value.detail;
    if (Array.isArray(value.detail)) return value.detail.map((entry: unknown) => entry && typeof entry === 'object' && typeof (entry as { msg?: unknown }).msg === 'string' ? (entry as { msg: string }).msg : 'Invalid field').join('; ');
  }
  return status === 401 ? 'Your session expired. Sign in again; your saved progress is retained.' : `Request failed (${status})`;
}

/** Captures request scope once. A response from an old identity/workspace cannot update this screen. */
async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal, workspace = true): Promise<T> {
  const identity = api.auth.session();
  const workspaceId = activeWorkspaceId();
  if (!identity) throw new SetupRequestError('Sign in to continue', 401);
  const response = await fetch(`${API_URL}${path}`, {
    method, signal, credentials: 'include',
    headers: { Accept: 'application/json', Authorization: `Bearer ${identity.accessToken}`,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(workspace && workspaceId ? { 'X-Workspace-ID': workspaceId } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload: unknown = response.status === 204 ? undefined : await response.json().catch(() => undefined);
  const current = api.auth.session();
  if (signal?.aborted || current?.accessToken !== identity.accessToken || (workspace && workspaceId !== activeWorkspaceId())) {
    throw new DOMException('The selected account or workspace changed', 'AbortError');
  }
  if (!response.ok) throw new SetupRequestError(messageFor(payload, response.status), response.status);
  return payload as T;
}
export const setupApi = {
  bootstrap: (signal?: AbortSignal) => request<SetupBootstrap>('/bootstrap', 'GET', undefined, signal),
  profile: (profile: OrganizationProfile, expectedRevision: number, complete: boolean) =>
    request<OnboardingState>('/organization/profile', 'PATCH', { profile, expectedRevision, complete }, undefined, false),
  chooseBranding: (choice: Exclude<BrandingChoice, 'unseen'>, expectedRevision: number) =>
    request<OnboardingState>('/onboarding', 'PATCH', { choice, expectedRevision }),
};
