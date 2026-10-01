import { readStorage, writeStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export interface EducationKnowledgeScopeRef {
  courseId: string;
  curriculumId?: string;
  paperId?: string | null;
  batchId?: string | null;
  selectedBlockIds?: string[];
  topicIds?: string[];
  materialType?: string;
}

export interface EducationKnowledgeScope extends EducationKnowledgeScopeRef {
  id: string;
  sourceId: string | null;
  factId: string | null;
  agentId: string;
  workspaceId: string;
  extractionRevision?: number;
  mappingRevision?: number;
  assignmentRevision?: number;
  requiresRelease?: boolean;
  approvalStatus?: 'draft' | 'approved' | 'published' | 'withdrawn';
  createdAt: string;
  updatedAt: string;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';
const SESSION_KEY = 'northstar.session';
const STORAGE_KEY = 'northstar.education.knowledge-scopes';

class EducationKnowledgeApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'EducationKnowledgeApiError';
  }
}

function sessionToken(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

async function remote<T>(path: string, method: 'GET' | 'PUT' | 'POST', body?: unknown): Promise<T> {
  const token = sessionToken();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    method,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string; error?: { message?: string } } | null;
    throw new EducationKnowledgeApiError(
      payload?.detail ?? payload?.error?.message ?? `Knowledge scope request failed (${response.status})`,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

function localScopes(): EducationKnowledgeScope[] {
  return readStorage<EducationKnowledgeScope[]>(STORAGE_KEY, []);
}

function localSourceScopes(sourceId: string): EducationKnowledgeScope[] {
  const workspaceId = activeWorkspaceId() ?? 'workspace-demo';
  return localScopes().filter((item) => item.workspaceId === workspaceId && item.sourceId === sourceId);
}

function replaceLocalSourceScopes(
  sourceId: string,
  agentId: string,
  scopes: EducationKnowledgeScopeRef[],
): EducationKnowledgeScope[] {
  const workspaceId = activeWorkspaceId() ?? 'workspace-demo';
  const retained = localScopes().filter((item) => !(item.workspaceId === workspaceId && item.sourceId === sourceId));
  const now = new Date().toISOString();
  const created = scopes.map((scope) => ({
    id: `education-knowledge-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
    sourceId,
    factId: null,
    agentId,
    workspaceId,
    courseId: scope.courseId,
    curriculumId: scope.curriculumId,
    paperId: scope.paperId ?? null,
    batchId: scope.batchId,
    selectedBlockIds: scope.selectedBlockIds ?? [],
    topicIds: scope.topicIds ?? [],
    materialType: scope.materialType ?? 'notes',
    extractionRevision: 1,
    mappingRevision: 1,
    assignmentRevision: 1,
    requiresRelease: true,
    approvalStatus: 'draft' as const,
    createdAt: now,
    updatedAt: now,
  }));
  writeStorage(STORAGE_KEY, [...retained, ...created]);
  return created;
}

async function withFallback<T>(remoteCall: () => Promise<T>, fallback: () => Promise<T>): Promise<T> {
  if (!DEMO_MODE) return remoteCall();
  try {
    return await remoteCall();
  } catch (error) {
    if (error instanceof EducationKnowledgeApiError && error.status < 500) throw error;
    return fallback();
  }
}

export const educationKnowledgeApi = {
  sourceScopes(sourceId: string): Promise<EducationKnowledgeScope[]> {
    return withFallback(
      () => remote<EducationKnowledgeScope[]>(`/knowledge/${sourceId}/education-scopes`, 'GET'),
      async () => localSourceScopes(sourceId),
    );
  },
  setSourceScopes(
    sourceId: string,
    agentId: string,
    scopes: EducationKnowledgeScopeRef[],
  ): Promise<EducationKnowledgeScope[]> {
    const unique = new Set(scopes.map((scope) => `${scope.courseId}:${scope.curriculumId}:${scope.paperId ?? ''}:${scope.batchId ?? ''}`));
    if (unique.size !== scopes.length) throw new Error('Each course audience tuple can only be selected once.');
    return withFallback(
      () => remote<EducationKnowledgeScope[]>(`/knowledge/${sourceId}/education-scopes`, 'PUT', { scopes }),
      async () => replaceLocalSourceScopes(sourceId, agentId, scopes),
    );
  },
  approve(assignment: EducationKnowledgeScope): Promise<EducationKnowledgeScope> {
    return remote(`/knowledge/education-assignments/${assignment.id}/approve`, 'POST', {
      extractionRevision: assignment.extractionRevision ?? 1,
      mappingRevision: assignment.mappingRevision ?? 1,
    });
  },
  withdraw(assignmentId: string): Promise<EducationKnowledgeScope> {
    return remote(`/knowledge/education-assignments/${assignmentId}/withdraw`, 'POST');
  },
};
