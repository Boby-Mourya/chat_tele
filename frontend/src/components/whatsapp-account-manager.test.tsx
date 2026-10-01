import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { WhatsAppAccountManager } from './whatsapp-account-manager';
import { WhatsAppNumberDeployment } from './whatsapp-number-deployment';

const mocks = vi.hoisted(() => ({ accounts: vi.fn(), status: vi.fn(), addAccount: vi.fn(), accountNumbers: vi.fn(), addNumber: vi.fn(), assignNumber: vi.fn(), agents: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { integrations: { whatsapp: mocks }, agents: { list: mocks.agents } } }));
vi.mock('@/components/providers', () => ({ useWorkspace: () => ({ activeWorkspace: { id: 'workspace' } }) }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it('lets users type account credentials and save without platform Facebook configuration', async () => {
  mocks.accounts.mockResolvedValue([]); mocks.status.mockResolvedValue({ connections: [] }); mocks.agents.mockResolvedValue([]);
  mocks.accountNumbers.mockResolvedValue([]);
  mocks.addAccount.mockResolvedValue({ id: 'account', name: 'Sales account', wabaId: '555', appId: '123', status: 'needs_webhook', webhookUrl: 'http://localhost:3100/api/v1/webhooks/whatsapp/accounts/account' });
  const user = userEvent.setup();
  render(<WhatsAppAccountManager open onClose={vi.fn()} onConnectionChanged={vi.fn()} onEmbedded={vi.fn()} />);
  await user.type(await screen.findByLabelText('Account name'), 'Sales account');
  await user.type(screen.getByLabelText('Meta App ID'), '123');
  await user.type(screen.getByLabelText('Meta App secret'), 'secret123');
  await user.type(screen.getByLabelText('WhatsApp Business Account ID'), '555');
  await user.type(screen.getByLabelText('System-user access token'), 'token123');
  await user.type(screen.getByLabelText('Webhook verification token'), 'a'.repeat(32));
  expect(screen.getByLabelText('Meta App secret')).toHaveAttribute('type', 'password');
  await user.click(screen.getByRole('button', { name: 'Verify and save account' }));
  await waitFor(() => expect(mocks.addAccount).toHaveBeenCalledWith({ name: 'Sales account', appId: '123', appSecret: 'secret123', accessToken: 'token123', wabaId: '555', verifyToken: 'a'.repeat(32) }));
});

it('deploys a chosen number rather than toggling WhatsApp for the whole workspace', async () => {
  const numbers = [{ id: 'first', agentId: 'bot', status: 'connected', displayPhoneNumber: '+15550001', verifiedName: 'Sales' }, { id: 'second', agentId: null, status: 'connected', displayPhoneNumber: '+15550002', verifiedName: 'Support' }];
  mocks.status.mockResolvedValue({ connections: numbers });
  mocks.assignNumber.mockResolvedValue({ ...numbers[1], agentId: 'bot' });
  const user = userEvent.setup();
  render(<WhatsAppNumberDeployment agentId="bot" />);
  await screen.findByRole('option', { name: /15550002/ });
  await user.selectOptions(screen.getByLabelText('Connected WhatsApp number'), 'second');
  await user.click(screen.getByRole('button', { name: 'Apply number assignment' }));
  await waitFor(() => expect(mocks.assignNumber).toHaveBeenCalledWith('second', 'bot'));
});
