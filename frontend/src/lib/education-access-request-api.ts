import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export type EducationAccessRequestStatus = 'pending' | 'approved' | 'denied';
export type EducationAccessRequestIdentityType = 'whatsapp' | 'telegram' | 'website_login' | 'alternate_phone';

export interface EducationAccessRequest {
  id: string;
  tenantId: string;
  workspaceId: string;
  agentId: string;
  studentId: string | null;
  enrollmentId: string | null;
  studentNumber: string;
  email: string | null;
  identityType: EducationAccessRequestIdentityType;
  normalizedIdentifier: string;
  message: string | null;
  status: EducationAccessRequestStatus;
  reviewedByUserId: string | null;
  reviewedAt: string | null;
  resolutionNote: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface EducationAccessRequestCreateInput {
  agentPublicId: string;
  studentNumber: string;
  email: string;
  identityType: EducationAccessRequestIdentityType;
  identifier: string;
  message?: string | null;
}

export interface EducationAccessRequestAccepted {
  accepted: boolean;
  requestId: string;
}

export interface EducationAccessRequestFilters {
  status?: EducationAccessRequestStatus;
  search?: string;
}

export interface EducationAccessRequestReviewInput {
  action: 'approve' | 'deny';
  studentId?: string;
  enrollmentId?: string;
  note?: string | null;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

export class EducationAccessRequestApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
    this.name = 'EducationAccessRequestApiError';
  }
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const candidate = payload as { detail?: unknown; error?: { message?: unknown } };
    if (typeof candidate.detail === 'string' && candidate.detail.trim()) return candidate.detail;
    if (candidate.error && typeof candidate.error.message === 'string') return candidate.error.message;
  }
  return `Education access request failed (${status})`;
}

async function responseError(response: Response): Promise<EducationAccessRequestApiError> {
  const payload = await response.json().catch(() => null) as unknown;
  return new EducationAccessRequestApiError(errorMessage(payload, response.status), response.status, payload);
}

export const educationAccessRequestApi = {
  async create(input: EducationAccessRequestCreateInput): Promise<EducationAccessRequestAccepted> {
    const response = await fetch(`${API_URL}/education/access-requests`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agentPublicId: input.agentPublicId.trim(),
        studentNumber: input.studentNumber.trim().toUpperCase(),
        email: input.email.trim().toLowerCase(),
        identityType: input.identityType,
        identifier: input.identifier.trim(),
        message: input.message?.trim() || null,
      }),
    });
    if (!response.ok) throw await responseError(response);
    return response.json() as Promise<EducationAccessRequestAccepted>;
  },

  async list(filters: EducationAccessRequestFilters = {}): Promise<EducationAccessRequest[]> {
    const token = bearer();
    const workspaceId = activeWorkspaceId();
    const params = new URLSearchParams();
    if (filters.status) params.set('status', filters.status);
    if (filters.search?.trim()) params.set('search', filters.search.trim());
    const suffix = params.size ? `?${params.toString()}` : '';
    const response = await fetch(`${API_URL}/education/access-requests${suffix}`, {
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
      },
    });
    if (!response.ok) throw await responseError(response);
    return response.json() as Promise<EducationAccessRequest[]>;
  },

  async review(requestId: string, input: EducationAccessRequestReviewInput): Promise<EducationAccessRequest> {
    const token = bearer();
    const workspaceId = activeWorkspaceId();
    const response = await fetch(`${API_URL}/education/access-requests/${requestId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
      },
      body: JSON.stringify(input),
    });
    if (!response.ok) throw await responseError(response);
    return response.json() as Promise<EducationAccessRequest>;
  },
};
