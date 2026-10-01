import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/providers';
import { CoursesPage } from '@/pages/CoursesPage';
import type {
  CourseCreateInput,
  CoursePatchInput,
  EducationCourse,
} from '@/lib/education-api';

const apiMocks = vi.hoisted(() => ({
  list: vi.fn<() => Promise<EducationCourse[]>>(),
  create: vi.fn<(input: CourseCreateInput) => Promise<EducationCourse>>(),
  update: vi.fn<(courseId: string, patch: CoursePatchInput) => Promise<EducationCourse>>(),
  archive: vi.fn<(courseId: string) => Promise<void>>(),
}));

vi.mock('@/lib/education-api', () => ({
  educationApi: { courses: apiMocks },
}));

describe('CoursesPage', () => {
  let records: EducationCourse[];

  beforeEach(() => {
    records = [{
      id: 'course-1',
      tenantId: 'tenant-1',
      workspaceId: 'workspace-1',
      code: 'CMA-P1',
      name: 'CMA Part 1',
      description: 'Financial planning course',
      status: 'active',
      createdAt: '2026-09-01T10:00:00.000Z',
      updatedAt: '2026-09-01T10:00:00.000Z',
    }];
    apiMocks.list.mockImplementation(async () => structuredClone(records));
    apiMocks.create.mockImplementation(async (input) => {
      const now = new Date().toISOString();
      const created: EducationCourse = {
        id: 'course-2',
        tenantId: 'tenant-1',
        workspaceId: 'workspace-1',
        code: input.code.toUpperCase(),
        name: input.name,
        description: input.description ?? '',
        status: 'active',
        createdAt: now,
        updatedAt: now,
      };
      records.push(created);
      return structuredClone(created);
    });
    apiMocks.update.mockImplementation(async (courseId, patch) => {
      const index = records.findIndex((course) => course.id === courseId);
      if (index < 0) throw new Error('Course not found');
      records[index] = {
        ...records[index]!,
        ...patch,
        code: patch.code?.toUpperCase() ?? records[index]!.code,
        updatedAt: new Date().toISOString(),
      };
      return structuredClone(records[index]!);
    });
    apiMocks.archive.mockImplementation(async (courseId) => {
      const index = records.findIndex((course) => course.id === courseId);
      if (index < 0) throw new Error('Course not found');
      records[index] = { ...records[index]!, status: 'archived', updatedAt: new Date().toISOString() };
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('creates and edits a workspace course', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ToastProvider><CoursesPage /></ToastProvider></MemoryRouter>);

    expect(await screen.findByText('CMA Part 1')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create course' }));
    const createDialog = screen.getByRole('dialog', { name: 'Create course' });
    await user.type(within(createDialog).getByLabelText('Course code'), 'cpa-core');
    await user.type(within(createDialog).getByLabelText('Course name'), 'CPA Core');
    await user.type(within(createDialog).getByLabelText('Description'), 'CPA foundation curriculum');
    await user.click(within(createDialog).getByRole('button', { name: 'Create course' }));

    await waitFor(() => expect(apiMocks.create).toHaveBeenCalledWith({
      code: 'CPA-CORE',
      name: 'CPA Core',
      description: 'CPA foundation curriculum',
    }));
    expect(await screen.findByText('CPA Core')).toBeInTheDocument();

    const editButtons = screen.getAllByRole('button', { name: 'Edit' });
    await user.click(editButtons.at(-1)!);
    const editDialog = screen.getByRole('dialog', { name: 'Edit course' });
    const nameInput = within(editDialog).getByLabelText('Course name');
    await user.clear(nameInput);
    await user.type(nameInput, 'CPA Core Program');
    await user.click(within(editDialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledWith('course-2', {
      code: 'CPA-CORE',
      name: 'CPA Core Program',
      description: 'CPA foundation curriculum',
    }));
    expect(await screen.findByText('CPA Core Program')).toBeInTheDocument();
  });

  it('archives, filters, and reactivates a course without deleting it', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ToastProvider><CoursesPage /></ToastProvider></MemoryRouter>);

    expect(await screen.findByText('CMA Part 1')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Archive' }));
    expect(screen.getByRole('heading', { name: 'Archive course?' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Archive course' }));

    await waitFor(() => expect(apiMocks.archive).toHaveBeenCalledWith('course-1'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Reactivate' })).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText('Filter courses by status'), 'active');
    expect(screen.queryByText('CMA Part 1')).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Filter courses by status'), 'archived');
    expect(screen.getByText('CMA Part 1')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Reactivate' }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledWith('course-1', { status: 'active' }));

    await user.selectOptions(screen.getByLabelText('Filter courses by status'), 'active');
    expect(await screen.findByText('CMA Part 1')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Search courses'), 'financial');
    expect(screen.getByText('CMA Part 1')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Search courses'));
    await user.type(screen.getByLabelText('Search courses'), 'ACCA');
    expect(screen.queryByText('CMA Part 1')).not.toBeInTheDocument();
  });
});
