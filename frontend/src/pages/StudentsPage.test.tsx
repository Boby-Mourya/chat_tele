import { MemoryRouter } from 'react-router-dom';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/providers';
import { StudentsPage } from '@/pages/StudentsPage';
import type {
  EducationStudent,
  StudentCreateInput,
  StudentPatchInput,
} from '@/lib/education-student-api';

const apiMocks = vi.hoisted(() => ({
  list: vi.fn<() => Promise<EducationStudent[]>>(),
  create: vi.fn<(input: StudentCreateInput) => Promise<EducationStudent>>(),
  update: vi.fn<(studentId: string, patch: StudentPatchInput) => Promise<EducationStudent>>(),
  archive: vi.fn<(studentId: string) => Promise<void>>(),
}));

vi.mock('@/lib/education-student-api', () => ({
  educationStudentApi: apiMocks,
}));

describe('StudentsPage', () => {
  let students: EducationStudent[];

  beforeEach(() => {
    students = [{
      id: 'student-1',
      tenantId: 'tenant-1',
      workspaceId: 'workspace-1',
      studentNumber: 'NS-1001',
      name: 'Asha Verma',
      email: 'asha@example.com',
      customFields: { language: 'English', city: 'Patna' },
      status: 'active',
      createdAt: '2026-09-01T10:00:00.000Z',
      updatedAt: '2026-09-01T10:00:00.000Z',
    }];

    apiMocks.list.mockImplementation(async () => structuredClone(students));
    apiMocks.create.mockImplementation(async (input) => {
      const now = new Date().toISOString();
      const created: EducationStudent = {
        whatsappNumber: input.whatsappNumber,
        whatsappVerified: input.whatsappVerified,
        telegramPhoneNumber: input.telegramPhoneNumber,
        telegramPhoneVerified: input.telegramPhoneVerified,
        id: 'student-2',
        tenantId: 'tenant-1',
        workspaceId: 'workspace-1',
        studentNumber: input.studentNumber.trim().toUpperCase(),
        name: input.name.trim(),
        email: input.email ?? null,
        customFields: input.customFields ?? {},
        status: 'active',
        createdAt: now,
        updatedAt: now,
      };
      students.push(created);
      return structuredClone(created);
    });
    apiMocks.update.mockImplementation(async (studentId, patch) => {
      const index = students.findIndex((student) => student.id === studentId);
      if (index < 0) throw new Error('Student not found');
      students[index] = {
        ...students[index]!,
        ...patch,
        studentNumber: patch.studentNumber?.trim().toUpperCase() ?? students[index]!.studentNumber,
        updatedAt: new Date().toISOString(),
      };
      return structuredClone(students[index]!);
    });
    apiMocks.archive.mockImplementation(async (studentId) => {
      const index = students.findIndex((student) => student.id === studentId);
      if (index < 0) throw new Error('Student not found');
      students[index] = { ...students[index]!, status: 'archived', updatedAt: new Date().toISOString() };
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('creates and edits a student profile with custom fields', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ToastProvider><StudentsPage /></ToastProvider></MemoryRouter>);

    expect(await screen.findByText('Asha Verma')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add student' }));
    const createDialog = screen.getByRole('dialog');
    await user.type(within(createDialog).getByLabelText('Student ID'), 'ns-1002');
    await user.type(within(createDialog).getByLabelText('Student name'), 'Riya Singh');
    await user.type(within(createDialog).getByLabelText('Email'), 'RIYA@EXAMPLE.COM');
    await user.type(within(createDialog).getByLabelText('Student WhatsApp number'), '+919876540123');
    await user.click(within(createDialog).getByRole('checkbox', { name: /I have confirmed/ }));
    await user.type(within(createDialog).getByLabelText('Student Telegram phone number'), '+919876543210');
    await user.click(within(createDialog).getByRole('checkbox', { name: /confirmed this Telegram phone number/ }));
    await user.click(within(createDialog).getByRole('button', { name: 'Add field' }));
    await user.type(within(createDialog).getByLabelText('Custom field name'), 'language');
    await user.type(within(createDialog).getByLabelText('Custom field value'), 'Hindi');
    await user.click(within(createDialog).getByRole('button', { name: 'Add student' }));

    await waitFor(() => expect(apiMocks.create).toHaveBeenCalledWith({
      studentNumber: 'NS-1002',
      name: 'Riya Singh',
      email: 'riya@example.com',
      whatsappNumber: '+919876540123',
      whatsappVerified: true,
      telegramPhoneNumber: '+919876543210',
      telegramPhoneVerified: true,
      customFields: { language: 'Hindi' },
    }));
    expect(await screen.findByText('Riya Singh')).toBeInTheDocument();

    const editButtons = screen.getAllByRole('button', { name: 'Edit' });
    await user.click(editButtons.at(-1)!);
    const editDialog = screen.getByRole('dialog');
    const nameInput = within(editDialog).getByLabelText('Student name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Riya S. Singh');
    await user.click(within(editDialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledWith('student-2', {
      studentNumber: 'NS-1002',
      name: 'Riya S. Singh',
      email: 'riya@example.com',
      whatsappNumber: '+919876540123',
      whatsappVerified: true,
      telegramPhoneNumber: '+919876543210',
      telegramPhoneVerified: true,
      customFields: { language: 'Hindi' },
    }));
    expect(await screen.findByText('Riya S. Singh')).toBeInTheDocument();
  });

  it('archives, filters, searches, and reactivates without deleting the student', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ToastProvider><StudentsPage /></ToastProvider></MemoryRouter>);

    expect(await screen.findByText('Asha Verma')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Archive' }));
    const archiveDialog = screen.getByRole('dialog');
    await user.click(within(archiveDialog).getByRole('button', { name: 'Archive student' }));

    await waitFor(() => expect(apiMocks.archive).toHaveBeenCalledWith('student-1'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Reactivate' })).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText('Filter students by status'), 'archived');
    expect(screen.getByText('Asha Verma')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reactivate' }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledWith('student-1', { status: 'active' }));

    await user.selectOptions(screen.getByLabelText('Filter students by status'), 'active');
    expect(await screen.findByText('Asha Verma')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Search students'), 'Patna');
    expect(screen.getByText('Asha Verma')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Search students'));
    await user.type(screen.getByLabelText('Search students'), 'missing');
    expect(screen.queryByText('Asha Verma')).not.toBeInTheDocument();
  });

  it('blocks duplicate custom field names before calling the API', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ToastProvider><StudentsPage /></ToastProvider></MemoryRouter>);

    expect(await screen.findByText('Asha Verma')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add student' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Student ID'), { target: { value: 'NS-2001' } });
    fireEvent.change(within(dialog).getByLabelText('Student name'), { target: { value: 'Duplicate Fields' } });
    await user.click(within(dialog).getByRole('button', { name: 'Add field' }));
    await user.click(within(dialog).getByRole('button', { name: 'Add field' }));
    const names = within(dialog).getAllByLabelText('Custom field name');
    fireEvent.change(names[0]!, { target: { value: 'Language' } });
    fireEvent.change(names[1]!, { target: { value: 'language' } });
    await user.click(within(dialog).getByRole('button', { name: 'Add student' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Custom field names must be unique.');
    expect(apiMocks.create).not.toHaveBeenCalled();
  });
});
