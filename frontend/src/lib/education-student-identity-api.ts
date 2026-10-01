import { readStorage, writeStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export type StudentIdentityType = 'whatsapp' | 'telegram' | 'website_login' | 'alternate_phone';
export type StudentIdentityStatus = 'pending' | 'verified' | 'revoked';

export interface EducationStudentIdentity {
  id: string;
  tenantId: string;
  workspaceId: string;
  studentId: string;
  identityType: StudentIdentityType;
  identifier: string;
  normalizedIdentifier: string;
  label: string | null;
  status: StudentIdentityStatus;
  isPrimary: boolean;
  verifiedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface StudentIdentityCreateInput {
  identityType: StudentIdentityType;
  identifier: string;
  label?: string | null;
  status?: Exclude<StudentIdentityStatus, 'revoked'>;
  isPrimary?: boolean;
}

export interface StudentIdentityPatchInput {
  label?: string | null;
  status?: StudentIdentityStatus;
  isPrimary?: boolean;
}

export interface StudentIdentityFilters {
  status?: StudentIdentityStatus;
  type?: StudentIdentityType;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';
const SESSION_KEY = 'northstar.session';
const IDENTITIES_KEY = 'northstar.education.student-identities';

export class EducationStudentIdentityApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
    this.name = 'EducationStudentIdentityApiError';
  }
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

function workspaceId(): string {
  return activeWorkspaceId() ?? 'workspace-demo';
}

function storedIdentities(): EducationStudentIdentity[] {
  return readStorage<EducationStudentIdentity[]>(IDENTITIES_KEY, []);
}

function persistIdentities(identities: EducationStudentIdentity[]): void {
  writeStorage(IDENTITIES_KEY, identities);
}

function normalizeIdentifier(type: StudentIdentityType, identifier: string): string {
  let value = identifier.trim();
  if (type === 'whatsapp' || type === 'alternate_phone') {
    value = value.replace(/[\s().-]+/g, '');
    if (value.startsWith('00')) value = `+${value.slice(2)}`;
    if (!/^\+[1-9]\d{7,14}$/.test(value)) {
      throw new EducationStudentIdentityApiError('Phone identity must be a valid international E.164 number', 422);
    }
    return value;
  }
  if (type === 'telegram') {
    if (!/^[1-9]\d{4,19}$/.test(value)) {
      throw new EducationStudentIdentityApiError('Telegram identity must be a numeric Telegram user ID', 422);
    }
    return value;
  }
  value = value.toLowerCase();
  if (value.length < 2 || value.length > 320 || /\s/.test(value)) {
    throw new EducationStudentIdentityApiError('Website login identity must contain 2 to 320 characters without spaces', 422);
  }
  return value;
}

function normalizeLabel(value?: string | null): string | null {
  const normalized = value?.trim().replace(/\s+/g, ' ') ?? '';
  return normalized || null;
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const candidate = payload as { detail?: unknown; error?: { message?: unknown } };
    if (typeof candidate.detail === 'string') return candidate.detail;
    if (candidate.error && typeof candidate.error.message === 'string') return candidate.error.message;
  }
  return `Education student identity request failed (${status})`;
}

async function remote<T>(
  path: string,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T> {
  const token = bearer();
  const currentWorkspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    method,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(currentWorkspaceId ? { 'X-Workspace-ID': currentWorkspaceId } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as unknown;
    throw new EducationStudentIdentityApiError(errorMessage(payload, response.status), response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function withFallback<T>(remoteCall: () => Promise<T>, fallback: () => Promise<T>): Promise<T> {
  if (!DEMO_MODE) return remoteCall();
  try {
    return await remoteCall();
  } catch (error) {
    if (error instanceof EducationStudentIdentityApiError && [400, 401, 403, 404, 409, 422].includes(error.status)) {
      throw error;
    }
    return fallback();
  }
}

function localList(studentId: string, filters: StudentIdentityFilters = {}): EducationStudentIdentity[] {
  const currentWorkspaceId = workspaceId();
  return storedIdentities()
    .filter((identity) => identity.workspaceId === currentWorkspaceId && identity.studentId === studentId)
    .filter((identity) => !filters.status || identity.status === filters.status)
    .filter((identity) => !filters.type || identity.identityType === filters.type)
    .sort((left, right) => (
      left.identityType.localeCompare(right.identityType)
      || Number(right.isPrimary) - Number(left.isPrimary)
      || left.createdAt.localeCompare(right.createdAt)
    ));
}

function ensurePrimary(identities: EducationStudentIdentity[], studentId: string, type: StudentIdentityType): void {
  const candidates = identities.filter((identity) => (
    identity.workspaceId === workspaceId()
    && identity.studentId === studentId
    && identity.identityType === type
    && identity.status !== 'revoked'
  ));
  if (!candidates.length || candidates.some((identity) => identity.isPrimary)) return;
  candidates.sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  candidates[0]!.isPrimary = true;
}

function localCreate(studentId: string, input: StudentIdentityCreateInput): EducationStudentIdentity {
  const identities = storedIdentities();
  const currentWorkspaceId = workspaceId();
  const normalizedIdentifier = normalizeIdentifier(input.identityType, input.identifier);
  if (identities.some((identity) => (
    identity.workspaceId === currentWorkspaceId
    && identity.identityType === input.identityType
    && identity.normalizedIdentifier === normalizedIdentifier
  ))) {
    throw new EducationStudentIdentityApiError('This identity is already linked to a student in this workspace', 409);
  }
  const sameType = identities.filter((identity) => (
    identity.workspaceId === currentWorkspaceId
    && identity.studentId === studentId
    && identity.identityType === input.identityType
    && identity.status !== 'revoked'
  ));
  const isPrimary = Boolean(input.isPrimary) || sameType.length === 0;
  if (isPrimary) sameType.forEach((identity) => { identity.isPrimary = false; });
  const now = new Date().toISOString();
  const status = input.status ?? 'pending';
  const created: EducationStudentIdentity = {
    id: `student-identity-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
    tenantId: 'tenant-demo',
    workspaceId: currentWorkspaceId,
    studentId,
    identityType: input.identityType,
    identifier: normalizedIdentifier,
    normalizedIdentifier,
    label: normalizeLabel(input.label),
    status,
    isPrimary,
    verifiedAt: status === 'verified' ? now : null,
    createdAt: now,
    updatedAt: now,
  };
  identities.push(created);
  persistIdentities(identities);
  return created;
}

function localUpdate(studentId: string, identityId: string, patch: StudentIdentityPatchInput): EducationStudentIdentity {
  const identities = storedIdentities();
  const currentWorkspaceId = workspaceId();
  const index = identities.findIndex((identity) => (
    identity.id === identityId
    && identity.studentId === studentId
    && identity.workspaceId === currentWorkspaceId
  ));
  if (index < 0) throw new EducationStudentIdentityApiError('Student identity not found', 404);
  const current = identities[index]!;
  const nextStatus = patch.status ?? current.status;
  if (patch.isPrimary && nextStatus === 'revoked') {
    throw new EducationStudentIdentityApiError('A revoked identity cannot be primary', 422);
  }
  const updated: EducationStudentIdentity = {
    ...current,
    ...patch,
    label: patch.label === undefined ? current.label : normalizeLabel(patch.label),
    status: nextStatus,
    isPrimary: nextStatus === 'revoked' ? false : (patch.isPrimary ?? current.isPrimary),
    verifiedAt: patch.status === 'verified'
      ? new Date().toISOString()
      : patch.status === 'pending'
        ? null
        : current.verifiedAt,
    updatedAt: new Date().toISOString(),
  };
  identities[index] = updated;
  if (updated.isPrimary) {
    identities.forEach((identity, identityIndex) => {
      if (
        identityIndex !== index
        && identity.workspaceId === currentWorkspaceId
        && identity.studentId === studentId
        && identity.identityType === updated.identityType
        && identity.status !== 'revoked'
      ) identity.isPrimary = false;
    });
  } else {
    ensurePrimary(identities, studentId, updated.identityType);
  }
  persistIdentities(identities);
  return identities[index]!;
}

export const educationStudentIdentityApi = {
  list(studentId: string, filters: StudentIdentityFilters = {}): Promise<EducationStudentIdentity[]> {
    const params = new URLSearchParams();
    if (filters.status) params.set('status', filters.status);
    if (filters.type) params.set('type', filters.type);
    const suffix = params.size ? `?${params.toString()}` : '';
    return withFallback(
      () => remote<EducationStudentIdentity[]>(`/education/students/${studentId}/identities${suffix}`, 'GET'),
      async () => localList(studentId, filters),
    );
  },
  create(studentId: string, input: StudentIdentityCreateInput): Promise<EducationStudentIdentity> {
    return withFallback(
      () => remote<EducationStudentIdentity>(`/education/students/${studentId}/identities`, 'POST', input),
      async () => localCreate(studentId, input),
    );
  },
  update(
    studentId: string,
    identityId: string,
    patch: StudentIdentityPatchInput,
  ): Promise<EducationStudentIdentity> {
    return withFallback(
      () => remote<EducationStudentIdentity>(`/education/students/${studentId}/identities/${identityId}`, 'PATCH', patch),
      async () => localUpdate(studentId, identityId, patch),
    );
  },
  revoke(studentId: string, identityId: string): Promise<void> {
    return withFallback(
      () => remote<void>(`/education/students/${studentId}/identities/${identityId}`, 'DELETE'),
      async () => { localUpdate(studentId, identityId, { status: 'revoked' }); },
    );
  },
};
