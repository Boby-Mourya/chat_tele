import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChannelOperationalHealthPanel } from '@/components/channel-operational-health-panel';

const mocks = vi.hoisted(() => ({
  health: vi.fn(),
  deliveries: vi.fn(),
  webhookEvents: vi.fn(),
  requeue: vi.fn(),
  useAuth: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useAuth: mocks.useAuth,
}));

vi.mock('@/lib/channel-operations-api', () => ({
  channelOperationsApi: { health: mocks.health },
}));

vi.mock('@/lib/channel-deliveries-api', () => ({
  channelDeliveriesApi: { list: mocks.deliveries, requeue: mocks.requeue },
}));

vi.mock('@/lib/channel-webhook-events-api', () => ({
  channelWebhookEventsApi: { list: mocks.webhookEvents },
}));

const attentionHealth = {
  overall_status: 'attention' as const,
  connection_count: 1,
  healthy_connections: 0,
  attention_connections: 1,
  pending_deliveries: 2,
  retrying_deliveries: 1,
  failed_deliveries: 1,
  pending_webhook_events: 3,
  failed_webhook_events: 1,
  rejected_webhook_events: 2,
  stale_webhook_events: 1,
  connections: [{
    connection_id: 'connection-1',
    name: 'Student Telegram',
    provider: 'telegram',
    status: 'healthy',
    last_health_at: '2026-09-12T08:00:00Z',
    last_event_at: '2026-09-12T08:30:00Z',
    last_failure_at: null,
    last_error: null,
    pending_deliveries: 2,
    retrying_deliveries: 1,
    failed_deliveries: 1,
    pending_webhook_events: 3,
    failed_webhook_events: 1,
    rejected_webhook_events: 2,
    stale_webhook_events: 1,
  }],
};

describe('ChannelOperationalHealthPanel', () => {
  beforeEach(() => {
    mocks.useAuth.mockReturnValue({ session: { user: { role: 'admin' } } });
    mocks.health.mockResolvedValue(attentionHealth);
    mocks.deliveries.mockResolvedValue([]);
    mocks.webhookEvents.mockResolvedValue([]);
    mocks.requeue.mockResolvedValue(null);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders Workspace outbound and inbound operational totals without eager detail loads', async () => {
    render(<ChannelOperationalHealthPanel />);

    expect(await screen.findByText('Student Telegram')).toBeInTheDocument();
    expect(screen.getByText('attention')).toBeInTheDocument();
    expect(screen.getByText('Pending deliveries')).toBeInTheDocument();
    expect(screen.getAllByText('Retrying').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('Terminal failures')).toBeInTheDocument();
    expect(screen.getAllByText('Inbound pending').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Inbound failed').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Inbound rejected').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Inbound stale').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole('status')).toHaveTextContent(
      '1 terminal outbound delivery failure state(s), 1 failed inbound webhook event(s), and 1 stale inbound webhook event(s)',
    );
    expect(mocks.health).toHaveBeenCalledOnce();
    expect(mocks.deliveries).not.toHaveBeenCalled();
    expect(mocks.webhookEvents).not.toHaveBeenCalled();
  });

  it('refreshes channel operational health on demand', async () => {
    const user = userEvent.setup();
    render(<ChannelOperationalHealthPanel />);

    await screen.findByText('Student Telegram');
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(mocks.health).toHaveBeenCalledTimes(2));
  });

  it('loads individual delivery evidence only after the user opens it', async () => {
    const user = userEvent.setup();
    render(<ChannelOperationalHealthPanel />);

    await screen.findByText('Student Telegram');
    expect(mocks.deliveries).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'View delivery evidence' }));

    await waitFor(() => expect(mocks.deliveries).toHaveBeenCalledWith({
      connectionId: undefined,
      status: undefined,
      limit: 100,
    }));
    expect(screen.getByRole('option', { name: 'Student Telegram · telegram' })).toBeInTheDocument();
    expect(mocks.webhookEvents).not.toHaveBeenCalled();
  });

  it('loads inbound webhook evidence only after the user opens it', async () => {
    const user = userEvent.setup();
    render(<ChannelOperationalHealthPanel />);

    await screen.findByText('Student Telegram');
    expect(mocks.webhookEvents).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'View webhook activity' }));

    await waitFor(() => expect(mocks.webhookEvents).toHaveBeenCalledWith({
      connectionId: undefined,
      processingStatus: undefined,
      provider: undefined,
      limit: 100,
    }));
    expect(await screen.findByText('Channel inbound webhook activity')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Student Telegram · telegram' })).toBeInTheDocument();
    expect(mocks.deliveries).not.toHaveBeenCalled();
  });

  it('shows an explicit empty state when the Workspace has no channel connections', async () => {
    mocks.health.mockResolvedValue({
      overall_status: 'empty',
      connection_count: 0,
      healthy_connections: 0,
      attention_connections: 0,
      pending_deliveries: 0,
      retrying_deliveries: 0,
      failed_deliveries: 0,
      pending_webhook_events: 0,
      failed_webhook_events: 0,
      rejected_webhook_events: 0,
      stale_webhook_events: 0,
      connections: [],
    });
    render(<ChannelOperationalHealthPanel />);

    expect(await screen.findByText('No channel operations to monitor')).toBeInTheDocument();
    expect(screen.getByText('Connect a provider-neutral messaging channel in this Workspace to begin monitoring delivery health.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'View delivery evidence' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'View webhook activity' })).not.toBeInTheDocument();
  });
});
