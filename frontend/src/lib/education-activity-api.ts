import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type { PageResult, Session } from '@/types';

export interface EducationActivityItem {
  id: string;
  eventType: string;
  studentId: string;
  studentNumber: string;
  studentName: string;
  studentEmail: string | null;
  enrollmentId: string;
  courseId: string;
  courseCode: string;
  courseName: string;
  batchId: string;
  batchCode: string;
  batchName: string;
  agentId: string;
  agentPublicId: string;
  agentName: string;
  conversationId: string;
  conversationPublicId: string;
  resolution: string | null;
  resolvedAt: string;
  actorUserId: string | null;
  details: Record<string, unknown>;
  createdAt: string;
}

export interface EducationActivityFilters {
  agentId?: string;
  courseId?: string;
  batchId?: string;
  studentId?: string;
  eventType?: string;
  search?: string;
  page?: number;
  pageSize?: number;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';
const SESSION_KEY = 'northstar.session';

export class EducationActivityApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
    this.name = 'EducationActivityApiError';
  }
}

function headers(): HeadersInit {
  const session = readStorage<Session | null>(SESSION_KEY, null);
  const workspaceId = activeWorkspaceId();
  return {
    Accept: 'application/json',
    ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}),
    ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
  };
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const candidate = payload as { detail?: unknown; error?: { message?: unknown } };
    if (typeof candidate.detail === 'string') return candidate.detail;
    if (candidate.error && typeof candidate.error.message === 'string') return candidate.error.message;
  }
  return `Education activity request failed (${status})`;
}

export const educationActivityApi = {
  async list(filters: EducationActivityFilters = {}): Promise<PageResult<EducationActivityItem>> {
    const params = new URLSearchParams();
    if (filters.agentId) params.set('agent_id', filters.agentId);
    if (filters.courseId) params.set('course_id', filters.courseId);
    if (filters.batchId) params.set('batch_id', filters.batchId);
    if (filters.studentId) params.set('student_id', filters.studentId);
    if (filters.eventType?.trim()) params.set('event_type', filters.eventType.trim());
    if (filters.search?.trim()) params.set('search', filters.search.trim());
    params.set('page', String(filters.page ?? 1));
    params.set('page_size', String(filters.pageSize ?? 50));

    try {
      const response = await fetch(`${API_URL}/education/activity?${params.toString()}`, {
        credentials: 'include',
        headers: headers(),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as unknown;
        throw new EducationActivityApiError(errorMessage(payload, response.status), response.status, payload);
      }
      return response.json() as Promise<PageResult<EducationActivityItem>>;
    } catch (error) {
      if (!DEMO_MODE || (error instanceof EducationActivityApiError && [400, 401, 403, 409, 422].includes(error.status))) {
        throw error;
      }
      return {
        items: [],
        total: 0,
        page: filters.page ?? 1,
        pageSize: filters.pageSize ?? 50,
      };
    }
  },
};
