import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { EducationStudentDetailPage } from '@/pages/EducationStudentDetailPage';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock('@/lib/education-student-detail-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/education-student-detail-api')>('@/lib/education-student-detail-api');
  return {
    ...actual,
    educationStudentDetailApi: { get: mocks.get },
  };
});

const detail = {
  student: {
    id: 'student-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentNumber: 'NS-1001',
    name: 'Asha Student', email: 'asha@example.com', customFields: { language: 'English' }, status: 'active',
    createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-09-11T10:00:00Z',
  },
  identities: [{
    id: 'identity-1', identityType: 'website_login', identifier: 'asha@example.com', label: 'Portal',
    status: 'verified', isPrimary: true, verifiedAt: '2026-09-01T00:00:00Z', createdAt: '2026-08-01T00:00:00Z',
  }],
  enrollments: [{
    id: 'enrollment-1', courseId: 'course-1', courseCode: 'CPA', courseName: 'CPA Program',
    batchId: 'batch-1', batchCode: 'CPA-2026', batchName: 'CPA 2026', agentId: 'agent-1',
    agentPublicId: 'agt_cpa', agentName: 'CPA Mentor', startsOn: '2026-01-01', endsOn: '2027-01-01',
    status: 'active', accessState: 'active', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-09-01T00:00:00Z',
  }],
  conversations: [{
    id: 'conversation-1', publicId: 'cnv_123', enrollmentId: 'enrollment-1', courseId: 'course-1',
    batchId: 'batch-1', agentId: 'agent-1', agentName: 'CPA Mentor', channel: 'widget', state: 'resolved',
    resolution: 'answered', startedAt: '2026-09-10T10:00:00Z', endedAt: '2026-09-10T10:15:00Z', updatedAt: '2026-09-10T10:15:00Z',
  }],
  activity: [{
    id: 'activity-1', eventType: 'education.conversation.resolved.v1', conversationId: 'conversation-1',
    conversationPublicId: 'cnv_123', enrollmentId: 'enrollment-1', courseId: 'course-1', courseName: 'CPA Program',
    batchId: 'batch-1', batchName: 'CPA 2026', agentId: 'agent-1', agentName: 'CPA Mentor', resolution: 'answered',
    resolvedAt: '2026-09-10T10:15:00Z', actorUserId: null, details: { topics: ['exam registration'], messageCount: 4 },
    createdAt: '2026-09-10T10:15:00Z',
  }],
  summary: {
    verifiedIdentityCount: 1, activeAccessCount: 1, conversationCount: 1, activityCount: 1,
    lastActiveAt: '2026-09-10T10:15:00Z',
  },
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/education/students/student-1']}>
      <Routes><Route path="/education/students/:studentId" element={<EducationStudentDetailPage />} /></Routes>
    </MemoryRouter>,
  );
}

describe('EducationStudentDetailPage', () => {
  beforeEach(() => {
    mocks.get.mockResolvedValue(detail);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders profile, identities, enrollment access, conversations and activity history together', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Asha Student' })).toBeInTheDocument();
    expect(screen.getAllByText('NS-1001').length).toBeGreaterThan(0);
    expect(screen.getAllByText('CPA Program').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/CPA 2026/).length).toBeGreaterThan(0);
    expect(screen.getAllByText('CPA Mentor').length).toBeGreaterThan(0);
    expect(screen.getAllByText('cnv_123').length).toBeGreaterThan(0);
    expect(screen.getByText('Education conversation resolved')).toBeInTheDocument();
    expect(screen.getByText(/exam registration/)).toBeInTheDocument();
    expect(screen.getByText('website login')).toBeInTheDocument();
    expect(screen.getAllByText('verified').length).toBeGreaterThan(0);
    expect(screen.getByText('Authorization remains unchanged')).toBeInTheDocument();
  });

  it('shows empty sections without removing the Student profile', async () => {
    mocks.get.mockResolvedValue({
      ...detail,
      identities: [], enrollments: [], conversations: [], activity: [],
      summary: { verifiedIdentityCount: 0, activeAccessCount: 0, conversationCount: 0, activityCount: 0, lastActiveAt: null },
    });
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Asha Student' })).toBeInTheDocument();
    expect(screen.getByText('No enrollments')).toBeInTheDocument();
    expect(screen.getByText('No Education conversations')).toBeInTheDocument();
    expect(screen.getByText('No activity history')).toBeInTheDocument();
    expect(screen.getByText('No identities')).toBeInTheDocument();
  });
});
