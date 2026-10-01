import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export type StudentImportIdentityType = 'whatsapp' | 'telegram' | 'website_login' | 'alternate_phone';
export type StudentImportEnrollmentStatus = 'pending' | 'active';
export type StudentImportCustomFields = Record<string, string | number | boolean | null>;

export interface StudentImportRow {
  studentNumber: string;
  name: string;
  email?: string | null;
  identityType?: StudentImportIdentityType | null;
  identifier?: string | null;
  identityVerified?: boolean;
  courseCode?: string | null;
  batchCode?: string | null;
  agentPublicId?: string | null;
  enrollmentStatus?: StudentImportEnrollmentStatus;
  startsOn?: string | null;
  endsOn?: string | null;
  customFields?: StudentImportCustomFields;
}

export interface StudentImportRowPreview {
  rowNumber: number;
  valid: boolean;
  errors: string[];
  warnings: string[];
  row: StudentImportRow;
}

export interface StudentImportPreview {
  totalRows: number;
  validRows: number;
  invalidRows: number;
  rows: StudentImportRowPreview[];
}

export interface StudentImportCommitResult {
  createdStudents: number;
  createdIdentities: number;
  createdEnrollments: number;
}

export interface StudentImportCommitResponse {
  committed: boolean;
  preview: StudentImportPreview;
  result: StudentImportCommitResult | null;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';
const MAX_ROWS = 500;

const headerAliases: Record<string, keyof StudentImportRow | 'customFieldsJson'> = {
  student_id: 'studentNumber',
  student_number: 'studentNumber',
  studentnumber: 'studentNumber',
  student: 'studentNumber',
  name: 'name',
  student_name: 'name',
  email: 'email',
  identity_type: 'identityType',
  identitytype: 'identityType',
  identifier: 'identifier',
  identity: 'identifier',
  phone: 'identifier',
  identity_verified: 'identityVerified',
  identityverified: 'identityVerified',
  course: 'courseCode',
  course_code: 'courseCode',
  coursecode: 'courseCode',
  batch: 'batchCode',
  batch_code: 'batchCode',
  batchcode: 'batchCode',
  agent: 'agentPublicId',
  agent_id: 'agentPublicId',
  agent_public_id: 'agentPublicId',
  agentpublicid: 'agentPublicId',
  enrollment_status: 'enrollmentStatus',
  enrollmentstatus: 'enrollmentStatus',
  starts_on: 'startsOn',
  start_date: 'startsOn',
  startson: 'startsOn',
  ends_on: 'endsOn',
  end_date: 'endsOn',
  endson: 'endsOn',
  custom_fields: 'customFieldsJson',
  custom_fields_json: 'customFieldsJson',
  customfields: 'customFieldsJson',
};

export class EducationStudentImportApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
    this.name = 'EducationStudentImportApiError';
  }
}

export class StudentImportParseError extends Error {
  constructor(readonly problems: string[]) {
    super(problems.join('\n'));
    this.name = 'StudentImportParseError';
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
  return `Education student import request failed (${status})`;
}

async function remote<T>(path: string, body: unknown): Promise<T> {
  const token = bearer();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as unknown;
    throw new EducationStudentImportApiError(errorMessage(payload, response.status), response.status, payload);
  }
  return response.json() as Promise<T>;
}

function normalizedHeader(value: string): string {
  return value.trim().toLowerCase().replace(/[\s-]+/g, '_');
}

function detectDelimiter(text: string): ',' | '\t' {
  const firstLine = text.split(/\r?\n/, 1)[0] ?? '';
  return firstLine.includes('\t') && !firstLine.includes(',') ? '\t' : ',';
}

function parseDelimited(text: string, delimiter: ',' | '\t'): string[][] {
  const table: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]!;
    if (character === '"') {
      if (quoted && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
      continue;
    }
    if (!quoted && character === delimiter) {
      row.push(cell);
      cell = '';
      continue;
    }
    if (!quoted && (character === '\n' || character === '\r')) {
      if (character === '\r' && text[index + 1] === '\n') index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) table.push(row);
      row = [];
      cell = '';
      continue;
    }
    cell += character;
  }
  if (quoted) throw new StudentImportParseError(['CSV contains an unclosed quoted field.']);
  row.push(cell);
  if (row.some((value) => value.trim())) table.push(row);
  return table;
}

function parseBoolean(value: string, rowNumber: number): boolean {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return false;
  if (['true', 'yes', 'y', '1', 'verified'].includes(normalized)) return true;
  if (['false', 'no', 'n', '0', 'pending'].includes(normalized)) return false;
  throw new StudentImportParseError([`Row ${rowNumber}: identity_verified must be true/false, yes/no, or 1/0.`]);
}

function parseCustomFields(value: string, rowNumber: number): StudentImportCustomFields {
  if (!value.trim()) return {};
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('not an object');
    return parsed as StudentImportCustomFields;
  } catch {
    throw new StudentImportParseError([`Row ${rowNumber}: custom_fields must be a JSON object.`]);
  }
}

function normalizeOptional(value: string | undefined): string | null {
  const normalized = value?.trim() ?? '';
  return normalized || null;
}

export function parseStudentImportText(text: string): StudentImportRow[] {
  const trimmed = text.replace(/^\uFEFF/, '').trim();
  if (!trimmed) throw new StudentImportParseError(['Paste data or choose a CSV file first.']);
  const table = parseDelimited(trimmed, detectDelimiter(trimmed));
  if (table.length < 2) throw new StudentImportParseError(['Import data must contain a header row and at least one student row.']);
  const headerRow = table[0]!;
  const mappedHeaders = headerRow.map((header) => headerAliases[normalizedHeader(header)] ?? null);
  const problems: string[] = [];
  if (!mappedHeaders.includes('studentNumber')) problems.push('Missing required student_id column.');
  if (!mappedHeaders.includes('name')) problems.push('Missing required name column.');
  const unknown = headerRow.filter((header, index) => header.trim() && mappedHeaders[index] === null);
  if (unknown.length) problems.push(`Unknown columns: ${unknown.join(', ')}.`);
  const duplicates = mappedHeaders.filter((header, index) => header && mappedHeaders.indexOf(header) !== index);
  if (duplicates.length) problems.push(`Duplicate mapped columns: ${[...new Set(duplicates)].join(', ')}.`);
  if (problems.length) throw new StudentImportParseError(problems);
  const dataRows = table.slice(1);
  if (dataRows.length > MAX_ROWS) {
    throw new StudentImportParseError([`Import contains ${dataRows.length} rows; maximum is ${MAX_ROWS}.`]);
  }

  return dataRows.map((cells, dataIndex) => {
    const rowNumber = dataIndex + 2;
    const raw: Partial<Record<keyof StudentImportRow | 'customFieldsJson', string>> = {};
    mappedHeaders.forEach((header, columnIndex) => {
      if (header) raw[header] = cells[columnIndex] ?? '';
    });
    const identityType = normalizeOptional(raw.identityType) as StudentImportIdentityType | null;
    const enrollmentStatus = (normalizeOptional(raw.enrollmentStatus) ?? 'active') as StudentImportEnrollmentStatus;
    if (identityType && !['whatsapp', 'telegram', 'website_login', 'alternate_phone'].includes(identityType)) {
      throw new StudentImportParseError([`Row ${rowNumber}: unsupported identity_type "${identityType}".`]);
    }
    if (!['pending', 'active'].includes(enrollmentStatus)) {
      throw new StudentImportParseError([`Row ${rowNumber}: enrollment_status must be pending or active.`]);
    }
    return {
      studentNumber: raw.studentNumber?.trim() ?? '',
      name: raw.name?.trim() ?? '',
      email: normalizeOptional(raw.email),
      identityType,
      identifier: normalizeOptional(raw.identifier),
      identityVerified: parseBoolean(raw.identityVerified ?? '', rowNumber),
      courseCode: normalizeOptional(raw.courseCode),
      batchCode: normalizeOptional(raw.batchCode),
      agentPublicId: normalizeOptional(raw.agentPublicId),
      enrollmentStatus,
      startsOn: normalizeOptional(raw.startsOn),
      endsOn: normalizeOptional(raw.endsOn),
      customFields: parseCustomFields(raw.customFieldsJson ?? '', rowNumber),
    };
  });
}

export const STUDENT_IMPORT_TEMPLATE = [
  'student_id,name,email,identity_type,identifier,identity_verified,course_code,batch_code,agent_id,enrollment_status,starts_on,ends_on,custom_fields',
  'STUDENT-001,Asha Verma,asha@example.com,whatsapp,+919876543210,false,CPA,CPA-2026-A,agt_example,active,2026-09-01,2027-06-30,"{""language"":""en""}"',
].join('\n');

export const educationStudentImportApi = {
  preview(rows: StudentImportRow[]): Promise<StudentImportPreview> {
    return remote<StudentImportPreview>('/education/students/import/preview', { rows });
  },
  commit(rows: StudentImportRow[]): Promise<StudentImportCommitResponse> {
    return remote<StudentImportCommitResponse>('/education/students/import/commit', { rows });
  },
};
