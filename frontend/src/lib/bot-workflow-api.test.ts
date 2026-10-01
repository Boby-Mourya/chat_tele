import { beforeEach, describe, expect, it, vi } from 'vitest';
import { botWorkflowApi } from '@/lib/bot-workflow-api';
import { persistActiveWorkspace } from '@/lib/workspace-api';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
beforeEach(() => { fetchMock.mockReset(); localStorage.clear(); sessionStorage.clear(); localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'token' })); persistActiveWorkspace('workspace-1'); });

describe('bot workflow API', () => {
  it('saves the selected bot workflow with workspace scope', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: 'wf-1' }) });
    await botWorkflowApi.save('agent-1', { name: 'Support flow', purpose: 'support', status: 'active', steps: [] });
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/bot-workflows/agent-1', expect.objectContaining({ method: 'PUT', credentials: 'include' }));
    const request = fetchMock.mock.calls[0]![1]!;
    expect(request.headers['X-Workspace-ID']).toBe('workspace-1');
    expect(JSON.parse(request.body)).toMatchObject({ purpose: 'support', status: 'active' });
  });

  it('applies and persists a backend-owned workflow template', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: 'wf-education' }) });
    await botWorkflowApi.applyTemplate('agent-education', 'enrolled_student_tutor');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/bot-workflows/agent-education/templates/enrolled_student_tutor',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    );
  });
});
