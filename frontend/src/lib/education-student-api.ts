import { readStorage, writeStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export type StudentStatus = 'active' | 'archived';
export type StudentCustomFields = Record<string, string | number | boolean | null>;

export interface EducationStudent {
  whatsappNumber?: string | null;
  whatsappVerified?: boolean;
  telegramPhoneNumber?: string | null;
  telegramPhoneVerified?: boolean;
  telegramUserId?: string | null;
  telegramVerified?: boolean;
  id: string;
  tenantId: string;
  workspaceId: string;
  studentNumber: string;
  name: string;
  email: string | null;
  customFields: StudentCustomFields;
  status: StudentStatus;
  createdAt: string;
  updatedAt: string;
}

export interface StudentCreateInput {
  whatsappNumber?: string | null;
  whatsappVerified?: boolean;
  telegramPhoneNumber?: string | null;
  telegramPhoneVerified?: boolean;
  telegramUserId?: string | null;
  telegramVerified?: boolean;
  studentNumber: string;
  name: string;
  email?: string | null;
  customFields?: StudentCustomFields;
}

export interface StudentPatchInput {
  whatsappNumber?: string | null;
  whatsappVerified?: boolean;
  telegramPhoneNumber?: string | null;
  telegramPhoneVerified?: boolean;
  telegramUserId?: string | null;
  telegramVerified?: boolean;
  studentNumber?: string;
  name?: string;
  email?: string | null;
  customFields?: StudentCustomFields;
  status?: StudentStatus;
}

export interface StudentFilters {
  status?: StudentStatus;
  search?: string;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';
const SESSION_KEY = 'northstar.session';
const STUDENTS_KEY = 'northstar.education.students';

export class EducationStudentApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
    this.name = 'EducationStudentApiError';
  }
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

function workspaceId(): string {
  return activeWorkspaceId() ?? 'workspace-demo';
}

function storedStudents(): EducationStudent[] {
  return readStorage<EducationStudent[]>(STUDENTS_KEY, []);
}

function persistStudents(students: EducationStudent[]): void {
  writeStorage(STUDENTS_KEY, students);
}

function normalizeStudentNumber(value: string): string {
  return value.trim().toUpperCase();
}

function normalizeName(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

function normalizeEmail(value?: string | null): string | null {
  const normalized = value?.trim().toLowerCase() ?? '';
  return normalized || null;
}

function normalizeCustomFields(fields: StudentCustomFields = {}): StudentCustomFields {
  return Object.fromEntries(
    Object.entries(fields)
      .map(([key, value]) => [key.trim(), typeof value === 'string' ? value.trim() : value] as const)
      .filter(([key]) => Boolean(key)),
  );
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const candidate = payload as { detail?: unknown; error?: { message?: unknown } };
    if (typeof candidate.detail === 'string') return candidate.detail;
    if (candidate.error && typeof candidate.error.message === 'string') return candidate.error.message;
  }
  return `Education student request failed (${status})`;
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
    throw new EducationStudentApiError(errorMessage(payload, response.status), response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function withFallback<T>(remoteCall: () => Promise<T>, fallback: () => Promise<T>): Promise<T> {
  if (!DEMO_MODE) return remoteCall();
  try {
    return await remoteCall();
  } catch (error) {
    if (error instanceof EducationStudentApiError && [400, 401, 403, 409, 422].includes(error.status)) throw error;
    return fallback();
  }
}

function localList(filters: StudentFilters = {}): EducationStudent[] {
  const currentWorkspaceId = workspaceId();
  const search = filters.search?.trim().toLowerCase() ?? '';
  return storedStudents()
    .filter((student) => student.workspaceId === currentWorkspaceId)
    .filter((student) => !filters.status || student.status === filters.status)
    .filter((student) => {
      if (!search) return true;
      const custom = Object.entries(student.customFields).map(([key, value]) => `${key} ${String(value ?? '')}`).join(' ');
      return `${student.studentNumber} ${student.name} ${student.email ?? ''} ${student.telegramPhoneNumber ?? ''} ${custom}`.toLowerCase().includes(search);
    })
    .sort((left, right) => left.name.localeCompare(right.name) || left.studentNumber.localeCompare(right.studentNumber));
}

function localCreate(input: StudentCreateInput): EducationStudent {
  const students = storedStudents();
  const currentWorkspaceId = workspaceId();
  const studentNumber = normalizeStudentNumber(input.studentNumber);
  if (students.some((student) => student.workspaceId === currentWorkspaceId && student.studentNumber === studentNumber)) {
    throw new EducationStudentApiError('A student with this Student ID already exists in this workspace', 409);
  }
  const now = new Date().toISOString();
  const student: EducationStudent = {
    id: `student-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
    tenantId: 'tenant-demo',
    workspaceId: currentWorkspaceId,
    telegramPhoneNumber: input.telegramPhoneNumber?.trim() || null,
    telegramPhoneVerified: Boolean(input.telegramPhoneNumber?.trim() && input.telegramPhoneVerified),
    telegramUserId: input.telegramUserId?.trim() || null,
    telegramVerified: Boolean(input.telegramUserId?.trim() && input.telegramVerified),
    studentNumber,
    name: normalizeName(input.name),
    email: normalizeEmail(input.email),
    customFields: normalizeCustomFields(input.customFields),
    status: 'active',
    createdAt: now,
    updatedAt: now,
  };
  students.push(student);
  persistStudents(students);
  return student;
}

function localUpdate(studentId: string, patch: StudentPatchInput): EducationStudent {
  const students = storedStudents();
  const currentWorkspaceId = workspaceId();
  const index = students.findIndex((student) => student.id === studentId && student.workspaceId === currentWorkspaceId);
  if (index < 0) throw new EducationStudentApiError('Student not found', 404);
  const current = students[index]!;
  const nextStudentNumber = patch.studentNumber === undefined
    ? current.studentNumber
    : normalizeStudentNumber(patch.studentNumber);
  if (students.some((student, studentIndex) => (
    studentIndex !== index
    && student.workspaceId === currentWorkspaceId
    && student.studentNumber === nextStudentNumber
  ))) {
    throw new EducationStudentApiError('A student with this Student ID already exists in this workspace', 409);
  }
  const updated: EducationStudent = {
    ...current,
    ...patch,
    studentNumber: nextStudentNumber,
    name: patch.name === undefined ? current.name : normalizeName(patch.name),
    email: patch.email === undefined ? current.email : normalizeEmail(patch.email),
    customFields: patch.customFields === undefined ? current.customFields : normalizeCustomFields(patch.customFields),
    updatedAt: new Date().toISOString(),
  };
  students[index] = updated;
  persistStudents(students);
  return updated;
}

export const educationStudentApi = {
  list(filters: StudentFilters = {}): Promise<EducationStudent[]> {
    const params = new URLSearchParams();
    if (filters.status) params.set('status', filters.status);
    if (filters.search?.trim()) params.set('search', filters.search.trim());
    const suffix = params.size ? `?${params.toString()}` : '';
    return withFallback(
      () => remote<EducationStudent[]>(`/education/students${suffix}`, 'GET'),
      async () => localList(filters),
    );
  },
  get(studentId: string): Promise<EducationStudent> {
    return withFallback(
      () => remote<EducationStudent>(`/education/students/${studentId}`, 'GET'),
      async () => {
        const student = localList().find((item) => item.id === studentId);
        if (!student) throw new EducationStudentApiError('Student not found', 404);
        return student;
      },
    );
  },
  create(input: StudentCreateInput): Promise<EducationStudent> {
    return withFallback(
      () => remote<EducationStudent>('/education/students', 'POST', input),
      async () => localCreate(input),
    );
  },
  update(studentId: string, patch: StudentPatchInput): Promise<EducationStudent> {
    return withFallback(
      () => remote<EducationStudent>(`/education/students/${studentId}`, 'PATCH', patch),
      async () => localUpdate(studentId, patch),
    );
  },
  archive(studentId: string): Promise<void> {
    return withFallback(
      () => remote<void>(`/education/students/${studentId}`, 'DELETE'),
      async () => { localUpdate(studentId, { status: 'archived' }); },
    );
  },
};
