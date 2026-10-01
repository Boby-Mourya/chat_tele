import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EducationKnowledgeScopeManager } from '@/components/education-knowledge-scope-manager';
import { ToastProvider } from '@/components/providers';
import type { EducationBatch, EducationCourse } from '@/lib/education-api';
import type { EducationKnowledgeScope } from '@/lib/education-knowledge-api';
import type { KnowledgeSource } from '@/types';

const mocks = vi.hoisted(() => ({
  courses: vi.fn<() => Promise<EducationCourse[]>>(),
  batches: vi.fn<() => Promise<EducationBatch[]>>(),
  sourceScopes: vi.fn<(sourceId: string) => Promise<EducationKnowledgeScope[]>>(),
  setSourceScopes: vi.fn(),
}));

vi.mock('@/lib/education-api', () => ({
  educationApi: {
    courses: { list: mocks.courses },
    batches: { list: mocks.batches },
  },
}));

vi.mock('@/lib/education-knowledge-api', () => ({
  educationKnowledgeApi: {
    sourceScopes: mocks.sourceScopes,
    setSourceScopes: mocks.setSourceScopes,
  },
}));

const source: KnowledgeSource = {
  id: 'source-1',
  agentId: 'agent-education',
  name: 'CPA Handbook',
  kind: 'text',
  status: 'ready',
  sizeLabel: '20 words',
  chunks: 3,
  updatedAt: '2026-09-10T00:00:00.000Z',
  content: 'CPA private knowledge',
};

const courses: EducationCourse[] = [
  {
    id: 'course-cpa', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'CPA',
    name: 'CPA', description: '', status: 'active', createdAt: '', updatedAt: '',
  },
  {
    id: 'course-cma', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'CMA',
    name: 'CMA', description: '', status: 'active', createdAt: '', updatedAt: '',
  },
];

const batches: EducationBatch[] = [
  {
    id: 'batch-cpa-a', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-cpa',
    code: 'CPA-A', name: 'CPA Batch A', description: '', startsOn: null, endsOn: null,
    status: 'active', createdAt: '', updatedAt: '',
  },
  {
    id: 'batch-cma-a', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-cma',
    code: 'CMA-A', name: 'CMA Batch A', description: '', startsOn: null, endsOn: null,
    status: 'active', createdAt: '', updatedAt: '',
  },
];

describe('EducationKnowledgeScopeManager', () => {
  beforeEach(() => {
    mocks.courses.mockResolvedValue(courses);
    mocks.batches.mockResolvedValue(batches);
    mocks.sourceScopes.mockResolvedValue([]);
    mocks.setSourceScopes.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('marks unscoped Education knowledge as blocked and saves a Course/Batch pair', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <EducationKnowledgeScopeManager agentId="agent-education" sources={[source]} />
      </ToastProvider>,
    );

    expect(await screen.findByText('Unscoped · blocked')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Manage scope' }));

    const courseSelect = screen.getByLabelText('Course');
    const batchSelect = screen.getByLabelText('Batch');
    await user.selectOptions(courseSelect, 'course-cpa');
    expect(screen.getByRole('option', { name: /CPA-A/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /CMA-A/ })).not.toBeInTheDocument();
    await user.selectOptions(batchSelect, 'batch-cpa-a');
    await user.click(screen.getByRole('button', { name: 'Add pair' }));
    expect(screen.getByText('CPA · CPA-A')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Save scope' }));
    await waitFor(() => expect(mocks.setSourceScopes).toHaveBeenCalledWith(
      source.id,
      'agent-education',
      [{ courseId: 'course-cpa', batchId: 'batch-cpa-a' }],
    ));
    await waitFor(() => expect(screen.queryByText(/Education scope · CPA Handbook/)).not.toBeInTheDocument());
  });

  it('prevents duplicate Course/Batch pairs before submitting', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <EducationKnowledgeScopeManager agentId="agent-education" sources={[source]} />
      </ToastProvider>,
    );
    await screen.findByText('Unscoped · blocked');
    await user.click(screen.getByRole('button', { name: 'Manage scope' }));

    for (let index = 0; index < 2; index += 1) {
      await user.selectOptions(screen.getByLabelText('Course'), 'course-cpa');
      await user.selectOptions(screen.getByLabelText('Batch'), 'batch-cpa-a');
      await user.click(screen.getByRole('button', { name: 'Add pair' }));
    }

    expect(screen.getByRole('alert')).toHaveTextContent('already selected');
    expect(mocks.setSourceScopes).not.toHaveBeenCalled();
  });
});
