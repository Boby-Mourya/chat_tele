import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CRMWebhookEventsPanel } from '@/components/crm-webhook-events-panel';
import type { CRMConnectionView } from '@/lib/lead-crm-api';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
}));

vi.mock('@/lib/crm-webhook-events-api', () => ({
  crmWebhookEventsApi: { list: mocks.list },
}));

const connections: CRMConnectionView[] = [
  {
    id: 'connection-1',
    public_id: 'crm_connection_1',
    provider: 'zoho',
    name: 'Zoho Production',
    environment: 'production',
    status: 'healthy',
    configuration: {},
    capabilities: {},
    created_at: '2026-09-12T08:00:00Z',
    updated_at: '2026-09-12T08:00:00Z',
  },
  {
    id: 'connection-2',
    public_id: 'crm_connection_2',
    provider: 'hubspot',
    name: 'HubSpot Sales',
    environment: 'production',
    status: 'healthy',
    configuration: {},
    capabilities: {},
    created_at: '2026-09-12T08:00:00Z',
    updated_at: '2026-09-12T08:00:00Z',
  },
];

const events = [
  {
    id: 'event-1',
    connection_id: 'connection-1',
    provider: 'zoho',
    event_type: 'record.updated',
    verification_status: 'verified',
    processing_status: 'processed',
    correlation_id: 'corr-1',
    received_at: '2026-09-12T09:00:00Z',
    processed_at: '2026-09-12T09:00:01Z',
    last_error: null,
  },
  {
    id: 'event-2',
    connection_id: 'connection-2',
    provider: 'hubspot',
    event_type: 'contact.changed',
    verification_status: 'verified',
    processing_status: 'ignored',
    correlation_id: 'corr-2',
    received_at: '2026-09-12T09:05:00Z',
    processed_at: '2026-09-12T09:05:01Z',
    last_error: 'no_effective_changes',
  },
];

describe('CRMWebhookEventsPanel', () => {
  beforeEach(() => {
    mocks.list.mockResolvedValue(events);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders safe webhook processing evidence without raw webhook content', async () => {
    render(<CRMWebhookEventsPanel connections={connections} />);

    expect(await screen.findByText('Zoho Production')).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: /^HubSpot Sales/ })).toBeInTheDocument();
    expect(screen.getByText('record.updated')).toBeInTheDocument();
    expect(screen.getByText('contact.changed')).toBeInTheDocument();
    expect(screen.getByText('no_effective_changes')).toBeInTheDocument();
    expect(screen.getByText(/Correlation corr-1/)).toBeInTheDocument();
    expect(screen.queryByText('super-secret-webhook-payload')).not.toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith({ connectionId: undefined, processingStatus: undefined, limit: 100 });
  });

  it('reloads with connection and processing-status filters and supports refresh', async () => {
    const user = userEvent.setup();
    render(<CRMWebhookEventsPanel connections={connections} />);
    await screen.findByText('Zoho Production');

    await user.selectOptions(screen.getByLabelText('CRM webhook connection'), 'connection-1');
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith({
      connectionId: 'connection-1', processingStatus: undefined, limit: 100,
    }));

    await user.selectOptions(screen.getByLabelText('CRM webhook processing status'), 'ignored');
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith({
      connectionId: 'connection-1', processingStatus: 'ignored', limit: 100,
    }));

    const beforeRefresh = mocks.list.mock.calls.length;
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(mocks.list.mock.calls.length).toBe(beforeRefresh + 1));
  });
});
