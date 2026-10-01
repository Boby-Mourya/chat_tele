import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EducationAccessRequestsPage } from '@/pages/EducationAccessRequestsPage';

const mocks = vi.hoisted(() => ({
  listRequests: vi.fn(),
  review: vi.fn(),
  listStudents: vi.fn(),
  listEnrollments: vi.fn(),
  pushToast: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/education-access-request-api', () => ({
  educationAccessRequestApi: {
    list: mocks.listRequests,
    review: mocks.review,
  },
}));

vi.mock('@/lib/education-student-api', () => ({
  educationStudentApi: { list: mocks.listStudents },
}));

vi.mock('@/lib/education-enrollment-api', () => ({
  educationEnrollmentApi: { list: mocks.listEnrollments },
}));

const pendingRequest = {
  id: 'request-1',
  tenantId: 'tenant-1',
  workspaceId: 'workspace-1',
  agentId: 'agent-1',
  studentId: null,
  enrollmentId: null,
  studentNumber: 'STUDENT-101',
  email: 'student101@example.com',
  identityType: 'whatsapp',
  normalizedIdentifier: '+919811112222',
  message: 'Please restore my course access.',
  status: 'pending',
  reviewedByUserId: null,
  reviewedAt: null,
  resolutionNote: null,
  createdAt: '2026-09-11T12:00:00Z',
  updatedAt: '2026-09-11T12:00:00Z',
};

const student = {
  id: 'student-1',
  tenantId: 'tenant-1',
  workspaceId: 'workspace-1',
  studentNumber: 'STUDENT-101',
  name: 'Asha Student',
  email: 'student101@example.com',
  customFields: {},
  status: 'active',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-09-01T00:00:00Z',
};

const enrollment = {
  id: 'enrollment-1',
  tenantId: 'tenant-1',
  workspaceId: 'workspace-1',
  studentId: 'student-1',
  courseId: 'course-1',
  batchId: 'batch-1',
  agentId: 'agent-1',
  startsOn: '2026-01-01',
  endsOn: '2027-12-31',
  status: 'active',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-09-01T00:00:00Z',
};

describe('EducationAccessRequestsPage', () => {
  beforeEach(() => {
    mocks.listRequests.mockResolvedValue([pendingRequest]);
    mocks.listStudents.mockResolvedValue([student]);
    mocks.listEnrollments.mockResolvedValue([enrollment]);
    mocks.review.mockImplementation(async (_id: string, input: { action: string; note?: string | null }) => ({
      ...pendingRequest,
      studentId: 'student-1',
      enrollmentId: 'enrollment-1',
      status: input.action === 'approve' ? 'approved' : 'denied',
      reviewedAt: '2026-09-11T13:00:00Z',
      resolutionNote: input.note ?? null,
    }));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('requires an active Student and Enrollment for the same Education Agent before approval', async () => {
    const user = userEvent.setup();
    render(<EducationAccessRequestsPage />);

    expect(await screen.findByText('STUDENT-101')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Student'), 'student-1');
    await user.selectOptions(screen.getByLabelText('Active enrollment'), 'enrollment-1');
    await user.type(screen.getByLabelText('Review note'), 'Matched against academy records.');
    await user.click(screen.getByRole('button', { name: /approve & verify identity/i }));

    await waitFor(() => expect(mocks.review).toHaveBeenCalledWith('request-1', {
      action: 'approve',
      studentId: 'student-1',
      enrollmentId: 'enrollment-1',
      note: 'Matched against academy records.',
    }));
    expect(await screen.findByText('Identity verified by reviewer')).toBeInTheDocument();
  });

  it('denies a request without linking Student or Enrollment in the review payload', async () => {
    const user = userEvent.setup();
    render(<EducationAccessRequestsPage />);

    await screen.findByText('STUDENT-101');
    await user.type(screen.getByLabelText('Review note'), 'Unable to verify enrollment.');
    await user.click(screen.getByRole('button', { name: /deny request/i }));

    await waitFor(() => expect(mocks.review).toHaveBeenCalledWith('request-1', {
      action: 'deny',
      studentId: undefined,
      enrollmentId: undefined,
      note: 'Unable to verify enrollment.',
    }));
    expect(await screen.findByText('Request denied')).toBeInTheDocument();
  });
});
