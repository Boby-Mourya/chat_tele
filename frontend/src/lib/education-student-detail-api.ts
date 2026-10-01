import { educationStudentApi, type EducationStudent } from '@/lib/education-student-api';
import type { StudentIdentityStatus, StudentIdentityType } from '@/lib/education-student-identity-api';
import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export type StudentEnrollmentStatus = 'pending' | 'active' | 'suspended' | 'expired' | 'revoked' | 'graduated';
export type StudentAccessState = StudentEnrollmentStatus | 'scheduled';
export type StudentConversationState = 'open' | 'resolved' | 'escalated';

export interface StudentDetailIdentity {
  id: string;
  identityType: StudentIdentityType;
  identifier: string;
  label: string | null;
  status: StudentIdentityStatus;
  isPrimary: boolean;
  verifiedAt: string | null;
  createdAt: string;
}

export interface StudentDetailEnrollment {
  id: string;
  courseId: string;
  courseCode: string;
  courseName: string;
  batchId: string;
  batchCode: string;
  batchName: string;
  agentId: string;
  agentPublicId: string;
  agentName: string;
  startsOn: string | null;
  endsOn: string | null;
  status: StudentEnrollmentStatus;
  accessState: StudentAccessState;
  createdAt: string;
  updatedAt: string;
}

export interface StudentDetailConversation {
  id: string;
  publicId: string;
  enrollmentId: string;
  courseId: string;
  batchId: string;
  agentId: string;
  agentName: string;
  channel: string;
  state: StudentConversationState;
  resolution: string | null;
  startedAt: string;
  endedAt: string | null;
  updatedAt: string;
}

export interface StudentDetailActivity {
  id: string;
  eventType: string;
  conversationId: string;
  conversationPublicId: string;
  enrollmentId: string;
  courseId: string;
  courseName: string;
  batchId: string;
  batchName: string;
  agentId: string;
  agentName: string;
  resolution: string | null;
  resolvedAt: string;
  actorUserId: string | null;
  details: Record<string, unknown>;
  createdAt: string;
}

export interface StudentDetailSummary {
  verifiedIdentityCount: number;
  activeAccessCount: number;
  conversationCount: number;
  activityCount: number;
  lastActiveAt: string | null;
}

export interface EducationStudentDetail {
  student: EducationStudent;
  identities: StudentDetailIdentity[];
  enrollments: StudentDetailEnrollment[];
  conversations: StudentDetailConversation[];
  activity: StudentDetailActivity[];
  summary: StudentDetailSummary;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';
const SESSION_KEY = 'northstar.session';

export class EducationStudentDetailApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
    this.name = 'EducationStudentDetailApiError';
  }
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const candidate = payload as { detail?: unknown; error?: { message?: unknown } };
    if (typeof candidate.detail === 'string') return candidate.detail;
    if (candidate.error && typeof candidate.error.message === 'string') return candidate.error.message;
  }
  return `Education student detail request failed (${status})`;
}

async function remote(studentId: string, activityLimit: number): Promise<EducationStudentDetail> {
  const token = bearer();
  const workspaceId = activeWorkspaceId();
  const params = new URLSearchParams({ activity_limit: String(activityLimit) });
  const response = await fetch(`${API_URL}/education/students/${studentId}/detail?${params.toString()}`, {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as unknown;
    throw new EducationStudentDetailApiError(errorMessage(payload, response.status), response.status, payload);
  }
  return response.json() as Promise<EducationStudentDetail>;
}

async function localFallback(studentId: string): Promise<EducationStudentDetail> {
  const student = await educationStudentApi.get(studentId);
  return {
    student,
    identities: [],
    enrollments: [],
    conversations: [],
    activity: [],
    summary: {
      verifiedIdentityCount: 0,
      activeAccessCount: 0,
      conversationCount: 0,
      activityCount: 0,
      lastActiveAt: null,
    },
  };
}

export const educationStudentDetailApi = {
  async get(studentId: string, activityLimit = 100): Promise<EducationStudentDetail> {
    const safeLimit = Math.min(500, Math.max(1, Math.trunc(activityLimit)));
    if (!DEMO_MODE) return remote(studentId, safeLimit);
    try {
      return await remote(studentId, safeLimit);
    } catch (error) {
      if (error instanceof EducationStudentDetailApiError && [400, 401, 403, 404, 409, 422].includes(error.status)) {
        throw error;
      }
      return localFallback(studentId);
    }
  },
};
