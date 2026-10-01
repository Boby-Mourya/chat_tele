import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/storage', () => ({
  readStorage: vi.fn(() => ({ accessToken: 'token-123' })),
}));

vi.mock('@/lib/workspace-api', () => ({
  activeWorkspaceId: vi.fn(() => 'workspace-1'),
}));

import { educationActivityApi } from '@/lib/education-activity-api';

const emptyPage = { items: [], total: 0, page: 1, pageSize: 50 };

describe('educationActivityApi', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('serializes workspace Education activity filters and authorization headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => emptyPage,
    });
    vi.stubGlobal('fetch', fetchMock);

    await educationActivityApi.list({
      agentId: 'agent-1',
      courseId: 'course-1',
      batchId: 'batch-1',
      studentId: 'student-1',
      eventType: 'conversation.resolved',
      search: 'CPA 1001',
      page: 2,
      pageSize: 25,
    });

    const [url, options] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain('/education/activity?');
    expect(String(url)).toContain('agent_id=agent-1');
    expect(String(url)).toContain('course_id=course-1');
    expect(String(url)).toContain('batch_id=batch-1');
    expect(String(url)).toContain('student_id=student-1');
    expect(String(url)).toContain('event_type=conversation.resolved');
    expect(String(url)).toContain('search=CPA+1001');
    expect(String(url)).toContain('page=2');
    expect(String(url)).toContain('page_size=25');
    expect(options.headers).toMatchObject({
      Authorization: 'Bearer token-123',
      'X-Workspace-ID': 'workspace-1',
    });
  });

  it('propagates authorization failures instead of hiding them with demo fallback', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: 'Forbidden' }),
    }));

    await expect(educationActivityApi.list()).rejects.toMatchObject({ status: 403 });
  });

  it('returns empty history on a demo network failure instead of fabricating activity', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network unavailable')));

    const result = await educationActivityApi.list({ page: 3, pageSize: 10 });

    expect(result).toEqual({ items: [], total: 0, page: 3, pageSize: 10 });
  });
});
