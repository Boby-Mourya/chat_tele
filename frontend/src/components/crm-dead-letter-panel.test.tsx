import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CRMDeadLetterPanel } from '@/components/crm-dead-letter-panel';
import type { CRMConnectionView } from '@/lib/lead-crm-api';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  replay: vi.fn(),
  pushToast: vi.fn(),
  authRole: { current: 'owner' },
}));

vi.mock('@/components/providers', () => ({
  useAuth: () => ({ session: { user: { role: mocks.authRole.current } } }),
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/crm-dead-letter-api', () => ({
  crmDeadLetterApi: { list: mocks.list, replay: mocks.replay },
}));

const connection: CRMConnectionView = {
  id: 'connection-1',
  public_id: 'crm_public_1',
  provider: 'zoho',
  name: 'Zoho Production',
  environment: 'production',
  status: 'healthy',
  configuration: {},
  capabilities: {},
  created_at: '2026-09-12T08:00:00Z',
  updated_at: '2026-09-12T08:00:00Z',
};

const secondConnection: CRMConnectionView = {
  ...connection,
  id: 'connection-2',
  public_id: 'crm_public_2',
  provider: 'salesforce',
  name: 'Salesforce Production',
};

const openDeadLetter = {
  id: 'dead-letter-1',
  delivery_id: 'delivery-1',
  lead_id: 'lead-1',
  connection_id: 'connection-1',
  provider: 'zoho',
  status: 'open',
  reason_code: 'network_error',
  reason_message: 'Provider timed out',
  created_at: '2026-09-12T08:30:00Z',
  updated_at: '2026-09-12T08:30:00Z',
  resolved_at: null,
};

const resolvedDeadLetter = {
  ...openDeadLetter,
  id: 'dead-letter-2',
  delivery_id: 'delivery-2',
  lead_id: 'lead-2',
  connection_id: 'connection-2',
  provider: 'salesforce',
  status: 'resolved',
  reason_code: 'rate_limit_error',
  reason_message: 'Provider rate limit exhausted',
  resolved_at: '2026-09-12T09:00:00Z',
};

describe('CRMDeadLetterPanel', () => {
  beforeEach(() => {
    mocks.authRole.current = 'owner';
    mocks.list.mockImplementation(async ({ status, connectionId }: { status?: string; connectionId?: string }) => {
      const rows = [openDeadLetter, resolvedDeadLetter];
      return rows.filter((item) => (
        (!status || status === 'all' || item.status === status)
        && (!connectionId || item.connection_id === connectionId)
      ));
    });
    mocks.replay.mockResolvedValue({
      dead_letter_id: 'dead-letter-1',
      delivery_id: 'delivery-1',
      dead_letter_status: 'resolved',
      delivery_status: 'retrying',
      replayed_at: '2026-09-12T09:15:00Z',
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('loads open dead letters by default and renders safe operational context', async () => {
    render(<CRMDeadLetterPanel connections={[connection, secondConnection]} />);

    expect(await screen.findByText('Provider timed out')).toBeInTheDocument();
    expect(screen.getAllByText('Zoho Production').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('Lead lead-1')).toBeInTheDocument();
    expect(screen.getByText('Delivery delivery-1')).toBeInTheDocument();
    expect(screen.queryByText('Provider rate limit exhausted')).not.toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith({ status: 'open', connectionId: undefined });
  });

  it('refetches with status and connection filters', async () => {
    const user = userEvent.setup();
    render(<CRMDeadLetterPanel connections={[connection, secondConnection]} />);

    await screen.findByText('Provider timed out');
    await user.selectOptions(screen.getByRole('combobox', { name: 'CRM dead-letter status' }), 'all');
    expect(await screen.findByText('Provider rate limit exhausted')).toBeInTheDocument();
    await waitFor(() => expect(mocks.list).toHaveBeenCalledWith({ status: 'all', connectionId: undefined }));

    await user.selectOptions(screen.getByRole('combobox', { name: 'CRM dead-letter connection' }), 'connection-2');
    await waitFor(() => expect(mocks.list).toHaveBeenCalledWith({ status: 'all', connectionId: 'connection-2' }));
    await waitFor(() => expect(screen.queryByText('Provider timed out')).not.toBeInTheDocument());
    expect(screen.getAllByText('Salesforce Production').length).toBeGreaterThanOrEqual(2);
  });

  it('requires explicit confirmation before replaying an open dead letter', async () => {
    const user = userEvent.setup();
    render(<CRMDeadLetterPanel connections={[connection]} />);

    await screen.findByText('Provider timed out');
    await user.click(screen.getByRole('button', { name: 'Replay' }));
    expect(mocks.replay).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Confirm replay' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Confirm replay' }));
    await waitFor(() => expect(mocks.replay).toHaveBeenCalledWith('dead-letter-1'));
    expect(mocks.pushToast).toHaveBeenCalledWith('CRM replay queued · delivery retrying');
    await waitFor(() => expect(mocks.list.mock.calls.length).toBeGreaterThan(1));
  });

  it('can cancel a replay confirmation without mutating the dead letter', async () => {
    const user = userEvent.setup();
    render(<CRMDeadLetterPanel connections={[connection]} />);

    await screen.findByText('Provider timed out');
    await user.click(screen.getByRole('button', { name: 'Replay' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(mocks.replay).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Replay' })).toBeInTheDocument();
  });

  it('keeps replay read-only for users without CRM management access in the UI', async () => {
    mocks.authRole.current = 'member';
    render(<CRMDeadLetterPanel connections={[connection]} />);

    await screen.findByText('Provider timed out');
    expect(screen.getByText('Admin only')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Replay' })).not.toBeInTheDocument();
    expect(mocks.replay).not.toHaveBeenCalled();
  });

  it('shows an explicit healthy empty state when there are no open dead letters', async () => {
    mocks.list.mockResolvedValue([]);
    render(<CRMDeadLetterPanel connections={[connection]} />);

    expect(await screen.findByText('No open CRM dead letters')).toBeInTheDocument();
    expect(screen.getByText('Automatic CRM delivery has no unresolved dead-letter items in this Workspace.')).toBeInTheDocument();
  });
});
