import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WhatsAppEmbeddedSignupModal as WhatsAppIntegrationModal } from './whatsapp-integration-modal';

const mocks = vi.hoisted(() => ({ bootstrap: vi.fn(), status: vi.fn(), list: vi.fn(), activity: vi.fn() }));
vi.mock('@/components/providers', () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock('@/lib/api', () => ({ ApiError: class extends Error {}, api: { integrations: { whatsapp: mocks }, agents: { list: mocks.list } } }));
vi.mock('@/lib/meta-whatsapp', () => ({
  MetaSignupError: class extends Error {}, loadFacebookSdk: vi.fn(), getFacebookLoginStatus: vi.fn().mockResolvedValue('unknown'), logoutFacebook: vi.fn(), startWhatsAppEmbeddedSignup: vi.fn(),
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it('shows the callback and missing configuration without claiming readiness', async () => {
  mocks.bootstrap.mockResolvedValue({ enabled: false, connections: [], webhookUrl: 'http://localhost:8100/api/v1/webhooks/whatsapp', missingSettings: ['META_APP_ID'] });
  mocks.status.mockResolvedValue({ enabled: false, connected: false, connections: [] });
  mocks.list.mockResolvedValue([]);
  render(<WhatsAppIntegrationModal open onClose={vi.fn()} onConnectionChanged={vi.fn()} />);
  expect(await screen.findByLabelText('Meta webhook callback URL')).toHaveValue('http://localhost:8100/api/v1/webhooks/whatsapp');
  expect(screen.getByText(/Missing server settings: META_APP_ID/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Meta setup required' })).toBeDisabled();
});

it('does not claim webhook delivery before the first event', async () => {
  const connection = { agentId: 'agent', status: 'connected', displayPhoneNumber: '+15550100', wabaId: '555', phoneNumberId: '777', connectedAt: '2026-09-14T00:00:00Z' };
  mocks.bootstrap.mockResolvedValue({ enabled: true, connections: [connection], appId: '123', configurationId: '456', signupSession: 'session' });
  mocks.status.mockResolvedValue({ enabled: true, connected: true, connections: [connection] });
  mocks.list.mockResolvedValue([{ id: 'agent', name: 'Draft bot', status: 'draft' }]);
  mocks.activity.mockResolvedValue({ inbound: [], deliveries: [], lastError: null });
  render(<WhatsAppIntegrationModal open onClose={vi.fn()} onConnectionChanged={vi.fn()} />);
  expect(await screen.findByText('Waiting for your first WhatsApp message')).toBeInTheDocument();
  expect(screen.getByRole('option', { name: /Draft bot/ })).toBeInTheDocument();
  expect(screen.queryByText('Webhook delivery is active')).not.toBeInTheDocument();
});
