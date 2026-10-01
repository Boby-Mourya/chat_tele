import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StarterTemplateClone } from '@/components/StarterTemplateClone';
import { starterContentApi, StarterCloneError, type PendingStarterClone, type StarterCloneResult } from '@/lib/starter-content-api';

vi.mock('@/lib/starter-content-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/starter-content-api')>();
  return { ...actual, starterContentApi: { pending: vi.fn(), prepare: vi.fn(), submit: vi.fn(), result: vi.fn(), startAnother: vi.fn() } };
});
const item = { id: 'support-template', version: 1, title: 'Support starter', kind: 'template', sample: true, content: 'Approved instructions', cloneable: true };
const saved: PendingStarterClone = { schemaVersion: 1, identity: 'context', workspaceId: 'workspace', catalogId: item.id, catalogVersion: 1, name: 'Support copy', idempotencyKey: 'request' };
const receipt: StarterCloneResult = { requestId: 'request', catalogId: item.id, catalogVersion: 1, agentId: 'agent-id', workspaceId: 'workspace', name: saved.name,
  purpose: 'support', initialStatus: 'draft', sample: true, createdAt: '2026-09-19T00:00:00Z', replayed: false };
function mount(canCreate = true, selected = item) {
  const onCreated = vi.fn();
  render(<MemoryRouter><StarterTemplateClone item={selected} canCreate={canCreate} onCreated={onCreated} /></MemoryRouter>);
  return onCreated;
}
describe('StarterTemplateClone', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(starterContentApi.pending).mockReturnValue(null); vi.mocked(starterContentApi.prepare).mockReturnValue(saved); });
  afterEach(cleanup);
  it('does not offer cloning for read-only tutorials', () => {
    mount(true, { ...item, cloneable: false }); expect(screen.queryByRole('button')).toBeNull();
  });
  it('does not offer a mutation without creation permission', () => {
    mount(false); expect(screen.queryByRole('button', { name: 'Use this template' })).toBeNull();
  });
  it('submits only after explicit confirmation and opens the existing agent editor', async () => {
    const onCreated = mount(); vi.mocked(starterContentApi.submit).mockResolvedValueOnce(receipt);
    fireEvent.click(screen.getByRole('button', { name: 'Use this template' }));
    expect(starterContentApi.submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Create draft copy' }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledOnce());
    expect(screen.getByRole('link', { name: 'Open the agent editor' }).getAttribute('href')).toBe('/agents/agent-id');
  });
  it('keeps an ambiguous request available for read-only recovery', async () => {
    mount(); vi.mocked(starterContentApi.submit).mockRejectedValueOnce(new StarterCloneError('Connection lost', 503, true));
    fireEvent.click(screen.getByRole('button', { name: 'Use this template' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create draft copy' }));
    await screen.findByRole('alert');
    expect(starterContentApi.submit).toHaveBeenCalledOnce();
    vi.mocked(starterContentApi.result).mockResolvedValueOnce({ ...receipt, replayed: true });
    fireEvent.click(screen.getByRole('button', { name: 'Check result' }));
    await screen.findByRole('link', { name: 'Open the agent editor' });
    expect(starterContentApi.result).toHaveBeenCalledOnce(); expect(starterContentApi.submit).toHaveBeenCalledOnce();
  });
  it('restores a saved request without automatically submitting it', () => {
    vi.mocked(starterContentApi.pending).mockReturnValue(saved); mount();
    fireEvent.click(screen.getByRole('button', { name: 'Use this template' }));
    expect((screen.getByRole('textbox', { name: 'Agent name' }) as HTMLInputElement).value).toBe(saved.name);
    expect(screen.getByRole('button', { name: 'Check result' })).toBeTruthy(); expect(starterContentApi.submit).not.toHaveBeenCalled();
  });
});
