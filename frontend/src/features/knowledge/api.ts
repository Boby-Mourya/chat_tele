import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';

export interface KnowledgeRecord {
  id: string;
  name?: string;
  code?: string;
  title?: string;
  courseId?: string;
  curriculumId?: string;
  paperId?: string | null;
  batchId?: string | null;
  agentId?: string;
  enrollmentId?: string;
  studentId?: string;
  sourceId?: string;
  sourceVersionId?: string;
  sourceRevision?: number;
  recordHash?: string;
  status?: string;
  indexStatus?: string;
  indexError?: string | null;
  revision?: number;
  blockIds?: string[];
  topicIds?: string[];
  paperIds?: string[];
  selectedPaperId?: string | null;
  materialType?: string;
  language?: string;
  overview?: boolean;
  withdrawn?: boolean;
  active?: boolean;
  epoch?: number;
  releaseId?: string | null;
  content?: string;
  artifactType?: string;
  fingerprint?: string;
  reviewStatus?: string;
  question?: string;
  reason?: string;
  step?: string;
  progress?: number;
  validation?: { warnings?: Array<{ code: string; evidence: string }>; [key: string]: unknown };
  manifest?: { assignments: Array<{ assignment_id: string }>; artifacts: Array<{ id: string }> };
  [key: string]: unknown;
}
export interface KnowledgeCatalog {
  courses: KnowledgeRecord[];
  batches: KnowledgeRecord[];
  curricula: KnowledgeRecord[];
  papers: KnowledgeRecord[];
  batchCurricula: KnowledgeRecord[];
}
export interface KnowledgeStatus {
  sources: KnowledgeRecord[];
  versions: KnowledgeRecord[];
  assignments: KnowledgeRecord[];
  releases: KnowledgeRecord[];
  heads: KnowledgeRecord[];
  artifacts: KnowledgeRecord[];
  access: KnowledgeRecord[];
  enrollments: KnowledgeRecord[];
  academicReviews: KnowledgeRecord[];
  jobs: KnowledgeRecord[];
  notice: string;
}
export interface SourceBlock {
  id: string;
  type: string;
  text: string;
  unit: number;
  page_number: number | null;
  rendered_version_id: string | null;
  related_block_ids: string[];
  structure?: unknown;
}
export interface VersionDetail extends KnowledgeRecord { blocks: SourceBlock[]; sourceUnitNotice: string }
export interface StudentPreview {
  evidence: Array<{ entity_id: string; kind: string; title: string; text: string; metadata: Record<string, unknown> }>;
  notice: string;
  context: unknown;
}

export interface TutorProgress {
  id: string;
  agentId: string;
  studentId: string;
  enrollmentId: string;
  paperId: string;
  questionsAsked: number;
  practiceAttempts: number;
  objectiveAnswersCorrect: number;
  objectiveAnswersGraded: number;
  learningStatus: 'not_started' | 'practicing' | 'review_needed';
  lastActivityAt: string | null;
}

export interface TutorContext {
  identityId: string;
  agentId: string;
  enrollmentId: string | null;
  interactionState: 'awaiting_course_selection' | 'awaiting_paper_selection' | 'awaiting_quiz_answer' | 'ready_for_question';
  menuId: string | null;
  menuOptions: string[];
  menuCreatedAt: string | null;
  menuExpiresAt: string | null;
  selectionRevision: number;
  pendingQuestion: string | null;
}

export interface AcademicReview {
  id: string;
  agentId: string;
  studentId: string | null;
  enrollmentId: string;
  courseId: string | null;
  curriculumId: string | null;
  paperId: string | null;
  batchId: string | null;
  messageId: string;
  question: string;
  answer: string;
  reason: string;
  internalEvidence: Array<Record<string, unknown>>;
  externalEvidence: Array<Record<string, unknown>>;
  status: string;
  assignedReviewer: string | null;
  resolution: string | null;
  correctionDeliveryStatus: string;
  createdAt: string;
  updatedAt: string;
}

function headers(json: boolean): Record<string, string> {
  const token = readStorage<{ accessToken?: string } | null>('northstar.session', null)?.accessToken;
  const workspace = activeWorkspaceId();
  return { ...(json ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(workspace ? { 'X-Workspace-ID': workspace } : {}) };
}
async function checked(path: string, method = 'GET', body?: unknown): Promise<Response> {
  const response = await fetch(`${BASE}${path}`, { method, credentials: 'include', cache: 'no-store', headers: headers(body !== undefined), ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown; error?: { message?: string } } | null;
    const detail = typeof payload?.detail === 'string' ? payload.detail : payload?.detail ? JSON.stringify(payload.detail) : payload?.error?.message;
    throw new Error(detail || `Knowledge request failed (${response.status})`);
  }
  return response;
}
export async function knowledgeRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  return (await checked(path, method, body)).json() as Promise<T>;
}
export async function knowledgeBlob(path: string, method = 'GET', body?: unknown): Promise<Blob> {
  return (await checked(path, method, body)).blob();
}
export function knowledgePath(agentId: string, suffix: string): string {
  return `/agents/${encodeURIComponent(agentId)}/education-knowledge${suffix}`;
}
export async function stageCourseFile(file: File): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  const checksumSha256 = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('');
  const signed = await knowledgeRequest<{ url: string; fields: Record<string, string>; objectKey: string }>('/uploads/presign', 'POST', { filename: file.name, contentType: file.type || 'application/octet-stream', sizeBytes: file.size, checksumSha256 });
  const body = new FormData();
  for (const [key, value] of Object.entries(signed.fields)) body.append(key, value);
  body.append('file', file);
  const uploaded = await fetch(signed.url, { method: 'POST', body });
  if (!uploaded.ok) throw new Error(`Object storage rejected the upload (${uploaded.status})`);
  return signed.objectKey;
}
export function saveKnowledgeBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
