import { afterEach, expect, it, vi } from 'vitest';
import { educationApi } from './education-api';

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

const input = { courseId: 'course-test', code: 'CA-2026-A', name: 'Test batch', startsOn: '2026-08-31', endsOn: '2026-11-30' };
const saved = { accessToken: 'expired-access', user: { id: 'test-user' } };

it('refreshes an expired login and retries batch creation with the original fields', async () => {
  localStorage.setItem('northstar.session', JSON.stringify(saved));
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: 'Invalid or expired access token' } }), { status: 401 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...saved, accessToken: 'fresh-access' }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...input, id: 'batch-test' }), { status: 201 }));
  vi.stubGlobal('fetch', fetchMock);
  await expect(educationApi.batches.create(input)).resolves.toMatchObject({ id: 'batch-test' });
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/auth/refresh', expect.objectContaining({ credentials: 'include' }));
  expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/v1/education/batches', expect.objectContaining({
    method: 'POST', body: JSON.stringify(input), headers: expect.objectContaining({ Authorization: 'Bearer fresh-access' }),
  }));
});

it('asks for sign-in when both the access token and refresh session have expired', async () => {
  localStorage.setItem('northstar.session', JSON.stringify(saved));
  const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', { status: 401 }));
  vi.stubGlobal('fetch', fetchMock);
  await expect(educationApi.batches.create(input)).rejects.toMatchObject({
    status: 401, message: 'Your session has expired. Please sign in again.',
  });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it('preserves validation errors without refreshing or retrying creation', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: 'Batch code already exists' } }), { status: 409 }));
  vi.stubGlobal('fetch', fetchMock);
  await expect(educationApi.batches.create(input)).rejects.toMatchObject({ status: 409, message: 'Batch code already exists' });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
