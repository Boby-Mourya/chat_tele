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

describe('IntegrationsPage Instagram setup', () => {
  beforeEach(() => {
    mocks.integrationsList.mockResolvedValue([]);
    mocks.crmProviders.mockResolvedValue([]);
    mocks.crmConnections.mockResolvedValue([]);
    mocks.channelConnections.mockResolvedValue([]);
    mocks.channelProviders.mockResolvedValue([]);
    mocks.createChannelConnection.mockResolvedValue({ id: 'channel-ig-1', name: 'Admissions Instagram' });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('requires the complete Instagram outbound and webhook configuration', async () => {
    const user = userEvent.setup();
    render(<IntegrationsPage />);

    await screen.findByText('Messaging channels');
    await user.selectOptions(screen.getByLabelText('Channel provider'), 'instagram');
    await user.type(screen.getAllByPlaceholderText('Connection name')[0]!, 'Admissions Instagram');
    await user.type(screen.getByPlaceholderText('Agent ID'), '11111111-1111-1111-1111-111111111111');
    await user.click(screen.getByRole('button', { name: 'Add channel' }));

    expect(mocks.createChannelConnection).not.toHaveBeenCalled();
    expect(mocks.pushToast).toHaveBeenCalledWith('Instagram professional account ID is required', 'error');
  });

  it('sends encrypted Instagram credentials and account routing configuration', async () => {
    const user = userEvent.setup();
    render(<IntegrationsPage />);

    await screen.findByText('Messaging channels');
    await user.selectOptions(screen.getByLabelText('Channel provider'), 'instagram');
    await user.type(screen.getAllByPlaceholderText('Connection name')[0]!, 'Admissions Instagram');
    await user.type(screen.getByPlaceholderText('Agent ID'), '11111111-1111-1111-1111-111111111111');
    await user.type(screen.getByPlaceholderText('Instagram professional account ID'), '123456789');
    await user.type(screen.getByPlaceholderText('Instagram access token'), 'ig-access-token');
    await user.type(screen.getByPlaceholderText('Instagram app secret'), 'meta-app-secret');
    await user.type(screen.getByPlaceholderText('Instagram webhook verify token'), 'webhook-verify-token');
    await user.click(screen.getByRole('button', { name: 'Add channel' }));

    await waitFor(() => expect(mocks.createChannelConnection).toHaveBeenCalledTimes(1));
    expect(mocks.createChannelConnection).toHaveBeenCalledWith({
      provider: 'instagram',
      name: 'Admissions Instagram',
      agentId: '11111111-1111-1111-1111-111111111111',
      configuration: {
        agentId: '11111111-1111-1111-1111-111111111111',
        leadCaptureDefault: { createLead: true, qualify: false, syncToCRM: false },
        instagramAccountId: '123456789',
        apiVersion: 'v26.0',
      },
      credentials: {
        access_token: 'ig-access-token',
        app_secret: 'meta-app-secret',
        verify_token: 'webhook-verify-token',
      },
    });
  });
});
