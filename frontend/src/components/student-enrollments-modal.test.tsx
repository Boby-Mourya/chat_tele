import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/providers';
import { StudentEnrollmentsModal } from '@/components/student-enrollments-modal';
import type { EducationBatch, EducationCourse } from '@/lib/education-api';
import type {
  EducationEnrollment,
  EnrollmentCreateInput,
  EnrollmentPatchInput,
} from '@/lib/education-enrollment-api';
import type { EducationStudent } from '@/lib/education-student-api';
import type { Agent } from '@/types';

const enrollmentMocks = vi.hoisted(() => ({
  list: vi.fn<() => Promise<EducationEnrollment[]>>(),
  create: vi.fn<(input: EnrollmentCreateInput) => Promise<EducationEnrollment>>(),
  update: vi.fn<(enrollmentId: string, patch: EnrollmentPatchInput) => Promise<EducationEnrollment>>(),
  revoke: vi.fn<(enrollmentId: string) => Promise<void>>(),
}));
const courseMocks = vi.hoisted(() => ({ list: vi.fn<() => Promise<EducationCourse[]>>() }));
const batchMocks = vi.hoisted(() => ({ list: vi.fn<() => Promise<EducationBatch[]>>() }));
const agentMocks = vi.hoisted(() => ({ list: vi.fn<() => Promise<Agent[]>>() }));

vi.mock('@/lib/education-enrollment-api', () => ({ educationEnrollmentApi: enrollmentMocks }));
vi.mock('@/lib/education-api', () => ({
  educationApi: { courses: courseMocks, batches: batchMocks },
}));
vi.mock('@/lib/api', () => ({ api: { agents: agentMocks } }));

const student: EducationStudent = {
  id: 'student-1',
  tenantId: 'tenant-1',
  workspaceId: 'workspace-1',
  studentNumber: 'NS-1001',
  name: 'Asha Verma',
  email: 'asha@example.com',
  customFields: {},
  status: 'active',
  createdAt: '2026-09-01T10:00:00.000Z',
  updatedAt: '2026-09-01T10:00:00.000Z',
};

const courses: EducationCourse[] = [
  {
    id: 'course-cpa', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'CPA', name: 'CPA',
    description: '', status: 'active', createdAt: '2026-09-01T10:00:00.000Z', updatedAt: '2026-09-01T10:00:00.000Z',
  },
  {
    id: 'course-acca', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'ACCA', name: 'ACCA',
    description: '', status: 'active', createdAt: '2026-09-01T10:00:00.000Z', updatedAt: '2026-09-01T10:00:00.000Z',
  },
];

const batches: EducationBatch[] = [
  {
    id: 'batch-cpa', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-cpa', code: 'CPA-A',
    name: 'CPA A', description: '', startsOn: '2026-09-15', endsOn: '2027-03-31', status: 'active',
    createdAt: '2026-09-01T10:00:00.000Z', updatedAt: '2026-09-01T10:00:00.000Z',
  },
  {
    id: 'batch-acca', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-acca', code: 'ACCA-A',
    name: 'ACCA A', description: '', startsOn: null, endsOn: null, status: 'active',
    createdAt: '2026-09-01T10:00:00.000Z', updatedAt: '2026-09-01T10:00:00.000Z',
  },
];

function agent(id: string, name: string, purpose: Agent['purpose']): Agent {
  return {
    id,
    workspaceId: 'workspace-1',
    publicId: `${id}-public`,
    name,
    description: '',
    instructions: '',
    status: 'draft',
    purpose,
    tone: 'friendly',
    language: 'English',
    avatar: 'N',
    conversations: 0,
    resolutionRate: 0,
    knowledgeCount: 0,
    lastUpdated: '2026-09-01T10:00:00.000Z',
    createdAt: '2026-09-01T10:00:00.000Z',
    appearance: {
      primaryColor: '#146cf6', surfaceColor: '#f6f8fb', position: 'bottom-right', launcherStyle: 'spark',
      welcomeTitle: 'Welcome', welcomeMessage: 'Hello', placeholder: 'Ask', suggestedQuestions: [], showBranding: true,
    },
    model: {
      provider: 'nvidia', model: 'nvidia/nemotron-3-ultra-550b-a55b', temperature: 1, topP: 0.95,
      maxTokens: 16384, enableThinking: true, citationMode: 'when-available',
    },
    security: { allowedDomains: [], rateLimitPerMinute: 30, collectEmail: false, maskSensitiveData: true, retentionDays: 90 },
  };
}

function enrollment(overrides: Partial<EducationEnrollment> = {}): EducationEnrollment {
  return {
    id: 'enrollment-1',
    tenantId: 'tenant-1',
    workspaceId: 'workspace-1',
    studentId: student.id,
    courseId: 'course-cpa',
    batchId: 'batch-cpa',
    agentId: 'agent-education',
    startsOn: '2026-09-15',
    endsOn: '2027-03-31',
    status: 'pending',
    createdAt: '2026-09-01T10:00:00.000Z',
    updatedAt: '2026-09-01T10:00:00.000Z',
    ...overrides,
  };
}

describe('StudentEnrollmentsModal', () => {
  let records: EducationEnrollment[];

  beforeEach(() => {
    records = [enrollment()];
    enrollmentMocks.list.mockImplementation(async () => structuredClone(records));
    courseMocks.list.mockImplementation(async () => structuredClone(courses));
    batchMocks.list.mockImplementation(async () => structuredClone(batches));
    agentMocks.list.mockImplementation(async () => [
      agent('agent-education', 'Education Mentor', 'education'),
      agent('agent-support', 'Support Bot', 'support'),
    ]);
    enrollmentMocks.create.mockImplementation(async (input) => {
      const now = new Date().toISOString();
      const created = enrollment({
        id: 'enrollment-2',
        studentId: input.studentId,
        courseId: input.courseId,
        batchId: input.batchId,
        agentId: input.agentId,
        startsOn: input.startsOn ?? null,
        endsOn: input.endsOn ?? null,
        status: input.status ?? 'pending',
        createdAt: now,
        updatedAt: now,
      });
      records.push(created);
      return structuredClone(created);
    });
    enrollmentMocks.update.mockImplementation(async (enrollmentId, patch) => {
      const index = records.findIndex((item) => item.id === enrollmentId);
      if (index < 0) throw new Error('Enrollment not found');
      records[index] = { ...records[index]!, ...patch, updatedAt: new Date().toISOString() };
      return structuredClone(records[index]!);
    });
    enrollmentMocks.revoke.mockImplementation(async (enrollmentId) => {
      const index = records.findIndex((item) => item.id === enrollmentId);
      if (index < 0) throw new Error('Enrollment not found');
      records[index] = { ...records[index]!, status: 'revoked', updatedAt: new Date().toISOString() };
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('creates enrollment access with Course-scoped batches and Education Agents only', async () => {
    const user = userEvent.setup();
    render(<ToastProvider><StudentEnrollmentsModal student={student} open onClose={vi.fn()} /></ToastProvider>);
    const dialog = screen.getByRole('dialog');
    expect(await within(dialog).findByRole('option', { name: 'CPA · CPA' })).toBeInTheDocument();

    const agentSelect = within(dialog).getByLabelText('Education Agent');
    expect(within(agentSelect).getByRole('option', { name: /Education Mentor/ })).toBeInTheDocument();
    expect(within(agentSelect).queryByRole('option', { name: /Support Bot/ })).not.toBeInTheDocument();

    await user.selectOptions(within(dialog).getByLabelText('Course'), 'course-cpa');
    const batchSelect = within(dialog).getByLabelText('Batch');
    expect(within(batchSelect).getByRole('option', { name: /CPA-A/ })).toBeInTheDocument();
    expect(within(batchSelect).queryByRole('option', { name: /ACCA-A/ })).not.toBeInTheDocument();
    await user.selectOptions(batchSelect, 'batch-cpa');
    await user.selectOptions(agentSelect, 'agent-education');
    await user.selectOptions(within(dialog).getByLabelText('Initial status'), 'active');
    await user.click(within(dialog).getByRole('button', { name: 'Add enrollment' }));

    await waitFor(() => expect(enrollmentMocks.create).toHaveBeenCalledWith({
      studentId: student.id,
      courseId: 'course-cpa',
      batchId: 'batch-cpa',
      agentId: 'agent-education',
      startsOn: '2026-09-15',
      endsOn: '2027-03-31',
      status: 'active',
    }));
    expect(await within(dialog).findAllByText('Active')).not.toHaveLength(0);
  });

  it('supports enrollment lifecycle actions without deleting history', async () => {
    const user = userEvent.setup();
    render(<ToastProvider><StudentEnrollmentsModal student={student} open onClose={vi.fn()} /></ToastProvider>);
    const dialog = screen.getByRole('dialog');
    await within(dialog).findByRole('button', { name: 'Activate' });

    await user.click(within(dialog).getByRole('button', { name: 'Activate' }));
    await waitFor(() => expect(enrollmentMocks.update).toHaveBeenCalledWith('enrollment-1', { status: 'active' }));
    expect(await within(dialog).findByRole('button', { name: 'Suspend' })).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Suspend' }));
    await waitFor(() => expect(enrollmentMocks.update).toHaveBeenCalledWith('enrollment-1', { status: 'suspended' }));

    await user.click(within(dialog).getByRole('button', { name: 'Revoke' }));
    await waitFor(() => expect(enrollmentMocks.revoke).toHaveBeenCalledWith('enrollment-1'));
    expect(await within(dialog).findByRole('button', { name: 'Restore' })).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(enrollmentMocks.update).toHaveBeenCalledWith('enrollment-1', { status: 'pending' }));
  });

  it('keeps archived Students read-only while preserving enrollment history', async () => {
    const archivedStudent = { ...student, status: 'archived' as const };
    render(<ToastProvider><StudentEnrollmentsModal student={archivedStudent} open onClose={vi.fn()} /></ToastProvider>);
    const dialog = screen.getByRole('dialog');
    expect(await within(dialog).findByText('Student is archived')).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Add enrollment' })).not.toBeInTheDocument();
    for (const action of ['Edit', 'Activate', 'Suspend', 'Expire', 'Graduate', 'Restore', 'Revoke']) {
      expect(within(dialog).queryByRole('button', { name: action })).not.toBeInTheDocument();
    }
    expect(within(dialog).getByText('CPA · CPA')).toBeInTheDocument();
    expect(enrollmentMocks.update).not.toHaveBeenCalled();
    expect(enrollmentMocks.revoke).not.toHaveBeenCalled();
  });
});
