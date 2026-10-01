import { AUTH_SESSION_EVENT } from '@/lib/api';
import { readStorage, writeStorage } from '@/lib/storage';
import { activeWorkspaceId, persistActiveWorkspace, workspacePresentationKey } from '@/lib/workspace-api';
import type { Session } from '@/types';

export type WorkspaceRole = 'workspace_admin' | 'manager' | 'operator' | 'analyst' | 'viewer';
export type WorkspaceInvitationStatus = 'pending' | 'accepted' | 'declined' | 'revoked' | 'expired';
export interface WorkspaceMember {
  userId: string; name: string; email: string; role: WorkspaceRole;
  allAgentsAccess: boolean; agentIds: string[]; joinedAt: string; isSelf: boolean;
}
export interface WorkspaceMemberLifecycle {
  userId: string; status: 'active' | 'suspended'; mfaEnabled: boolean; lastActive: string | null; teamIds: string[];
}
export interface WorkspaceInvitation {
  id: string; email: string; role: WorkspaceRole; allAgentsAccess: boolean; agentIds: string[];
  status: WorkspaceInvitationStatus; expiresAt: string; lastSentAt: string | null;
  deliveryAttempts: number; deliveryState: 'not-sent' | 'sent' | 'failed'; createdAt: string;
}
export interface WorkspaceAccessInput { role: WorkspaceRole; allAgentsAccess: boolean; agentIds: string[] }
export interface WorkspaceInvitationCreate extends WorkspaceAccessInput { email: string }
export interface WorkspaceInvitationPreview {
  invitationId: string; email: string; tenantId: string; tenantName: string; tenantSlug: string;
  workspaceId: string; workspaceName: string; role: WorkspaceRole; allAgentsAccess: boolean;
  agentCount: number; expiresAt: string; existingUser: boolean;
}
export interface WorkspaceInvitationSession extends Session { tenantId: string; tenantSlug: string; workspaceId: string }
export interface WorkspaceInvitationSignupInput { token: string; name: string; password: string; termsAccepted: true; privacyAccepted: true }

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';
export class WorkspaceTeamRequestError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message); this.name = 'WorkspaceTeamRequestError';
  }
}
function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

async function request<T>(path: string, options: {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'; body?: unknown;
  authenticated?: boolean; workspaceScoped?: boolean; signal?: AbortSignal;
} = {}): Promise<T> {
  const { method = 'GET', body, authenticated = true, workspaceScoped = authenticated, signal } = options;
  const token = bearer();
  const identity = workspacePresentationKey();
  const workspaceId = activeWorkspaceId();
  const current = () => {
    if (signal?.aborted || identity !== workspacePresentationKey()
      || (method !== 'GET' && token !== bearer())
      || (workspaceScoped && workspaceId !== activeWorkspaceId())) {
      throw new DOMException('Account or workspace changed. Reload before retrying; the operation may already have completed.', 'AbortError');
    }
  };
  current();
  const response = await fetch(`${API_URL}${path}`, {
    method, signal, credentials: 'include', cache: 'no-store',
    headers: {
      Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(authenticated && token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceScoped && workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  current();
  if (response.status === 204) {
    if (method !== 'DELETE') throw new WorkspaceTeamRequestError('The team service returned an empty response', 502);
    return undefined as T;
  }
  const payload: unknown = await response.json().catch(() => null);
  current();
  if (!response.ok) {
    const error = payload as { detail?: unknown; error?: { message?: string } } | null;
    throw new WorkspaceTeamRequestError(error?.error?.message
      ?? (typeof error?.detail === 'string' ? error.detail : `Workspace team request failed (${response.status})`), response.status, payload);
  }
  if (payload === null) throw new WorkspaceTeamRequestError('The team service returned an invalid response', 502);
  return payload as T;
}

export const workspaceTeamApi = {
  listMembers: (signal?: AbortSignal) => request<WorkspaceMember[]>('/workspace/members', { signal }),
  listMemberLifecycle: (signal?: AbortSignal) => request<WorkspaceMemberLifecycle[]>('/workspace/settings/members/lifecycle', { signal }),
  listInvitations: (signal?: AbortSignal) => request<WorkspaceInvitation[]>('/workspace/invitations', { signal }),
  invite: (input: WorkspaceInvitationCreate) => request<WorkspaceInvitation>('/workspace/invitations', { method: 'POST', body: input }),
  updateMember: (userId: string, input: WorkspaceAccessInput) => request<WorkspaceMember>(
    `/workspace/members/${encodeURIComponent(userId)}`,
    { method: 'PATCH', body: input },
  ),
  suspendMember: (userId: string) => request<WorkspaceMemberLifecycle>(
    `/workspace/settings/members/${encodeURIComponent(userId)}/suspend`, { method: 'POST' },
  ),
  reactivateMember: (userId: string) => request<WorkspaceMemberLifecycle>(
    `/workspace/settings/members/${encodeURIComponent(userId)}/reactivate`, { method: 'POST' },
  ),
  transferOwnership: (userId: string) => request<WorkspaceMemberLifecycle>(
    `/workspace/settings/members/${encodeURIComponent(userId)}/transfer-ownership`, { method: 'POST' },
  ),
  removeMember: (userId: string) => request<void>(
    `/workspace/members/${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  ),
  resendInvitation: (invitationId: string) => request<WorkspaceInvitation>(
    `/workspace/invitations/${encodeURIComponent(invitationId)}/resend`, { method: 'POST' },
  ),
  revokeInvitation: (invitationId: string) => request<void>(
    `/workspace/invitations/${encodeURIComponent(invitationId)}`, { method: 'DELETE' },
  ),
};

/** A committed invitation and a delivered email are different outcomes. */
export function invitationDeliveryNotice(value: WorkspaceInvitation): { message: string; tone: 'success' | 'error' | 'info' } {
  if (value.status !== 'pending') return { message: `Invitation is ${value.status}. Reload the team to review its current state.`, tone: 'info' };
  if (value.deliveryState === 'sent') return { message: `Invitation sent to ${value.email}`, tone: 'success' };
  if (value.deliveryState === 'failed') return { message: `Invitation saved for ${value.email}, but email delivery failed. Use Resend after checking delivery configuration.`, tone: 'error' };
  return { message: `Invitation saved for ${value.email}; email delivery is not confirmed.`, tone: 'info' };
}

export const workspaceInvitationApi = {
  preview: (token: string) => request<WorkspaceInvitationPreview>('/workspace-invitations/preview', {
    method: 'POST', body: { token }, authenticated: false, workspaceScoped: false,
  }),
  decline: (token: string) => request<{ declined: true }>('/workspace-invitations/decline', {
    method: 'POST', body: { token }, authenticated: false, workspaceScoped: false,
  }),
  accept: (token: string) => request<WorkspaceInvitationSession>('/workspace-invitations/accept', {
    method: 'POST', body: { token }, authenticated: true, workspaceScoped: false,
  }),
  signup: (input: WorkspaceInvitationSignupInput) => request<WorkspaceInvitationSession>('/workspace-invitations/signup', {
    method: 'POST', body: input, authenticated: false, workspaceScoped: false,
  }),
};

export function activateWorkspaceInvitationSession(value: WorkspaceInvitationSession): void {
  const safeSession: Session = { accessToken: value.accessToken, expiresAt: value.expiresAt, user: value.user };
  writeStorage(SESSION_KEY, safeSession);
  persistActiveWorkspace(value.workspaceId);
  window.dispatchEvent(new Event(AUTH_SESSION_EVENT));
}
