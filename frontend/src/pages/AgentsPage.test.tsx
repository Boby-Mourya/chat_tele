import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '@/components/providers';
import { demoAgents } from '@/lib/demo-data';
import { AgentsPage } from '@/pages/AgentsPage';
import type { Agent, AgentPatch, CreateAgentInput, DuplicateAgentInput } from '@/types';

const apiMocks = vi.hoisted(() => ({
  list: vi.fn<() => Promise<Agent[]>>(),
  create: vi.fn<(input: CreateAgentInput) => Promise<Agent>>(),
  duplicate: vi.fn<(agentId: string, input: DuplicateAgentInput) => Promise<Agent>>(),
  update: vi.fn<(agentId: string, patch: AgentPatch) => Promise<Agent>>(),
  remove: vi.fn<(agentId: string) => Promise<void>>(),
}));

vi.mock('@/lib/api', () => ({
  ApiError: class extends Error {},
  api: { agents: apiMocks, integrations: { whatsapp: { status: vi.fn().mockResolvedValue({ connections: [{ id: 'available', phoneNumberId: '123', displayPhoneNumber: '+15550100', status: 'connected', agentId: null }] }) } } },
}));

describe('AgentsPage purpose and duplicate flows', () => {
  let source: Agent;

  beforeEach(() => {
    source = structuredClone(demoAgents[0]!);
    source.purpose = 'support';
    source.appearance.deploymentChannel = 'website';
    apiMocks.list.mockResolvedValue([source]);
    apiMocks.remove.mockResolvedValue();
    apiMocks.create.mockImplementation(async (input) => ({
      ...structuredClone(source),
      id: 'agent-created',
      publicId: 'created-public',
      name: input.name,
      description: input.description,
      purpose: input.purpose ?? 'support',
      tone: input.tone ?? 'friendly',
      language: input.language ?? 'English',
      status: input.purpose === 'education' ? 'draft' : 'active',
      appearance: { ...structuredClone(source.appearance), deploymentChannel: input.deploymentChannel ?? 'website' },
    }));
    apiMocks.duplicate.mockImplementation(async (_agentId, input) => ({
      ...structuredClone(source),
      id: 'agent-duplicate',
      publicId: 'duplicate-public',
      name: input.name,
      purpose: source.purpose,
      status: 'draft',
      appearance: { ...structuredClone(source.appearance), deploymentChannel: input.deploymentChannel },
    }));
    apiMocks.update.mockImplementation(async (_agentId, patch) => ({
      ...structuredClone(source),
      ...patch,
      status: patch.purpose === 'education' ? 'draft' : (patch.status ?? source.status),
      lastUpdated: new Date().toISOString(),
    }));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows deletion errors and allows a successful retry', async () => {
    const user = userEvent.setup();
    apiMocks.remove.mockRejectedValueOnce(new Error('Deletion temporarily unavailable'));
    render(<MemoryRouter><ToastProvider><AgentsPage /></ToastProvider></MemoryRouter>);
    await user.click(await screen.findByRole('button', { name: `Actions for ${source.name}` }));
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await user.click(screen.getByRole('button', { name: 'Delete agent' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Deletion temporarily unavailable');
    apiMocks.list.mockResolvedValue([]);
    await user.click(screen.getByRole('button', { name: 'Delete agent' }));
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Delete this agent?' })).not.toBeInTheDocument());
    expect(apiMocks.remove).toHaveBeenLastCalledWith(source.id);
    expect(await screen.findByText('Create your first agent')).toBeInTheDocument();
  });

  it('asks for a deployment channel and duplicates the complete bot purpose and template', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ToastProvider><AgentsPage /></ToastProvider></MemoryRouter>);

    await user.click(await screen.findByRole('button', { name: `Actions for ${source.name}` }));
    await user.click(screen.getByRole('button', { name: 'Duplicate' }));

    expect(screen.getByRole('heading', { name: 'Duplicate AI agent' })).toBeInTheDocument();
    expect(screen.getByText(/Purpose:/)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Website/ })).toBeChecked();
    await user.click(screen.getByRole('radio', { name: /WhatsApp/ }));
    await user.click(screen.getByRole('button', { name: 'Duplicate agent' }));

    await waitFor(() => expect(apiMocks.duplicate).toHaveBeenCalledWith(source.id, {
      name: `${source.name} copy`,
      deploymentChannel: 'whatsapp',
    }));
  });

  it('creates an agent with an explicit first-class purpose', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ToastProvider><AgentsPage /></ToastProvider></MemoryRouter>);

    await user.click(await screen.findByRole('button', { name: 'Create agent' }));
    await user.type(screen.getByLabelText('Agent name'), 'Hindi Lead Agent');
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await user.click(screen.getByRole('radio', { name: /Lead generation/ }));
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await user.selectOptions(screen.getByLabelText('Primary language'), 'Hindi');
    expect(screen.getByText('मैं आपकी कैसे मदद कर सकता हूँ?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await user.click(screen.getByRole('radio', { name: /WhatsApp/ }));
    await waitFor(() => expect(screen.getByLabelText('WhatsApp number for this bot')).toBeEnabled());
    await user.selectOptions(screen.getByLabelText('WhatsApp number for this bot'), 'available');
    await user.click(screen.getAllByRole('button', { name: 'Create agent' }).at(-1)!);

    await waitFor(() => expect(apiMocks.create).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Hindi Lead Agent',
      purpose: 'lead_generation',
      template: 'lead',
      language: 'Hindi',
      deploymentChannel: 'whatsapp',
    })));
  });

  it('creates a Telegram agent with the selected deployment channel', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ToastProvider><AgentsPage /></ToastProvider></MemoryRouter>);
    await user.click(await screen.findByRole('button', { name: 'Create agent' }));
    await user.type(screen.getByLabelText('Agent name'), 'Telegram Assistant');
    for (let step = 0; step < 3; step++) await user.click(screen.getByRole('button', { name: 'Continue' }));
    await user.click(screen.getByRole('radio', { name: /Telegram/ }));
    await user.click(screen.getAllByRole('button', { name: 'Create agent' }).at(-1)!);
    await waitFor(() => expect(apiMocks.create).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Telegram Assistant', deploymentChannel: 'telegram',
    })));
  });

  it('lets an existing agent change purpose and exposes the Education safety state', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ToastProvider><AgentsPage /></ToastProvider></MemoryRouter>);

    await user.click(await screen.findByRole('button', { name: `Actions for ${source.name}` }));
    await user.click(screen.getByRole('button', { name: 'Change purpose' }));

    expect(screen.getByRole('heading', { name: 'Change agent purpose' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /General \/ Support/ })).toBeChecked();
    await user.click(screen.getByRole('radio', { name: /Education/ }));
    expect(screen.getByText('Education agents stay in draft during provisioning')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save purpose' }));

    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledWith(source.id, {
      purpose: 'education',
    }));
  });
});
