import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { demoAgents } from '@/lib/demo-data';
import { ConversationsPage } from '@/pages/ConversationsPage';
import type { Agent, Conversation, PageResult } from '@/types';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  agentList: vi.fn(),
  conversationList: vi.fn(),
  resolve: vi.fn(),
  resolveEducationSalesIntent: vi.fn(),
  educationSalesSettings: vi.fn(),
  updateState: vi.fn(),
  reply: vi.fn(),
  courseList: vi.fn(),
  batchList: vi.fn(),
  enrollmentList: vi.fn(),
  studentList: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
  useWorkspace: () => ({ activeWorkspace: { id: 'workspace-1', name: 'NorthStar Academy' } }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    agents: { list: mocks.agentList },
    conversations: { updateState: mocks.updateState, reply: mocks.reply },
  },
}));

vi.mock('@/lib/conversation-api', () => ({
  conversationApi: {
    list: mocks.conversationList,
    resolve: mocks.resolve,
    resolveEducationSalesIntent: mocks.resolveEducationSalesIntent,
  },
}));

vi.mock('@/lib/education-sales-settings-api', () => ({
  educationSalesSettingsApi: { get: mocks.educationSalesSettings },
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

const emptyPage: PageResult<Conversation> = { items: [], total: 0, page: 1, pageSize: 50 };

function agent(id: string, name: string, purpose: Agent['purpose']): Agent {
  return { ...structuredClone(demoAgents[0]!), id, name, purpose };
}

describe('ConversationsPage Education filters', () => {
  beforeEach(() => {
    mocks.educationSalesSettings.mockResolvedValue({ createUpsellLeads: false });
    mocks.agentList.mockResolvedValue([
      agent('education-agent', 'CPA Mentor', 'education'),
      agent('support-agent', 'Support Agent', 'support'),
    ]);
    mocks.conversationList.mockResolvedValue(emptyPage);
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
    mocks.updateState.mockResolvedValue(undefined);
    mocks.reply.mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('reveals Education scope only for Education Agents and cascades Course → Batch → Student', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);

    expect(await screen.findByRole('combobox', { name: 'Filter by agent' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Education conversation filters')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByRole('combobox', { name: 'Filter by agent' }), 'education-agent');

    expect(await screen.findByLabelText('Education conversation filters')).toBeInTheDocument();
    const course = screen.getByRole('combobox', { name: 'Filter by course' });
    const batch = screen.getByRole('combobox', { name: 'Filter by batch' });
    const student = screen.getByRole('combobox', { name: 'Filter by student' });
    expect(batch).toBeDisabled();
    expect(student).toBeDisabled();
    await waitFor(() => expect(mocks.conversationList).toHaveBeenCalledWith(expect.objectContaining({
      agentId: 'education-agent', educationScope: true,
    }), expect.any(AbortSignal)));
    expect(await screen.findByRole('option', { name: 'CPA · CPA Program' })).toBeInTheDocument();

    await user.selectOptions(course, 'course-1');
    await waitFor(() => expect(mocks.batchList).toHaveBeenCalledWith({ courseId: 'course-1', status: 'active' }));
    expect(await screen.findByRole('option', { name: 'CPA-26 · CPA 2026' })).toBeInTheDocument();
    expect(batch).not.toBeDisabled();

    await user.selectOptions(batch, 'batch-1');
    await waitFor(() => expect(mocks.enrollmentList).toHaveBeenCalledWith({
      agentId: 'education-agent', courseId: 'course-1', batchId: 'batch-1',
    }));
    expect(await screen.findByRole('option', { name: 'NS-1001 · Asha Student' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Unassigned Student/ })).not.toBeInTheDocument();
    expect(student).not.toBeDisabled();

    await user.selectOptions(student, 'student-1');
    await waitFor(() => expect(mocks.conversationList).toHaveBeenCalledWith(expect.objectContaining({
      agentId: 'education-agent',
      educationScope: true,
      courseId: 'course-1',
      batchId: 'batch-1',
      studentId: 'student-1',
    }), expect.any(AbortSignal)));
  });

  it('removes Education scope again when switching to a non-Education Agent', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);
    const agentFilter = await screen.findByRole('combobox', { name: 'Filter by agent' });

    await user.selectOptions(agentFilter, 'education-agent');
    expect(await screen.findByLabelText('Education conversation filters')).toBeInTheDocument();

    await user.selectOptions(agentFilter, 'support-agent');
    await waitFor(() => expect(screen.queryByLabelText('Education conversation filters')).not.toBeInTheDocument());
    await waitFor(() => expect(mocks.conversationList).toHaveBeenCalledWith(expect.objectContaining({
      agentId: 'support-agent',
      educationScope: false,
      courseId: undefined,
      batchId: undefined,
      studentId: undefined,
    }), expect.any(AbortSignal)));
  });
});
