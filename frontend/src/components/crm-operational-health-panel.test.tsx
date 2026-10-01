import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CRMOperationalHealthPanel } from '@/components/crm-operational-health-panel';

const mocks = vi.hoisted(() => ({
  health: vi.fn(),
}));

vi.mock('@/lib/crm-operations-api', () => ({
  crmOperationsApi: { health: mocks.health },
}));

const attentionHealth = {
  overall_status: 'attention' as const,
  connection_count: 1,
  healthy_connections: 1,
  attention_connections: 1,
  pending_deliveries: 2,
  retrying_deliveries: 1,
  failed_deliveries: 1,
  open_dead_letters: 1,
  connections: [{
    connection_id: 'connection-1',
    name: 'Zoho Production',
    provider: 'zoho',
    status: 'healthy',
    last_health_at: '2026-09-12T08:00:00Z',
    last_success_at: '2026-09-12T08:30:00Z',
    last_failure_at: null,
    last_error: null,
    pending_deliveries: 2,
    retrying_deliveries: 1,
    failed_deliveries: 1,
    open_dead_letters: 1,
  }],
};

describe('CRMOperationalHealthPanel', () => {
  beforeEach(() => {
    mocks.health.mockResolvedValue(attentionHealth);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders workspace CRM operational totals and per-connection evidence', async () => {
    render(<CRMOperationalHealthPanel />);

    expect(await screen.findByText('Zoho Production')).toBeInTheDocument();
    expect(screen.getByText('attention')).toBeInTheDocument();
    expect(screen.getByText('Pending deliveries')).toBeInTheDocument();
    expect(screen.getAllByText('Retrying').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('Open dead letters')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('1 failed delivery state(s) and 1 unresolved dead-letter incident(s)');
    expect(mocks.health).toHaveBeenCalledOnce();
  });

  it('refreshes current operational health on demand', async () => {
    const user = userEvent.setup();
    render(<CRMOperationalHealthPanel />);

    await screen.findByText('Zoho Production');
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(mocks.health).toHaveBeenCalledTimes(2));
  });

  it('shows an explicit empty state when the workspace has no CRM connections', async () => {
    mocks.health.mockResolvedValue({
      overall_status: 'empty',
      connection_count: 0,
      healthy_connections: 0,
      attention_connections: 0,
      pending_deliveries: 0,
      retrying_deliveries: 0,
      failed_deliveries: 0,
      open_dead_letters: 0,
      connections: [],
    });
    render(<CRMOperationalHealthPanel />);

    expect(await screen.findByText('No CRM operations to monitor')).toBeInTheDocument();
    expect(screen.getByText('Connect a CRM in this Workspace to begin monitoring delivery health.')).toBeInTheDocument();
  });
});
