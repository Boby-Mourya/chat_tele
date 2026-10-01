import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { EducationEnrollmentsPage } from '@/pages/EducationEnrollmentsPage';

const mocks = vi.hoisted(() => ({
  agentList: vi.fn(),
  enrollmentList: vi.fn(),
  studentList: vi.fn(),
  courseList: vi.fn(),
  batchList: vi.fn(),
}));
vi.mock('@/lib/education-enrollment-events-api', () => ({ enrollmentReadiness: vi.fn().mockResolvedValue({ whatsappConnected: true, verifiedStudentNumbers: 1, pendingStudentNumbers: 0, knowledgeSources: 1, aiProviderConfigured: true }) }));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: vi.fn() }),
  useWorkspace: () => ({ activeWorkspace: { id: 'workspace-1', name: 'NorthStar Academy' } }),
}));

vi.mock('@/components/student-enrollments-modal', () => ({
  StudentEnrollmentsModal: ({ student, open, onClose }: { student: { name: string } | null; open: boolean; onClose: () => void }) => (
    open && student ? <div role="dialog" aria-label="Enrollment manager">
      <span>Managing {student.name}</span>
      <button type="button" onClick={onClose}>Close enrollment manager</button>
    </div> : null
  ),
}));

vi.mock('@/lib/api', () => ({
  api: { agents: { list: mocks.agentList } },
}));

vi.mock('@/lib/education-enrollment-api', () => ({
  educationEnrollmentApi: { list: mocks.enrollmentList },
}));

vi.mock('@/lib/education-student-api', () => ({
  educationStudentApi: { list: mocks.studentList },
}));

vi.mock('@/lib/education-api', () => ({
  educationApi: {
    courses: { list: mocks.courseList },
    batches: { list: mocks.batchList },
  },
}));

const students = [
  {
    id: 'student-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentNumber: 'NS-1001',
    name: 'Asha Student', email: 'asha@example.com', customFields: {}, status: 'active',
    createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-09-12T04:00:00Z',
  },
  {
    id: 'student-2', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentNumber: 'NS-1002',
    name: 'Ravi Archived', email: 'ravi@example.com', customFields: {}, status: 'archived',
    createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-09-12T03:00:00Z',
  },
];

const courses = [
  { id: 'course-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'CPA', name: 'CPA Program', description: '', status: 'active', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' },
  { id: 'course-2', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'CMA', name: 'CMA Program', description: '', status: 'active', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' },
];

const batches = [
  { id: 'batch-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-1', code: 'CPA-26', name: 'CPA 2026', description: '', startsOn: null, endsOn: null, status: 'active', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' },
  { id: 'batch-2', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-2', code: 'CMA-26', name: 'CMA 2026', description: '', startsOn: null, endsOn: null, status: 'active', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' },
];

const agents = [
  { id: 'agent-1', publicId: 'agent-cpa', name: 'CPA Mentor', purpose: 'education' },
  { id: 'agent-2', publicId: 'agent-cma', name: 'CMA Mentor', purpose: 'education' },
  { id: 'support-agent', publicId: 'agent-support', name: 'Support Agent', purpose: 'support' },
];

const enrollments = [
  {
    id: 'enrollment-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentId: 'student-1',
    courseId: 'course-1', batchId: 'batch-1', agentId: 'agent-1', startsOn: '2026-01-01', endsOn: null,
    status: 'active', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-09-12T04:00:00Z',
  },
  {
    id: 'enrollment-2', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentId: 'student-2',
    courseId: 'course-2', batchId: 'batch-2', agentId: 'agent-2', startsOn: null, endsOn: '2026-12-31',
    status: 'suspended', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-09-12T03:00:00Z',
  },
];

describe('EducationEnrollmentsPage', () => {
  beforeEach(() => {
    mocks.agentList.mockResolvedValue(agents);
    mocks.enrollmentList.mockResolvedValue(enrollments);
    mocks.studentList.mockResolvedValue(students);
    mocks.courseList.mockResolvedValue(courses);
    mocks.batchList.mockResolvedValue(batches);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders the workspace enrollment directory and composes status, Course, Batch, Agent, and search filters', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><EducationEnrollmentsPage /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: 'Enrollments' })).toBeInTheDocument();
    expect(screen.getByText('Asha Student')).toBeInTheDocument();
    expect(screen.getByText('Ravi Archived')).toBeInTheDocument();
    const totalCard = screen.getByText('Total enrollments').closest('.card');
    expect(totalCard).not.toBeNull();
    expect(totalCard).toHaveTextContent('2');

    const agentFilter = screen.getByRole('combobox', { name: 'Filter enrollments by agent' });
    expect(within(agentFilter).queryByRole('option', { name: 'Support Agent' })).not.toBeInTheDocument();

    const statusFilter = screen.getByRole('combobox', { name: 'Filter enrollments by status' });
    await user.selectOptions(statusFilter, 'suspended');
    expect(screen.queryByText('Asha Student')).not.toBeInTheDocument();
    expect(screen.getByText('Ravi Archived')).toBeInTheDocument();

    await user.selectOptions(statusFilter, 'all');
    const courseFilter = screen.getByRole('combobox', { name: 'Filter enrollments by course' });
    await user.selectOptions(courseFilter, 'course-1');
    expect(screen.getByText('Asha Student')).toBeInTheDocument();
    expect(screen.queryByText('Ravi Archived')).not.toBeInTheDocument();

    const batchFilter = screen.getByRole('combobox', { name: 'Filter enrollments by batch' });
    expect(within(batchFilter).getByRole('option', { name: 'CPA-26 · CPA 2026' })).toBeInTheDocument();
    expect(within(batchFilter).queryByRole('option', { name: 'CMA-26 · CMA 2026' })).not.toBeInTheDocument();
    await user.selectOptions(batchFilter, 'batch-1');
    await user.selectOptions(agentFilter, 'agent-1');

    const search = screen.getByRole('textbox', { name: 'Search enrollments' });
    await user.type(search, 'asha@example.com');
    expect(screen.getByText('Asha Student')).toBeInTheDocument();
    await user.clear(search);
    await user.type(search, 'no-match');
    expect(screen.getByText('No matching enrollments')).toBeInTheDocument();
  });

  it('reuses the existing Student enrollment manager for row actions and new enrollment entry', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><EducationEnrollmentsPage /></MemoryRouter>);

    const asha = await screen.findByText('Asha Student');
    const ashaRow = asha.closest('tr');
    expect(ashaRow).not.toBeNull();
    await user.click(within(ashaRow!).getByRole('button', { name: 'Manage access' }));
    expect(screen.getByRole('dialog', { name: 'Enrollment manager' })).toHaveTextContent('Managing Asha Student');
    await user.click(screen.getByRole('button', { name: 'Close enrollment manager' }));
    await waitFor(() => expect(mocks.enrollmentList).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole('button', { name: 'Add enrollment' }));
    const studentPicker = screen.getByRole('combobox', { name: 'Choose active student' });
    expect(within(studentPicker).getByRole('option', { name: 'NS-1001 · Asha Student' })).toBeInTheDocument();
    expect(within(studentPicker).queryByRole('option', { name: /Ravi Archived/ })).not.toBeInTheDocument();
    await user.selectOptions(studentPicker, 'student-1');
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(screen.getByRole('dialog', { name: 'Enrollment manager' })).toHaveTextContent('Managing Asha Student');
  });

  it('groups one student’s multiple courses and shows the complete course count', async () => {
    mocks.enrollmentList.mockResolvedValue([
      enrollments[0],
      {
        ...enrollments[0],
        id: 'enrollment-3',
        courseId: 'course-2',
        batchId: 'batch-2',
        agentId: 'agent-2',
        updatedAt: '2026-09-13T04:00:00Z',
      },
      enrollments[1],
    ]);

    render(<MemoryRouter><EducationEnrollmentsPage /></MemoryRouter>);

    const student = await screen.findByText('Asha Student');
    const studentCell = student.closest('td');
    expect(studentCell).not.toBeNull();
    expect(studentCell).toHaveAttribute('rowspan', '2');
    expect(within(studentCell!).getByText('2 courses')).toHaveAttribute('title', 'CPA Program, CMA Program');
    expect(screen.getAllByRole('button', { name: 'Manage access' })).toHaveLength(2);
  });
});
