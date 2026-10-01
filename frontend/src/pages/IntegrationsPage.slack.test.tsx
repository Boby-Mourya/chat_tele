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

describe('IntegrationsPage Slack setup', () => {
  beforeEach(() => {
    mocks.integrationsList.mockResolvedValue([]);
    mocks.crmProviders.mockResolvedValue([]);
    mocks.crmConnections.mockResolvedValue([]);
    mocks.channelConnections.mockResolvedValue([]);
    mocks.channelProviders.mockResolvedValue([]);
    mocks.createChannelConnection.mockResolvedValue({ id: 'channel-slack-1', name: 'Support Slack' });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('requires the Slack bot token and signing secret', async () => {
    const user = userEvent.setup();
    render(<IntegrationsPage />);

    await screen.findByText('Messaging channels');
    await user.selectOptions(screen.getByLabelText('Channel provider'), 'slack');
    await user.type(screen.getAllByPlaceholderText('Connection name')[0]!, 'Support Slack');
    await user.type(screen.getByPlaceholderText('Agent ID'), '11111111-1111-1111-1111-111111111111');
    await user.click(screen.getByRole('button', { name: 'Add channel' }));

    expect(mocks.createChannelConnection).not.toHaveBeenCalled();
    expect(mocks.pushToast).toHaveBeenCalledWith('Slack Bot token is required', 'error');

    await user.type(screen.getByPlaceholderText('Slack Bot token'), 'xoxb-test');
    await user.click(screen.getByRole('button', { name: 'Add channel' }));
    expect(mocks.createChannelConnection).not.toHaveBeenCalled();
    expect(mocks.pushToast).toHaveBeenCalledWith('Slack signing secret is required', 'error');
  });

  it('sends encrypted Slack credentials without changing generic channel settings', async () => {
    const user = userEvent.setup();
    render(<IntegrationsPage />);

    await screen.findByText('Messaging channels');
    await user.selectOptions(screen.getByLabelText('Channel provider'), 'slack');
    await user.type(screen.getAllByPlaceholderText('Connection name')[0]!, 'Support Slack');
    await user.type(screen.getByPlaceholderText('Agent ID'), '11111111-1111-1111-1111-111111111111');
    await user.type(screen.getByPlaceholderText('Slack Bot token'), 'xoxb-test');
    await user.type(screen.getByPlaceholderText('Slack signing secret'), 'slack-signing-secret');
    await user.click(screen.getByRole('button', { name: 'Add channel' }));

    await waitFor(() => expect(mocks.createChannelConnection).toHaveBeenCalledTimes(1));
    expect(mocks.createChannelConnection).toHaveBeenCalledWith({
      provider: 'slack',
      name: 'Support Slack',
      agentId: '11111111-1111-1111-1111-111111111111',
      configuration: {
        agentId: '11111111-1111-1111-1111-111111111111',
        leadCaptureDefault: { createLead: true, qualify: false, syncToCRM: false },
      },
      credentials: {
        bot_token: 'xoxb-test',
        signing_secret: 'slack-signing-secret',
      },
    });
  });

  it('shows the exact Slack Events API request path returned by the backend', async () => {
    mocks.channelConnections.mockResolvedValue([
      {
        id: 'channel-slack-1',
        public_id: 'chn_slack',
        workspace_id: '22222222-2222-2222-2222-222222222222',
        agent_id: '11111111-1111-1111-1111-111111111111',
        provider: 'slack',
        name: 'Support Slack',
        status: 'configured',
        configuration: {},
        webhook_path: '/api/v1/webhooks/channels/33333333-3333-3333-3333-333333333333/slack/chn_slack',
        created_at: '2026-09-11T00:00:00Z',
        updated_at: '2026-09-11T00:00:00Z',
      },
    ]);

    render(<IntegrationsPage />);

    const requestUrl = await screen.findByText(/Slack Events API Request URL:/);
    expect(requestUrl).toHaveTextContent(
      '/api/v1/webhooks/channels/33333333-3333-3333-3333-333333333333/slack/chn_slack',
    );
  });
});
