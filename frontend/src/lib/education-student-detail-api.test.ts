import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/storage', () => ({
  readStorage: vi.fn(() => ({ accessToken: 'token-123' })),
}));

vi.mock('@/lib/workspace-api', () => ({
  activeWorkspaceId: vi.fn(() => 'workspace-1'),
}));

vi.mock('@/lib/education-student-api', () => ({
  educationStudentApi: { get: vi.fn() },
}));

import { educationStudentDetailApi } from '@/lib/education-student-detail-api';

const detailPayload = {
  student: {
    id: 'student-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentNumber: 'NS-1001',
    name: 'Asha Student', email: 'asha@example.com', customFields: {}, status: 'active',
    createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-09-11T00:00:00Z',
  },
  identities: [], enrollments: [], conversations: [], activity: [],
  summary: { verifiedIdentityCount: 0, activeAccessCount: 0, conversationCount: 0, activityCount: 0, lastActiveAt: null },
};

describe('educationStudentDetailApi', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('loads the workspace-scoped Student detail with a bounded activity limit', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => detailPayload,
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await educationStudentDetailApi.get('student-1', 9999);

    expect(result.student.studentNumber).toBe('NS-1001');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain('/education/students/student-1/detail?activity_limit=500');
    expect(options.headers).toMatchObject({
      Authorization: 'Bearer token-123',
      'X-Workspace-ID': 'workspace-1',
    });
  });

  it('does not hide a real not-found response behind demo fallback', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Student not found' }),
    }));

    await expect(educationStudentDetailApi.get('missing-student')).rejects.toMatchObject({
      message: 'Student not found',
      status: 404,
    });
  });
});
