import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { EducationActivityPage } from '@/pages/EducationActivityPage';

const mocks = vi.hoisted(() => ({
  agentList: vi.fn(),
  activityList: vi.fn(),
  courseList: vi.fn(),
  batchList: vi.fn(),
  enrollmentList: vi.fn(),
  studentList: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useWorkspace: () => ({ activeWorkspace: { id: 'workspace-1', name: 'NorthStar Academy' } }),
}));

vi.mock('@/lib/api', () => ({
  api: { agents: { list: mocks.agentList } },
}));

vi.mock('@/lib/education-activity-api', () => ({
  educationActivityApi: { list: mocks.activityList },
}));

vi.mock('@/lib/education-api', () => ({
  educationApi: {
    courses: { list: mocks.courseList },
    batches: { list: mocks.batchList },
  },
}));

vi.mock('@/lib/education-enrollment-api', () => ({
  educationEnrollmentApi: { list: mocks.enrollmentList },
}));

vi.mock('@/lib/education-student-api', () => ({
  educationStudentApi: { list: mocks.studentList },
}));

const activityItem = {
  id: 'activity-1',
  eventType: 'conversation.resolved',
  studentId: 'student-1',
  studentNumber: 'NS-1001',
  studentName: 'Asha Student',
  studentEmail: 'asha@example.com',
  enrollmentId: 'enrollment-1',
  courseId: 'course-1',
  courseCode: 'CPA',
  courseName: 'CPA Program',
  batchId: 'batch-1',
  batchCode: 'CPA-26',
  batchName: 'CPA 2026',
  agentId: 'education-agent',
  agentPublicId: 'agent-cpa',
  agentName: 'CPA Mentor',
  conversationId: 'conversation-1',
  conversationPublicId: 'conv-cpa-1',
  resolution: 'answered',
  resolvedAt: '2026-09-12T04:00:00Z',
  actorUserId: null,
  details: { topic: 'financial reporting' },
  createdAt: '2026-09-12T04:00:00Z',
};

describe('EducationActivityPage', () => {
  beforeEach(() => {
    mocks.agentList.mockResolvedValue([
      { id: 'education-agent', name: 'CPA Mentor', purpose: 'education' },
      { id: 'support-agent', name: 'Support Agent', purpose: 'support' },
    ]);
    mocks.activityList.mockResolvedValue({ items: [activityItem], total: 1, page: 1, pageSize: 50 });
    mocks.courseList.mockResolvedValue([
      {
        id: 'course-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'CPA', name: 'CPA Program',
        description: '', status: 'active', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
      },
    ]);
    mocks.batchList.mockResolvedValue([
      {
        id: 'batch-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-1', code: 'CPA-26',
        name: 'CPA 2026', description: '', startsOn: null, endsOn: null, status: 'active',
        createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
      },
    ]);
    mocks.enrollmentList.mockResolvedValue([
      {
        id: 'enrollment-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentId: 'student-1',
        courseId: 'course-1', batchId: 'batch-1', agentId: 'education-agent', startsOn: null, endsOn: null,
        status: 'active', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
      },
    ]);
    mocks.studentList.mockResolvedValue([
      {
        id: 'student-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentNumber: 'NS-1001',
        name: 'Asha Student', email: 'asha@example.com', customFields: {}, status: 'active',
        createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
      },
      {
        id: 'student-2', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentNumber: 'NS-1002',
        name: 'Unassigned Student', email: null, customFields: {}, status: 'active',
        createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z',
      },
    ]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders enriched activity and cascades Agent → Course → Batch → Student filters', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><EducationActivityPage /></MemoryRouter>);

    expect(await screen.findByText('Asha Student')).toBeInTheDocument();
    expect(screen.getAllByText('CPA · CPA Program').length).toBeGreaterThan(0);
    expect(screen.getAllByText('CPA-26 · CPA 2026').length).toBeGreaterThan(0);
    expect(screen.getByText('conv-cpa-1')).toBeInTheDocument();

    const agent = screen.getByRole('combobox', { name: 'Filter by agent' });
    expect(screen.queryByRole('option', { name: 'Support Agent' })).not.toBeInTheDocument();
    await user.selectOptions(agent, 'education-agent');

    const course = screen.getByRole('combobox', { name: 'Filter by course' });
    const batch = screen.getByRole('combobox', { name: 'Filter by batch' });
    const student = screen.getByRole('combobox', { name: 'Filter by student' });
    expect(batch).toBeDisabled();
    expect(student).toBeDisabled();

    await user.selectOptions(course, 'course-1');
    await waitFor(() => expect(mocks.batchList).toHaveBeenCalledWith({ courseId: 'course-1', status: 'active' }));
    expect(await screen.findByRole('option', { name: 'CPA-26 · CPA 2026' })).toBeInTheDocument();
    expect(batch).not.toBeDisabled();

    await user.selectOptions(batch, 'batch-1');
    await waitFor(() => expect(mocks.enrollmentList).toHaveBeenCalledWith({
      courseId: 'course-1', batchId: 'batch-1', agentId: 'education-agent',
    }));
    expect(await screen.findByRole('option', { name: 'NS-1001 · Asha Student' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Unassigned Student/ })).not.toBeInTheDocument();
    expect(student).not.toBeDisabled();

    await user.selectOptions(student, 'student-1');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Filter by event type' }), 'conversation.resolved');
    await waitFor(() => expect(mocks.activityList).toHaveBeenCalledWith(expect.objectContaining({
      agentId: 'education-agent',
      courseId: 'course-1',
      batchId: 'batch-1',
      studentId: 'student-1',
      eventType: 'conversation.resolved',
    })));
  });

  it('resets dependent Education scope when the Agent changes', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><EducationActivityPage /></MemoryRouter>);

    const agent = await screen.findByRole('combobox', { name: 'Filter by agent' });
    await user.selectOptions(agent, 'education-agent');
    const course = screen.getByRole('combobox', { name: 'Filter by course' });
    await user.selectOptions(course, 'course-1');
    const batch = screen.getByRole('combobox', { name: 'Filter by batch' });
    expect(await screen.findByRole('option', { name: 'CPA-26 · CPA 2026' })).toBeInTheDocument();
    await user.selectOptions(batch, 'batch-1');
    expect(await screen.findByRole('option', { name: 'NS-1001 · Asha Student' })).toBeInTheDocument();

    await user.selectOptions(agent, 'all');

    expect(course).toHaveValue('all');
    expect(batch).toHaveValue('all');
    expect(screen.getByRole('combobox', { name: 'Filter by student' })).toHaveValue('all');
  });
});
