import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/providers';
import { BatchesPage } from '@/pages/BatchesPage';
import type {
  BatchCreateInput,
  BatchPatchInput,
  EducationBatch,
  EducationCourse,
} from '@/lib/education-api';

const apiMocks = vi.hoisted(() => ({
  listCourses: vi.fn<() => Promise<EducationCourse[]>>(),
  listBatches: vi.fn<() => Promise<EducationBatch[]>>(),
  createBatch: vi.fn<(input: BatchCreateInput) => Promise<EducationBatch>>(),
  updateBatch: vi.fn<(batchId: string, patch: BatchPatchInput) => Promise<EducationBatch>>(),
  archiveBatch: vi.fn<(batchId: string) => Promise<void>>(),
}));

vi.mock('@/lib/education-api', () => ({
  educationApi: {
    courses: { list: apiMocks.listCourses },
    batches: {
      list: apiMocks.listBatches,
      create: apiMocks.createBatch,
      update: apiMocks.updateBatch,
      archive: apiMocks.archiveBatch,
    },
  },
}));

describe('BatchesPage', () => {
  let courses: EducationCourse[];
  let batches: EducationBatch[];

  beforeEach(() => {
    courses = [
      {
        id: 'course-1',
        tenantId: 'tenant-1',
        workspaceId: 'workspace-1',
        code: 'CPA-CORE',
        name: 'CPA Core',
        description: 'CPA curriculum',
        status: 'active',
        createdAt: '2026-09-01T10:00:00.000Z',
        updatedAt: '2026-09-01T10:00:00.000Z',
      },
      {
        id: 'course-2',
        tenantId: 'tenant-1',
        workspaceId: 'workspace-1',
        code: 'CMA-P1',
        name: 'CMA Part 1',
        description: 'CMA curriculum',
        status: 'archived',
        createdAt: '2026-09-01T10:00:00.000Z',
        updatedAt: '2026-09-01T10:00:00.000Z',
      },
    ];
    batches = [{
      id: 'batch-1',
      tenantId: 'tenant-1',
      workspaceId: 'workspace-1',
      courseId: 'course-1',
      code: 'CPA-2026-A',
      name: 'CPA 2026 Cohort A',
      description: 'Morning cohort',
      startsOn: '2026-09-15',
      endsOn: '2027-03-31',
      status: 'active',
      createdAt: '2026-09-01T10:00:00.000Z',
      updatedAt: '2026-09-01T10:00:00.000Z',
    }];

    apiMocks.listCourses.mockImplementation(async () => structuredClone(courses));
    apiMocks.listBatches.mockImplementation(async () => structuredClone(batches));
    apiMocks.createBatch.mockImplementation(async (input) => {
      const now = new Date().toISOString();
      const created: EducationBatch = {
        id: 'batch-2',
        tenantId: 'tenant-1',
        workspaceId: 'workspace-1',
        courseId: input.courseId,
        code: input.code.toUpperCase(),
        name: input.name,
        description: input.description ?? '',
        startsOn: input.startsOn ?? null,
        endsOn: input.endsOn ?? null,
        status: 'active',
        createdAt: now,
        updatedAt: now,
      };
      batches.push(created);
      return structuredClone(created);
    });
    apiMocks.updateBatch.mockImplementation(async (batchId, patch) => {
      const index = batches.findIndex((batch) => batch.id === batchId);
      if (index < 0) throw new Error('Batch not found');
      batches[index] = {
        ...batches[index]!,
        ...patch,
        code: patch.code?.toUpperCase() ?? batches[index]!.code,
        updatedAt: new Date().toISOString(),
      };
      return structuredClone(batches[index]!);
    });
    apiMocks.archiveBatch.mockImplementation(async (batchId) => {
      const index = batches.findIndex((batch) => batch.id === batchId);
      if (index < 0) throw new Error('Batch not found');
      batches[index] = { ...batches[index]!, status: 'archived', updatedAt: new Date().toISOString() };
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('creates and edits a batch linked to an active course', async () => {
    const user = userEvent.setup();
    render(<ToastProvider><BatchesPage /></ToastProvider>);

    expect(await screen.findByText('CPA 2026 Cohort A')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create batch' }));
    const createDialog = screen.getByRole('dialog');
    expect(within(createDialog).getByLabelText('Course')).toHaveValue('course-1');
    expect(within(createDialog).queryByRole('option', { name: /CMA-P1/ })).not.toBeInTheDocument();
    await user.type(within(createDialog).getByLabelText('Batch code'), 'cpa-2026-b');
    await user.type(within(createDialog).getByLabelText('Batch name'), 'CPA 2026 Cohort B');
    await user.type(within(createDialog).getByLabelText('Description'), 'Evening cohort');
    fireEvent.change(within(createDialog).getByLabelText('Start date'), { target: { value: '2026-10-01' } });
    fireEvent.change(within(createDialog).getByLabelText('End date'), { target: { value: '2027-04-30' } });
    await user.click(within(createDialog).getByRole('button', { name: 'Create batch' }));

    await waitFor(() => expect(apiMocks.createBatch).toHaveBeenCalledWith({
      courseId: 'course-1',
      code: 'CPA-2026-B',
      name: 'CPA 2026 Cohort B',
      description: 'Evening cohort',
      startsOn: '2026-10-01',
      endsOn: '2027-04-30',
    }));
    expect(await screen.findByText('CPA 2026 Cohort B')).toBeInTheDocument();

    const editButtons = screen.getAllByRole('button', { name: 'Edit' });
    await user.click(editButtons.at(-1)!);
    const editDialog = screen.getByRole('dialog');
    expect(within(editDialog).getByLabelText('Course')).toBeDisabled();
    const nameInput = within(editDialog).getByLabelText('Batch name');
    await user.clear(nameInput);
    await user.type(nameInput, 'CPA 2026 Evening Program');
    await user.click(within(editDialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(apiMocks.updateBatch).toHaveBeenCalledWith('batch-2', {
      code: 'CPA-2026-B',
      name: 'CPA 2026 Evening Program',
      description: 'Evening cohort',
      startsOn: '2026-10-01',
      endsOn: '2027-04-30',
    }));
    expect(await screen.findByText('CPA 2026 Evening Program')).toBeInTheDocument();
  });

  it('archives, filters, and reactivates a batch without deleting it', async () => {
    const user = userEvent.setup();
    render(<ToastProvider><BatchesPage /></ToastProvider>);

    expect(await screen.findByText('CPA 2026 Cohort A')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Archive' }));
    const archiveDialog = screen.getByRole('dialog');
    expect(within(archiveDialog).getByRole('heading', { name: 'Archive batch?' })).toBeInTheDocument();
    await user.click(within(archiveDialog).getByRole('button', { name: 'Archive batch' }));

    await waitFor(() => expect(apiMocks.archiveBatch).toHaveBeenCalledWith('batch-1'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Reactivate' })).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText('Filter batches by status'), 'archived');
    expect(screen.getByText('CPA 2026 Cohort A')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Filter batches by course'), 'course-1');
    expect(screen.getByText('CPA 2026 Cohort A')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Reactivate' }));
    await waitFor(() => expect(apiMocks.updateBatch).toHaveBeenCalledWith('batch-1', { status: 'active' }));

    await user.selectOptions(screen.getByLabelText('Filter batches by status'), 'active');
    expect(await screen.findByText('CPA 2026 Cohort A')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Search batches'), 'CPA Core');
    expect(screen.getByText('CPA 2026 Cohort A')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Search batches'));
    await user.type(screen.getByLabelText('Search batches'), 'ACCA');
    expect(screen.queryByText('CPA 2026 Cohort A')).not.toBeInTheDocument();
  });

  it('blocks an invalid date range before calling the API', async () => {
    const user = userEvent.setup();
    render(<ToastProvider><BatchesPage /></ToastProvider>);

    expect(await screen.findByText('CPA 2026 Cohort A')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create batch' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Batch code'), { target: { value: 'CPA-BAD-DATES' } });
    fireEvent.change(within(dialog).getByLabelText('Batch name'), { target: { value: 'Bad Date Batch' } });
    fireEvent.change(within(dialog).getByLabelText('Start date'), { target: { value: '2026-12-01' } });
    fireEvent.change(within(dialog).getByLabelText('End date'), { target: { value: '2026-11-01' } });
    await user.click(within(dialog).getByRole('button', { name: 'Create batch' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Batch end date cannot be before start date.');
    expect(apiMocks.createBatch).not.toHaveBeenCalled();
  });
});
