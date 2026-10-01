import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/providers';
import { AgentStatusControl } from './agent-status-control';
import { demoAgents } from '@/lib/demo-data';

const update = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ api: { agents: { update } } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('bot activation control', () => {
  it('activates the selected bot and links to its enrollments', async () => {
    const agent = { ...demoAgents[0]!, purpose: 'education' as const, status: 'draft' as const };
    const onSaved = vi.fn(); update.mockResolvedValue({ ...agent, status: 'active' });
    render(<MemoryRouter><ToastProvider><AgentStatusControl agent={agent} onSaved={onSaved} /></ToastProvider></MemoryRouter>);
    await userEvent.click(screen.getByRole('switch'));
    await waitFor(() => expect(update).toHaveBeenCalledWith(agent.id, { status: 'active' }));
    expect(onSaved).toHaveBeenCalledOnce();
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('link', { name: 'Manage enrollments' })).toHaveAttribute('href', `/education/enrollments?agentId=${agent.id}`);
  });
  it('keeps the draft state and explains activation failures', async () => {
    const agent = { ...demoAgents[0]!, status: 'draft' as const };
    const onSaved = vi.fn(); update.mockRejectedValue(new Error('Create an active enrollment first'));
    render(<MemoryRouter><ToastProvider><AgentStatusControl agent={agent} onSaved={onSaved} /></ToastProvider></MemoryRouter>);
    await userEvent.click(screen.getByRole('switch'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Create an active enrollment first');
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false'); expect(onSaved).not.toHaveBeenCalled();
  });
  it('sets an active bot to draft', async () => {
    const agent = { ...demoAgents[0]!, status: 'active' as const };
    update.mockResolvedValue({ ...agent, status: 'draft' });
    render(<MemoryRouter><ToastProvider><AgentStatusControl agent={agent} onSaved={() => {}} /></ToastProvider></MemoryRouter>);
    await userEvent.click(screen.getByRole('switch'));
    await waitFor(() => expect(update).toHaveBeenCalledWith(agent.id, { status: 'draft' }));
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  });
});
