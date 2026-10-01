import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';
import { EducationStudentImportApiError, type StudentImportRow } from '@/lib/education-student-import-api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const candidate = payload as { detail?: unknown; error?: { message?: unknown } };
    if (typeof candidate.detail === 'string') return candidate.detail;
    if (candidate.error && typeof candidate.error.message === 'string') return candidate.error.message;
  }
  return `Education student import file request failed (${status})`;
}

export async function parseStudentImportFile(file: File): Promise<StudentImportRow[]> {
  const token = bearer();
  const workspaceId = activeWorkspaceId();
  const form = new FormData();
  form.append('file', file);
  const response = await fetch(`${API_URL}/education/students/import/parse-file`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
    body: form,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as unknown;
    throw new EducationStudentImportApiError(errorMessage(payload, response.status), response.status, payload);
  }
  const payload = await response.json() as { rows?: StudentImportRow[] };
  if (!Array.isArray(payload.rows) || !payload.rows.length) {
    throw new EducationStudentImportApiError('Import file did not contain any student rows', 422, payload);
  }
  return payload.rows;
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined
    ? ''
    : typeof value === 'object' ? JSON.stringify(value) : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function serializeStudentImportRows(rows: StudentImportRow[]): string {
  const header = [
    'student_id', 'name', 'email', 'identity_type', 'identifier', 'identity_verified',
    'course_code', 'batch_code', 'agent_id', 'enrollment_status', 'starts_on', 'ends_on', 'custom_fields',
  ];
  const lines = rows.map((row) => [
    row.studentNumber,
    row.name,
    row.email,
    row.identityType,
    row.identifier,
    row.identityVerified ?? false,
    row.courseCode,
    row.batchCode,
    row.agentPublicId,
    row.enrollmentStatus ?? 'active',
    row.startsOn,
    row.endsOn,
    row.customFields ?? {},
  ].map(csvCell).join(','));
  return [header.join(','), ...lines].join('\n');
}
