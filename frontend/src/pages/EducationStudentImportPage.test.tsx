import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { EducationStudentImportPage } from '@/pages/EducationStudentImportPage';

const mocks = vi.hoisted(() => ({
  preview: vi.fn(),
  commit: vi.fn(),
  parseFile: vi.fn(),
  pushToast: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/education-student-import-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/education-student-import-api')>('@/lib/education-student-import-api');
  return {
    ...actual,
    educationStudentImportApi: {
      preview: mocks.preview,
      commit: mocks.commit,
    },
  };
});

vi.mock('@/lib/education-student-import-file-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/education-student-import-file-api')>('@/lib/education-student-import-file-api');
  return { ...actual, parseStudentImportFile: mocks.parseFile };
});

const validPreview = {
  totalRows: 1,
  validRows: 1,
  invalidRows: 0,
  rows: [{
    rowNumber: 1,
    valid: true,
    errors: [],
    warnings: [],
    row: {
      studentNumber: 'STUDENT-001',
      name: 'Asha Verma',
      email: 'asha@example.com',
      identityType: null,
      identifier: null,
      identityVerified: false,
      courseCode: null,
      batchCode: null,
      agentPublicId: null,
      enrollmentStatus: 'active',
      startsOn: null,
      endsOn: null,
      customFields: {},
    },
  }],
};

function renderPage() {
  return render(<MemoryRouter><EducationStudentImportPage /></MemoryRouter>);
}

describe('EducationStudentImportPage', () => {
  beforeEach(() => {
    mocks.preview.mockResolvedValue(validPreview);
    mocks.commit.mockResolvedValue({
      committed: true,
      preview: validPreview,
      result: { createdStudents: 1, createdIdentities: 0, createdEnrollments: 0 },
    });
    mocks.parseFile.mockResolvedValue([validPreview.rows[0]!.row]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('parses pasted spreadsheet data and requests server preview', async () => {
    const user = userEvent.setup();
    renderPage();
    const textarea = screen.getByLabelText('Student import data');
    fireEvent.change(textarea, {
      target: { value: 'student_id\tname\temail\nSTUDENT-001\tAsha Verma\tasha@example.com' },
    });
    await user.click(screen.getByRole('button', { name: /preview import/i }));

    await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(1));
    expect(mocks.preview.mock.calls[0]?.[0]).toEqual([expect.objectContaining({
      studentNumber: 'STUDENT-001',
      name: 'Asha Verma',
      email: 'asha@example.com',
    })]);
    expect(await screen.findByText('Server validation preview')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /commit import/i })).toBeEnabled();
  });

  it('loads a direct XLSX upload through the server file parser', async () => {
    renderPage();
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    const workbook = new File([new Uint8Array([80, 75, 3, 4])], 'students.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    fireEvent.change(input!, { target: { files: [workbook] } });

    await waitFor(() => expect(mocks.parseFile).toHaveBeenCalledWith(workbook));
    expect(await screen.findByText('students.xlsx')).toBeInTheDocument();
    expect(screen.getByLabelText<HTMLTextAreaElement>('Student import data').value).toContain('STUDENT-001');
    expect(screen.getByLabelText<HTMLTextAreaElement>('Student import data').value).toContain('asha@example.com');
  });

  it('blocks commit when the server reports invalid rows', async () => {
    const user = userEvent.setup();
    mocks.preview.mockResolvedValue({
      ...validPreview,
      validRows: 0,
      invalidRows: 1,
      rows: [{
        ...validPreview.rows[0],
        valid: false,
        errors: ['Student ID already exists in this workspace'],
      }],
    });
    renderPage();
    await user.click(screen.getByRole('button', { name: /preview import/i }));

    expect(await screen.findByText('Student ID already exists in this workspace')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /commit import/i })).toBeDisabled();
    expect(mocks.commit).not.toHaveBeenCalled();
  });

  it('invalidates a successful preview when source data changes', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /preview import/i }));
    expect(await screen.findByText('Server validation preview')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /commit import/i })).toBeEnabled();

    fireEvent.change(screen.getByLabelText('Student import data'), {
      target: { value: `${screen.getByLabelText<HTMLTextAreaElement>('Student import data').value} ` },
    });
    expect(screen.queryByText('Server validation preview')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /commit import/i })).toBeDisabled();
  });

  it('commits exactly the rows from the latest valid preview', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /preview import/i }));
    await screen.findByText('Server validation preview');
    await user.click(screen.getByRole('button', { name: /commit import/i }));

    await waitFor(() => expect(mocks.commit).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Import completed')).toBeInTheDocument();
    expect(screen.getByText(/1 Students, 0 identities and 0 enrollments/i)).toBeInTheDocument();
  });
});
