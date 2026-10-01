import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IntegrationsPage } from '@/pages/IntegrationsPage';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  createChannelConnection: vi.fn(),
  channelConnections: vi.fn(),
  channelProviders: vi.fn(),
  crmProviders: vi.fn(),
  crmConnections: vi.fn(),
  integrationsList: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useAuth: () => ({ session: { user: { role: 'owner' } } }),
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/components/crm-management-panel', () => ({
  CRMManagementPanel: () => null,
}));

vi.mock('@/components/whatsapp-integration-modal', () => ({
  WhatsAppIntegrationModal: () => null,
}));

vi.mock('@/lib/api', () => ({
  api: {
    integrations: {
      list: mocks.integrationsList,
      setConnected: vi.fn(),
    },
  },
}));

vi.mock('@/lib/lead-crm-api', () => ({
  leadCrmApi: {
    providers: mocks.crmProviders,
    connections: mocks.crmConnections,
    channelConnections: mocks.channelConnections,
    channelProviders: mocks.channelProviders,
    createChannelConnection: mocks.createChannelConnection,
    createConnection: vi.fn(),
    testConnection: vi.fn(),
    startOAuth: vi.fn(),
    testChannelConnection: vi.fn(),
    reconnect: vi.fn(),
    refreshSchema: vi.fn(),
  },
}));

describe('IntegrationsPage Telegram setup', () => {
  beforeEach(() => {
    mocks.integrationsList.mockResolvedValue([]);
    mocks.crmProviders.mockResolvedValue([]);
    mocks.crmConnections.mockResolvedValue([]);
    mocks.channelConnections.mockResolvedValue([]);
    mocks.channelProviders.mockResolvedValue([]);
    mocks.createChannelConnection.mockResolvedValue({ id: 'channel-1', name: 'Admissions Telegram' });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('requires complete Telegram credentials before creating a connection', async () => {
    const user = userEvent.setup();
    render(<IntegrationsPage />);

    await screen.findByText('Messaging channels');
    await user.type(screen.getAllByPlaceholderText('Connection name')[0]!, 'Admissions Telegram');
    await user.type(screen.getByPlaceholderText('Agent ID'), '11111111-1111-1111-1111-111111111111');
    await user.click(screen.getByRole('button', { name: 'Add channel' }));

    expect(mocks.createChannelConnection).not.toHaveBeenCalled();
    expect(mocks.pushToast).toHaveBeenCalledWith('Telegram Bot token is required', 'error');
  });

  it('sends encrypted credential inputs and first-class agent scope', async () => {
    const user = userEvent.setup();
    render(<IntegrationsPage />);

    await screen.findByText('Messaging channels');
    await user.type(screen.getAllByPlaceholderText('Connection name')[0]!, 'Admissions Telegram');
    await user.type(screen.getByPlaceholderText('Agent ID'), '11111111-1111-1111-1111-111111111111');
    await user.type(screen.getByPlaceholderText('Telegram Bot token'), '123456:bot-secret');
    await user.type(screen.getByPlaceholderText('Telegram webhook secret token'), 'webhook-secret');
    await user.click(screen.getByRole('button', { name: 'Add channel' }));

    await waitFor(() => expect(mocks.createChannelConnection).toHaveBeenCalledTimes(1));
    expect(mocks.createChannelConnection).toHaveBeenCalledWith({
      provider: 'telegram',
      name: 'Admissions Telegram',
      agentId: '11111111-1111-1111-1111-111111111111',
      configuration: {
        agentId: '11111111-1111-1111-1111-111111111111',
        leadCaptureDefault: { createLead: true, qualify: false, syncToCRM: false },
      },
      credentials: {
        bot_token: '123456:bot-secret',
        webhook_secret: 'webhook-secret',
      },
    });
  });
});
