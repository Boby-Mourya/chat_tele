import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CreateAgentModal } from './AgentsPage';
const mocks = vi.hoisted(() => ({ status: vi.fn(), list: vi.fn(), create: vi.fn() }));
vi.mock('@/lib/api', () => ({ ApiError: class extends Error {}, api: { integrations: { whatsapp: { status: mocks.status } }, agents: { list: mocks.list, create: mocks.create } } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
async function openWhatsApp() {
  render(<CreateAgentModal onClose={vi.fn()} onCreated={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('Agent name'), { target: { value: 'Support bot' } });
  for (let i = 0; i < 3; i++) fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  fireEvent.click(screen.getByRole('radio', { name: /WhatsApp/ }));
  await waitFor(() => expect(screen.getByLabelText('WhatsApp number for this bot')).toBeEnabled());
}
it('requires an available number and sends it with agent creation', async () => {
  mocks.status.mockResolvedValue({ connections: [
    { id: 'free', displayPhoneNumber: '+15550100', status: 'connected', agentId: null },
    { id: 'used', displayPhoneNumber: '+15550101', status: 'connected', agentId: 'sales' },
  ] });
  mocks.list.mockResolvedValue([{ id: 'sales', name: 'Sales bot' }]);
  mocks.create.mockResolvedValue({ id: 'new', purpose: 'support' });
  await openWhatsApp();
  expect(screen.getByRole('button', { name: 'Create agent' })).toBeDisabled();
  expect(screen.getByRole('option', { name: /Assigned to Sales bot/ })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('WhatsApp number for this bot'), { target: { value: 'free' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));
  await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ whatsappConnectionId: 'free', deploymentChannel: 'whatsapp' })));
});
it('blocks WhatsApp creation when inventory fails to load', async () => {
  mocks.status.mockRejectedValue(new Error('offline')); mocks.list.mockResolvedValue([]);
  await openWhatsApp();
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load connected numbers');
  expect(screen.getByRole('button', { name: 'Create agent' })).toBeDisabled();
});
