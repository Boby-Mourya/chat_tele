import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IntegrationsHubPage } from '@/pages/IntegrationsHubPage';

const mocks = vi.hoisted(() => ({
  resume: vi.fn(), role: 'owner', crm: vi.fn(), channels: vi.fn(), providers: vi.fn(), agents: vi.fn(),
  create: vi.fn(), update: vi.fn(), test: vi.fn(), start: vi.fn(), activate: vi.fn(), entitlements: vi.fn(),
}));
vi.mock('@/components/providers', () => ({ useAuth: () => ({ session: { user: { role: mocks.role } } }), useWorkspace: () => ({ activeWorkspace: { id: 'workspace-1' } }) }));
vi.mock('@/components/whatsapp-integration-modal', () => ({ WhatsAppIntegrationModal: () => null }));
vi.mock('@/lib/api', () => ({ api: { integrations: { list: async () => [] }, agents: { list: mocks.agents } } }));
vi.mock('@/lib/crm-one-click-api', () => ({ crmOneClickApi: { providers: mocks.providers, startOAuth: mocks.start, activateDirect: mocks.activate } }));
vi.mock('@/lib/lead-crm-api', () => ({ leadCrmApi: { startOAuth: mocks.resume, connections: mocks.crm, channelConnections: mocks.channels, createChannelConnection: mocks.create, updateChannelConnection: mocks.update, testChannelConnection: mocks.test, connectionEntitlements: mocks.entitlements } }));

const saved = { id: 'slack-1', public_id: 'channel-1', provider: 'slack', name: 'Slack', agent_id: 'agent-1', status: 'configured', configuration: {}, webhook_path: '/api/v1/webhooks/channels/tenant/slack/channel-1' };
async function open(name: string) {
  render(<MemoryRouter><IntegrationsHubPage /></MemoryRouter>);
  const button = await screen.findByRole('button', { name: `Connect ${name}` });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  return screen.getByRole('dialog');
}
beforeEach(() => {
  mocks.role = 'owner'; mocks.crm.mockResolvedValue([]); mocks.channels.mockResolvedValue([]);
  mocks.entitlements.mockResolvedValue({ plan: 'business', features: { crm: true, allowedChannels: ['slack', 'telegram', 'instagram', 'facebook'] } });
  mocks.providers.mockResolvedValue([{ id: 'zoho', mode: 'oauth', configured: false, supportsSandbox: true, oauthRedirectUri: 'http://localhost:8100/api/v1/crm/oauth/zoho/callback' }]);
  mocks.agents.mockResolvedValue([{ id: 'agent-1', name: 'Slack support', appearance: { deploymentChannel: 'slack' } }, { id: 'wrong-agent', name: 'Website support', appearance: { deploymentChannel: 'website' } }]);
  mocks.create.mockResolvedValue(saved); mocks.update.mockResolvedValue(saved); mocks.test.mockResolvedValue({ status: 'healthy' });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });

describe('integration catalogue and real setup', () => {
  it('puts CRM first and filters by category and search', async () => {
    render(<MemoryRouter><IntegrationsHubPage /></MemoryRouter>);
    expect(screen.getAllByRole('region')[0]).toHaveAccessibleName('CRM integrations');
    await userEvent.click(screen.getByRole('button', { name: 'Channels' }));
    expect(screen.queryByRole('heading', { name: 'Zoho CRM' })).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: 'Search integrations' }), 'slack');
    expect(screen.getByRole('heading', { name: 'Slack' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Telegram' })).not.toBeInTheDocument();
    await userEvent.clear(screen.getByRole('textbox', { name: 'Search integrations' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Search integrations' }), 'unavailable-platform');
    expect(screen.getByText('No integrations found')).toBeInTheDocument();
  });

  it('collects Slack details, validates them and shows remaining webhook setup', async () => {
    const dialog = await open('Slack');
    expect(within(dialog).queryByRole('option', { name: 'Website support' })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save and verify' }));
    expect(mocks.create).not.toHaveBeenCalled();
    await userEvent.selectOptions(within(dialog).getByLabelText('Agent'), 'agent-1');
    await userEvent.type(within(dialog).getByLabelText('Bot user OAuth token'), 'xoxb-private');
    await userEvent.type(within(dialog).getByLabelText('Signing secret'), 'private-signing');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save and verify' }));
    await screen.findByText('Finish message setup');
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ provider: 'slack', agentId: 'agent-1', credentials: { bot_token: 'xoxb-private', signing_secret: 'private-signing' } }));
    expect(mocks.test).toHaveBeenCalledWith('slack-1');
    expect(screen.queryByDisplayValue('xoxb-private')).not.toBeInTheDocument();
    expect((screen.getByLabelText('Webhook URL') as HTMLInputElement).value).toContain('/webhooks/channels/tenant/slack/channel-1');
    expect(screen.queryByText('Connected', { exact: true })).not.toBeInTheDocument();
  });

  it('does not show success for rejected credentials and retries the same connection', async () => {
    mocks.test.mockResolvedValueOnce({ status: 'auth_required' });
    const dialog = await open('Slack');
    await userEvent.selectOptions(within(dialog).getByLabelText('Agent'), 'agent-1');
    await userEvent.type(within(dialog).getByLabelText('Bot user OAuth token'), 'bad-token');
    await userEvent.type(within(dialog).getByLabelText('Signing secret'), 'bad-secret');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save and verify' }));
    await screen.findByText(/Credentials could not be verified/);
    expect(screen.queryByText('Finish message setup')).not.toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText('Bot user OAuth token'), 'correct-token');
    await userEvent.type(within(dialog).getByLabelText('Signing secret'), 'correct-secret');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save and verify' }));
    await screen.findByText('Finish message setup');
    expect(mocks.create).toHaveBeenCalledTimes(1);
    expect(mocks.update).toHaveBeenCalledWith('slack-1', expect.objectContaining({ credentials: { bot_token: 'correct-token', signing_secret: 'correct-secret' } }));
  });

  it('asks for a customer OAuth app and accepts only the expected popup callback', async () => {
    const popup = { closed: false, close: vi.fn(), location: { replace: vi.fn() } };
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
    mocks.start.mockResolvedValue({ connectionId: 'zoho-1', authorizationUrl: 'https://accounts.zoho.com/oauth/v2/auth' });
    const dialog = await open('Zoho CRM');
    expect(within(dialog).getByLabelText('Authorized redirect URL')).toHaveValue('http://localhost:8100/api/v1/crm/oauth/zoho/callback');
    await userEvent.type(within(dialog).getByLabelText('Client ID'), 'customer-app');
    await userEvent.type(within(dialog).getByLabelText('Client secret'), 'private-secret');
    await userEvent.selectOptions(within(dialog).getByLabelText('Zoho data center'), 'in');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Authorize account' }));
    await waitFor(() => expect(popup.location.replace).toHaveBeenCalled());
    expect(mocks.start).toHaveBeenCalledWith('zoho', expect.objectContaining({ client_id: 'customer-app', client_secret: 'private-secret', region: 'in' }));
    expect(screen.queryByDisplayValue('private-secret')).not.toBeInTheDocument();
    const data = { type: 'northstar:crm-oauth', success: true, connectionId: 'zoho-1', readiness: { ready: true } };
    act(() => { fireEvent(window, new MessageEvent('message', { origin: 'https://untrusted.example', source: popup as unknown as Window, data })); });
    expect(screen.queryByText(/Account connected. Lead sync/)).not.toBeInTheDocument();
    act(() => { fireEvent(window, new MessageEvent('message', { origin: 'http://localhost:8100', source: popup as unknown as Window, data })); });
    expect(await screen.findByText(/Account connected. Lead sync/)).toBeInTheDocument();
    expect(popup.close).toHaveBeenCalled();
  });

  it('prevents a viewer from connecting platforms', async () => {
    mocks.role = 'viewer';
    render(<MemoryRouter><IntegrationsHubPage /></MemoryRouter>);
    await waitFor(() => expect(screen.queryByText('Refreshing connection status…')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Connect Zoho CRM' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Connect Slack' })).toBeDisabled();
  });

  it('keeps credentials editable and reports backend plan restrictions on submission', async () => {
    mocks.entitlements.mockResolvedValue({ plan: 'starter', features: { crm: false, allowedChannels: ['website'] } });
    const popup = { closed: false, close: vi.fn(), location: { replace: vi.fn() } };
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
    mocks.start.mockRejectedValueOnce(new Error('CRM is not available on the starter plan'));
    const dialog = await open('Zoho CRM');
    expect(await within(dialog).findByText(/Your starter plan does not include/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Client ID')).toBeEnabled();
    expect(within(dialog).getByRole('link', { name: 'Review plans' })).toHaveAttribute('href', '/workspace?section=billing');
    await userEvent.type(within(dialog).getByLabelText('Client ID'), 'customer-app');
    await userEvent.type(within(dialog).getByLabelText('Client secret'), 'customer-secret');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Authorize account' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('CRM is not available on the starter plan');
    expect(mocks.start).toHaveBeenCalled();
    expect(popup.close).toHaveBeenCalled();
    expect(within(dialog).getByLabelText('Client ID')).toHaveValue('customer-app');
  });
});


it('resumes authorization on the existing saved CRM connection', async () => {
  mocks.crm.mockResolvedValue([{ id: 'zoho-existing', provider: 'zoho', name: 'Zoho CRM', status: 'auth_required', environment: 'production' }]);
  mocks.resume.mockResolvedValue({ authorizationUrl: 'https://accounts.zoho.com/oauth/v2/auth' });
  const popup = { closed: false, close: vi.fn(), location: { replace: vi.fn() } };
  vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
  render(<MemoryRouter><IntegrationsHubPage /></MemoryRouter>);
  const manage = await screen.findByRole('button', { name: 'Manage Zoho CRM' });
  await waitFor(() => expect(manage).toBeEnabled());
  await userEvent.click(manage);
  await userEvent.click(screen.getByRole('button', { name: 'Authorize account' }));
  await waitFor(() => expect(mocks.resume).toHaveBeenCalledWith('zoho-existing'));
  expect(mocks.start).not.toHaveBeenCalled();
  expect(popup.location.replace).toHaveBeenCalledWith('https://accounts.zoho.com/oauth/v2/auth');
});
