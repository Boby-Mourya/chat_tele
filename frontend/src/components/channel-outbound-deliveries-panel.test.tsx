import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChannelOutboundDeliveriesPanel } from '@/components/channel-outbound-deliveries-panel';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  attempts: vi.fn(),
  requeue: vi.fn(),
  useAuth: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useAuth: mocks.useAuth,
}));

vi.mock('@/lib/channel-deliveries-api', () => ({
  channelDeliveriesApi: {
    list: mocks.list,
    attempts: mocks.attempts,
    requeue: mocks.requeue,
  },
}));

const connections = [{
  id: 'channel-1',
  provider: 'telegram',
  name: 'Primary Telegram',
}];

const delivery = {
  id: 'delivery-1',
  connection_id: 'channel-1',
  connection_name: 'Primary Telegram',
  message_id: 'message-safe-reference',
  provider: 'telegram',
  status: 'failed',
  error_code: 'retryable_failure',
  attempt_count: 2,
  dispatch_attempts: 3,
  dispatched_at: '2026-09-12T18:30:00Z',
  processed_at: null,
  next_dispatch_at: '2026-09-12T18:35:00Z',
  created_at: '2026-09-12T18:29:00Z',
  updated_at: '2026-09-12T18:31:00Z',
};

const dispatchFailedDelivery = {
  ...delivery,
  id: 'dispatch-failure-1',
  status: 'dispatch_failed',
  error_code: 'dispatch_failed',
  dispatch_attempts: 8,
  next_dispatch_at: null,
};

const attempts = [{
  id: 'attempt-2',
  delivery_id: 'delivery-1',
  phase: 'provider',
  attempt_number: 2,
  outcome: 'failed',
  error_code: 'provider_retryable',
  created_at: '2026-09-12T18:31:00Z',
}, {
  id: 'attempt-1',
  delivery_id: 'delivery-1',
  phase: 'dispatch',
  attempt_number: 1,
  outcome: 'published',
  error_code: null,
  created_at: '2026-09-12T18:29:30Z',
}];

describe('ChannelOutboundDeliveriesPanel', () => {
  beforeEach(() => {
    mocks.useAuth.mockReturnValue({ session: { user: { role: 'admin' } } });
    mocks.list.mockResolvedValue([delivery]);
    mocks.attempts.mockResolvedValue(attempts);
    mocks.requeue.mockResolvedValue({
      ...dispatchFailedDelivery,
      status: 'queued',
      error_code: null,
      dispatch_attempts: 0,
      dispatched_at: null,
      next_dispatch_at: '2026-09-12T18:40:00Z',
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows only safe outbound delivery evidence without loading attempts eagerly', async () => {
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    expect(await screen.findByText('Primary Telegram')).toBeInTheDocument();
    expect(screen.getByText('retryable_failure')).toBeInTheDocument();
    expect(screen.getByText('message-safe-reference')).toBeInTheDocument();
    expect(screen.getByText('Provider 2')).toBeInTheDocument();
    expect(screen.getByText('Dispatch 3')).toBeInTheDocument();
    expect(screen.queryByText('private-recipient-42')).not.toBeInTheDocument();
    expect(screen.queryByText('provider-secret-id')).not.toBeInTheDocument();
    expect(screen.queryByText('Bearer secret-token provider response body')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Requeue dispatch' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View attempts' })).toBeInTheDocument();
    expect(mocks.attempts).not.toHaveBeenCalled();
    expect(mocks.list).toHaveBeenCalledWith({
      connectionId: undefined,
      status: undefined,
      limit: 100,
    });
  });

  it('loads safe attempt history only after the selected delivery is opened', async () => {
    const user = userEvent.setup();
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    await screen.findByText('message-safe-reference');
    expect(mocks.attempts).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'View attempts' }));

    await waitFor(() => expect(mocks.attempts).toHaveBeenCalledWith('delivery-1', 100));
    expect(await screen.findByText('Delivery attempt history')).toBeInTheDocument();
    expect(screen.getByText('provider_retryable')).toBeInTheDocument();
    expect(screen.getByText('published')).toBeInTheDocument();
    expect(screen.queryByText('private-recipient-42')).not.toBeInTheDocument();
    expect(screen.queryByText('provider-secret-id')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Close attempts' }));
    expect(screen.queryByText('Delivery attempt history')).not.toBeInTheDocument();
  });

  it('refreshes attempt history without reloading the delivery list', async () => {
    const user = userEvent.setup();
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    await screen.findByText('message-safe-reference');
    await user.click(screen.getByRole('button', { name: 'View attempts' }));
    await screen.findByText('provider_retryable');
    expect(mocks.attempts).toHaveBeenCalledTimes(1);
    expect(mocks.list).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Refresh attempts' }));
    await waitFor(() => expect(mocks.attempts).toHaveBeenCalledTimes(2));
    expect(mocks.list).toHaveBeenCalledTimes(1);
  });

  it('reloads using selected connection and status filters', async () => {
    const user = userEvent.setup();
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    await screen.findByText('message-safe-reference');
    await user.selectOptions(screen.getByLabelText('Channel delivery connection'), 'channel-1');
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith({
      connectionId: 'channel-1',
      status: undefined,
      limit: 100,
    }));

    await user.selectOptions(screen.getByLabelText('Channel delivery status'), 'failed');
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith({
      connectionId: 'channel-1',
      status: 'failed',
      limit: 100,
    }));
  });

  it('refreshes the current delivery view on demand', async () => {
    const user = userEvent.setup();
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    await screen.findByText('message-safe-reference');
    await user.click(screen.getByRole('button', { name: 'Refresh deliveries' }));
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  });

  it('lets an admin requeue only an exhausted dispatch failure and reloads evidence', async () => {
    const user = userEvent.setup();
    mocks.list.mockResolvedValue([dispatchFailedDelivery]);
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    expect((await screen.findAllByText('dispatch_failed')).length).toBeGreaterThanOrEqual(2);
    await user.click(screen.getByRole('button', { name: 'Requeue dispatch' }));

    await waitFor(() => expect(mocks.requeue).toHaveBeenCalledWith('dispatch-failure-1'));
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Dispatch failure requeued through the existing channel dispatcher.',
    );
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  });

  it('keeps dispatch recovery hidden from viewers while attempt history stays readable', async () => {
    mocks.useAuth.mockReturnValue({ session: { user: { role: 'member' } } });
    mocks.list.mockResolvedValue([dispatchFailedDelivery]);
    render(<ChannelOutboundDeliveriesPanel connections={connections} />);

    expect((await screen.findAllByText('dispatch_failed')).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByRole('button', { name: 'Requeue dispatch' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View attempts' })).toBeInTheDocument();
    expect(mocks.requeue).not.toHaveBeenCalled();
  });

  it('shows an explicit empty state', async () => {
    mocks.list.mockResolvedValue([]);
    render(<ChannelOutboundDeliveriesPanel connections={[]} />);

    expect(await screen.findByText('No outbound delivery evidence found')).toBeInTheDocument();
    expect(mocks.attempts).not.toHaveBeenCalled();
  });
});
