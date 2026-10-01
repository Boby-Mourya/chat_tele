import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ToastProvider } from '@/components/providers';
import { demoAgents } from '@/lib/demo-data';
import { AgentBuilderPage } from '@/pages/AgentBuilderPage';
import type { Agent, AgentPatch } from '@/types';

const apiMocks = vi.hoisted(() => ({
  list: vi.fn<() => Promise<Agent[]>>(),
  update: vi.fn<(agentId: string, patch: AgentPatch) => Promise<Agent>>(),
  remove: vi.fn<(agentId: string) => Promise<void>>(),
}));

vi.mock('@/lib/api', () => ({
  api: {
    agents: apiMocks,
    knowledge: {
      list: vi.fn(async () => []),
      add: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

vi.mock('@/pages/DeployPage', () => ({
  AgentDeploymentPreview: ({ agent }: { agent: Agent }) => <div data-testid="agent-preview">{agent.name}</div>,
}));

describe('AgentBuilderPage first-class purpose', () => {
  let source: Agent;

  beforeEach(() => {
    source = structuredClone(demoAgents[0]!);
    source.purpose = 'support';
    source.status = 'active';
    apiMocks.list.mockResolvedValue([source]);
    apiMocks.update.mockImplementation(async (_agentId, patch) => ({
      ...structuredClone(source),
      ...patch,
      lastUpdated: new Date().toISOString(),
    }));
    apiMocks.remove.mockResolvedValue();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows purpose in the builder and safely saves Education as draft', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={[`/agents/${source.id}/settings`]}>
        <ToastProvider>
          <Routes>
            <Route path="/agents/:agentId/:tab" element={<AgentBuilderPage />} />
          </Routes>
        </ToastProvider>
      </MemoryRouter>,
    );

    const purposeSelect = await screen.findByLabelText('Agent purpose');
    expect(purposeSelect).toHaveValue('support');
    expect(screen.getAllByText('General / Support').length).toBeGreaterThan(0);

    await user.selectOptions(purposeSelect, 'education');
    expect(screen.getByText('Education safety mode')).toBeInTheDocument();
    expect(screen.getByText(/stays in draft until Course, Batch, Student, and Enrollment authorization/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledWith(
      source.id,
      expect.objectContaining({ purpose: 'education', status: 'draft' }),
    ));
  });
});
