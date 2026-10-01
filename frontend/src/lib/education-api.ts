import { ApiError, request } from '@/lib/api';
import { readStorage, writeStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export type CourseStatus = 'active' | 'archived';
export type BatchStatus = 'active' | 'archived';

export interface EducationCourse {
  id: string;
  tenantId: string;
  workspaceId: string;
  code: string;
  name: string;
  description: string;
  status: CourseStatus;
  createdAt: string;
  updatedAt: string;
}

export interface EducationBatch {
  id: string;
  tenantId: string;
  workspaceId: string;
  courseId: string;
  curriculumId?: string | null;
  code: string;
  name: string;
  description: string;
  startsOn: string | null;
  endsOn: string | null;
  status: BatchStatus;
  createdAt: string;
  updatedAt: string;
}

export interface CourseCreateInput {
  code: string;
  name: string;
  description?: string;
}

export interface CoursePatchInput {
  code?: string;
  name?: string;
  description?: string;
  status?: CourseStatus;
}

export interface CourseFilters {
  status?: CourseStatus;
  search?: string;
}

export interface BatchCreateInput {
  courseId: string;
  code: string;
  name: string;
  description?: string;
  startsOn?: string | null;
  endsOn?: string | null;
}

export interface BatchPatchInput {
  code?: string;
  name?: string;
  description?: string;
  startsOn?: string | null;
  endsOn?: string | null;
  status?: BatchStatus;
}

export interface BatchFilters {
  courseId?: string;
  status?: BatchStatus;
  search?: string;
}

const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';
const COURSES_KEY = 'northstar.education.courses';
const BATCHES_KEY = 'northstar.education.batches';

export class EducationApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
    this.name = 'EducationApiError';
  }
}

function currentWorkspaceId(): string {
  return activeWorkspaceId() ?? 'workspace-demo';
}

function localCourses(): EducationCourse[] {
  return readStorage<EducationCourse[]>(COURSES_KEY, []);
}

function persistCourses(courses: EducationCourse[]): void {
  writeStorage(COURSES_KEY, courses);
}

function localBatches(): EducationBatch[] {
  return readStorage<EducationBatch[]>(BATCHES_KEY, []);
}

function persistBatches(batches: EducationBatch[]): void {
  writeStorage(BATCHES_KEY, batches);
}

function normalizeCode(value: string): string {
  return value.trim().toUpperCase();
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const candidate = payload as { detail?: unknown; error?: { message?: unknown } };
    if (typeof candidate.detail === 'string') return candidate.detail;
    if (candidate.error && typeof candidate.error.message === 'string') return candidate.error.message;
  }
  return `Education request failed (${status})`;
}

async function remote<T>(
  path: string,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T> {
  try {
    return await request<T>(path, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw new EducationApiError(
        error.status === 401 ? 'Your session has expired. Please sign in again.' : errorMessage(error.detail, error.status),
        error.status,
        error.detail,
      );
    }
    throw error;
  }
}

async function withFallback<T>(remoteCall: () => Promise<T>, fallback: () => Promise<T>): Promise<T> {
  if (!DEMO_MODE) return remoteCall();
  try {
    return await remoteCall();
  } catch (error) {
    if (error instanceof EducationApiError && [400, 401, 403, 409, 422].includes(error.status)) throw error;
    return fallback();
  }
}

function localListCourses(filters: CourseFilters = {}): EducationCourse[] {
  const workspaceId = currentWorkspaceId();
  const search = filters.search?.trim().toLowerCase() ?? '';
  return localCourses()
    .filter((course) => course.workspaceId === workspaceId)
    .filter((course) => !filters.status || course.status === filters.status)
    .filter((course) => {
      if (!search) return true;
      return `${course.code} ${course.name} ${course.description}`.toLowerCase().includes(search);
    })
    .sort((left, right) => left.name.localeCompare(right.name) || left.code.localeCompare(right.code));
}

function localCreateCourse(input: CourseCreateInput): EducationCourse {
  const courses = localCourses();
  const workspaceId = currentWorkspaceId();
  const code = normalizeCode(input.code);
  if (courses.some((course) => course.workspaceId === workspaceId && course.code === code)) {
    throw new EducationApiError('A course with this code already exists in this workspace', 409);
  }
  const now = new Date().toISOString();
  const course: EducationCourse = {
    id: `course-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
    tenantId: 'tenant-demo',
    workspaceId,
    code,
    name: input.name.trim(),
    description: input.description?.trim() ?? '',
    status: 'active',
    createdAt: now,
    updatedAt: now,
  };
  courses.push(course);
  persistCourses(courses);
  return course;
}

function localUpdateCourse(courseId: string, patch: CoursePatchInput): EducationCourse {
  const courses = localCourses();
  const workspaceId = currentWorkspaceId();
  const index = courses.findIndex((course) => course.id === courseId && course.workspaceId === workspaceId);
  if (index < 0) throw new EducationApiError('Course not found', 404);
  const current = courses[index]!;
  const nextCode = patch.code === undefined ? current.code : normalizeCode(patch.code);
  if (courses.some((course, courseIndex) => (
    courseIndex !== index && course.workspaceId === workspaceId && course.code === nextCode
  ))) {
    throw new EducationApiError('A course with this code already exists in this workspace', 409);
  }
  if (patch.status === 'archived') {
    const hasActiveBatches = localBatches().some((batch) => (
      batch.workspaceId === workspaceId && batch.courseId === courseId && batch.status === 'active'
    ));
    if (hasActiveBatches) {
      throw new EducationApiError('Archive active batches before archiving this course', 409);
    }
  }
  const updated: EducationCourse = {
    ...current,
    ...patch,
    code: nextCode,
    name: patch.name === undefined ? current.name : patch.name.trim(),
    description: patch.description === undefined ? current.description : patch.description.trim(),
    updatedAt: new Date().toISOString(),
  };
  courses[index] = updated;
  persistCourses(courses);
  return updated;
}

function validateBatchDates(startsOn: string | null, endsOn: string | null): void {
  if (startsOn && endsOn && endsOn < startsOn) {
    throw new EducationApiError('Batch end date cannot be before start date', 422);
  }
}

function localListBatches(filters: BatchFilters = {}): EducationBatch[] {
  const workspaceId = currentWorkspaceId();
  const search = filters.search?.trim().toLowerCase() ?? '';
  return localBatches()
    .filter((batch) => batch.workspaceId === workspaceId)
    .filter((batch) => !filters.courseId || batch.courseId === filters.courseId)
    .filter((batch) => !filters.status || batch.status === filters.status)
    .filter((batch) => {
      if (!search) return true;
      return `${batch.code} ${batch.name} ${batch.description}`.toLowerCase().includes(search);
    })
    .sort((left, right) => left.name.localeCompare(right.name) || left.code.localeCompare(right.code));
}

function activeLocalCourse(courseId: string): EducationCourse {
  const workspaceId = currentWorkspaceId();
  const course = localCourses().find((item) => item.id === courseId && item.workspaceId === workspaceId);
  if (!course) throw new EducationApiError('Course not found', 404);
  if (course.status !== 'active') {
    throw new EducationApiError('Archived courses cannot receive active batches', 409);
  }
  return course;
}

function localCreateBatch(input: BatchCreateInput): EducationBatch {
  activeLocalCourse(input.courseId);
  const batches = localBatches();
  const workspaceId = currentWorkspaceId();
  const code = normalizeCode(input.code);
  if (batches.some((batch) => batch.workspaceId === workspaceId && batch.code === code)) {
    throw new EducationApiError('A batch with this code already exists in this workspace', 409);
  }
  const startsOn = input.startsOn ?? null;
  const endsOn = input.endsOn ?? null;
  validateBatchDates(startsOn, endsOn);
  const now = new Date().toISOString();
  const batch: EducationBatch = {
    id: `batch-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
    tenantId: 'tenant-demo',
    workspaceId,
    courseId: input.courseId,
    code,
    name: input.name.trim(),
    description: input.description?.trim() ?? '',
    startsOn,
    endsOn,
    status: 'active',
    createdAt: now,
    updatedAt: now,
  };
  batches.push(batch);
  persistBatches(batches);
  return batch;
}

function localUpdateBatch(batchId: string, patch: BatchPatchInput): EducationBatch {
  const batches = localBatches();
  const workspaceId = currentWorkspaceId();
  const index = batches.findIndex((batch) => batch.id === batchId && batch.workspaceId === workspaceId);
  if (index < 0) throw new EducationApiError('Batch not found', 404);
  const current = batches[index]!;
  if (patch.status === 'active' && current.status !== 'active') activeLocalCourse(current.courseId);
  const nextCode = patch.code === undefined ? current.code : normalizeCode(patch.code);
  if (batches.some((batch, batchIndex) => (
    batchIndex !== index && batch.workspaceId === workspaceId && batch.code === nextCode
  ))) {
    throw new EducationApiError('A batch with this code already exists in this workspace', 409);
  }
  const startsOn = patch.startsOn === undefined ? current.startsOn : patch.startsOn;
  const endsOn = patch.endsOn === undefined ? current.endsOn : patch.endsOn;
  validateBatchDates(startsOn, endsOn);
  const updated: EducationBatch = {
    ...current,
    ...patch,
    code: nextCode,
    name: patch.name === undefined ? current.name : patch.name.trim(),
    description: patch.description === undefined ? current.description : patch.description.trim(),
    startsOn,
    endsOn,
    updatedAt: new Date().toISOString(),
  };
  batches[index] = updated;
  persistBatches(batches);
  return updated;
}

export const educationApi = {
  courses: {
    list(filters: CourseFilters = {}): Promise<EducationCourse[]> {
      const params = new URLSearchParams();
      if (filters.status) params.set('status', filters.status);
      if (filters.search?.trim()) params.set('search', filters.search.trim());
      const suffix = params.size ? `?${params.toString()}` : '';
      return withFallback(
        () => remote<EducationCourse[]>(`/education/courses${suffix}`, 'GET'),
        async () => localListCourses(filters),
      );
    },
    get(courseId: string): Promise<EducationCourse> {
      return withFallback(
        () => remote<EducationCourse>(`/education/courses/${courseId}`, 'GET'),
        async () => {
          const course = localListCourses().find((item) => item.id === courseId);
          if (!course) throw new EducationApiError('Course not found', 404);
          return course;
        },
      );
    },
    create(input: CourseCreateInput): Promise<EducationCourse> {
      return withFallback(
        () => remote<EducationCourse>('/education/courses', 'POST', input),
        async () => localCreateCourse(input),
      );
    },
    update(courseId: string, patch: CoursePatchInput): Promise<EducationCourse> {
      return withFallback(
        () => remote<EducationCourse>(`/education/courses/${courseId}`, 'PATCH', patch),
        async () => localUpdateCourse(courseId, patch),
      );
    },
    archive(courseId: string): Promise<void> {
      return withFallback(
        () => remote<void>(`/education/courses/${courseId}`, 'DELETE'),
        async () => { localUpdateCourse(courseId, { status: 'archived' }); },
      );
    },
  },
  batches: {
    list(filters: BatchFilters = {}): Promise<EducationBatch[]> {
      const params = new URLSearchParams();
      if (filters.courseId) params.set('course_id', filters.courseId);
      if (filters.status) params.set('status', filters.status);
      if (filters.search?.trim()) params.set('search', filters.search.trim());
      const suffix = params.size ? `?${params.toString()}` : '';
      return withFallback(
        () => remote<EducationBatch[]>(`/education/batches${suffix}`, 'GET'),
        async () => localListBatches(filters),
      );
    },
    get(batchId: string): Promise<EducationBatch> {
      return withFallback(
        () => remote<EducationBatch>(`/education/batches/${batchId}`, 'GET'),
        async () => {
          const batch = localListBatches().find((item) => item.id === batchId);
          if (!batch) throw new EducationApiError('Batch not found', 404);
          return batch;
        },
      );
    },
    create(input: BatchCreateInput): Promise<EducationBatch> {
      return withFallback(
        () => remote<EducationBatch>('/education/batches', 'POST', input),
        async () => localCreateBatch(input),
      );
    },
    update(batchId: string, patch: BatchPatchInput): Promise<EducationBatch> {
      return withFallback(
        () => remote<EducationBatch>(`/education/batches/${batchId}`, 'PATCH', patch),
        async () => localUpdateBatch(batchId, patch),
      );
    },
    archive(batchId: string): Promise<void> {
      return withFallback(
        () => remote<void>(`/education/batches/${batchId}`, 'DELETE'),
        async () => { localUpdateBatch(batchId, { status: 'archived' }); },
      );
    },
  },
};
