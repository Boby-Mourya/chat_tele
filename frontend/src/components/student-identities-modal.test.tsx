import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/providers';
import { StudentIdentitiesModal } from '@/components/student-identities-modal';
import type {
  EducationStudentIdentity,
  StudentIdentityCreateInput,
  StudentIdentityPatchInput,
} from '@/lib/education-student-identity-api';
import type { EducationStudent } from '@/lib/education-student-api';

const apiMocks = vi.hoisted(() => ({
  list: vi.fn<(studentId: string) => Promise<EducationStudentIdentity[]>>(),
  create: vi.fn<(studentId: string, input: StudentIdentityCreateInput) => Promise<EducationStudentIdentity>>(),
  update: vi.fn<(
    studentId: string,
    identityId: string,
    patch: StudentIdentityPatchInput,
  ) => Promise<EducationStudentIdentity>>(),
  revoke: vi.fn<(studentId: string, identityId: string) => Promise<void>>(),
}));

vi.mock('@/lib/education-student-identity-api', () => ({
  educationStudentIdentityApi: apiMocks,
}));

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

function identity(overrides: Partial<EducationStudentIdentity> = {}): EducationStudentIdentity {
  return {
    id: 'identity-1',
    tenantId: 'tenant-1',
    workspaceId: 'workspace-1',
    studentId: student.id,
    identityType: 'telegram',
    identifier: '123456789',
    normalizedIdentifier: '123456789',
    label: 'Telegram',
    status: 'pending',
    isPrimary: true,
    verifiedAt: null,
    createdAt: '2026-09-01T10:00:00.000Z',
    updatedAt: '2026-09-01T10:00:00.000Z',
    ...overrides,
  };
}

describe('StudentIdentitiesModal', () => {
  let identities: EducationStudentIdentity[];

  beforeEach(() => {
    identities = [identity()];
    apiMocks.list.mockImplementation(async () => structuredClone(identities));
    apiMocks.create.mockImplementation(async (studentId, input) => {
      const now = new Date().toISOString();
      const created = identity({
        id: 'identity-2',
        studentId,
        identityType: input.identityType,
        identifier: input.identifier.replace(/[\s().-]+/g, ''),
        normalizedIdentifier: input.identifier.replace(/[\s().-]+/g, ''),
        label: input.label ?? null,
        status: input.status ?? 'pending',
        isPrimary: Boolean(input.isPrimary),
        verifiedAt: input.status === 'verified' ? now : null,
        createdAt: now,
        updatedAt: now,
      });
      identities.push(created);
      return structuredClone(created);
    });
    apiMocks.update.mockImplementation(async (_studentId, identityId, patch) => {
      const index = identities.findIndex((item) => item.id === identityId);
      if (index < 0) throw new Error('Student identity not found');
      identities[index] = {
        ...identities[index]!,
        ...patch,
        verifiedAt: patch.status === 'verified'
          ? new Date().toISOString()
          : patch.status === 'pending'
            ? null
            : identities[index]!.verifiedAt,
        updatedAt: new Date().toISOString(),
      };
      return structuredClone(identities[index]!);
    });
    apiMocks.revoke.mockImplementation(async (_studentId, identityId) => {
      const index = identities.findIndex((item) => item.id === identityId);
      if (index < 0) throw new Error('Student identity not found');
      identities[index] = {
        ...identities[index]!,
        status: 'revoked',
        isPrimary: false,
        updatedAt: new Date().toISOString(),
      };
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('loads, links, verifies, revokes, and restores identities', async () => {
    const user = userEvent.setup();
    render(<ToastProvider><StudentIdentitiesModal student={student} open onClose={vi.fn()} /></ToastProvider>);

    const dialog = screen.getByRole('dialog');
    expect(await within(dialog).findByText('123456789')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Verify' }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledWith(student.id, 'identity-1', { status: 'verified' }));
    expect(await within(dialog).findByText('verified')).toBeInTheDocument();

    await user.selectOptions(within(dialog).getByLabelText('Identity type'), 'whatsapp');
    await user.type(within(dialog).getByLabelText('Identifier'), '+91 98765-43210');
    await user.type(within(dialog).getByLabelText('Label'), 'Primary WhatsApp');
    await user.click(within(dialog).getByText('Mark as verified'));
    await user.click(within(dialog).getByRole('button', { name: 'Link identity' }));

    await waitFor(() => expect(apiMocks.create).toHaveBeenCalledWith(student.id, {
      identityType: 'whatsapp',
      identifier: '+91 98765-43210',
      label: 'Primary WhatsApp',
      status: 'verified',
      isPrimary: false,
    }));
    expect(await within(dialog).findByText('+919876543210')).toBeInTheDocument();

    const revokeButtons = within(dialog).getAllByRole('button', { name: 'Revoke' });
    await user.click(revokeButtons[0]!);
    await waitFor(() => expect(apiMocks.revoke).toHaveBeenCalledWith(student.id, 'identity-1'));
    expect(await within(dialog).findByRole('button', { name: 'Restore' })).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledWith(student.id, 'identity-1', { status: 'pending' }));
  });

  it('rejects invalid Telegram usernames before calling the API', async () => {
    const user = userEvent.setup();
    render(<ToastProvider><StudentIdentitiesModal student={student} open onClose={vi.fn()} /></ToastProvider>);
    const dialog = screen.getByRole('dialog');
    await within(dialog).findByText('123456789');
    await user.selectOptions(within(dialog).getByLabelText('Identity type'), 'telegram');
    await user.type(within(dialog).getByLabelText('Identifier'), '@asha');
    await user.click(within(dialog).getByRole('button', { name: 'Link identity' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('numeric Telegram user ID');
    expect(apiMocks.create).not.toHaveBeenCalled();
  });

  it('keeps archived students read-only for new identity linking', async () => {
    const archivedStudent = { ...student, status: 'archived' as const };
    render(<ToastProvider><StudentIdentitiesModal student={archivedStudent} open onClose={vi.fn()} /></ToastProvider>);
    const dialog = screen.getByRole('dialog');
    expect(await within(dialog).findByText('Student is archived')).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Link identity' })).not.toBeInTheDocument();
  });
});
