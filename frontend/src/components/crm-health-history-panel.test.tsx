import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CRMHealthHistoryPanel } from '@/components/crm-health-history-panel';
import type { CRMConnectionView, CRMHealthSnapshotView } from '@/lib/lead-crm-api';

const mocks = vi.hoisted(() => ({
  healthHistory: vi.fn(),
  runHealthCheck: vi.fn(),
}));

vi.mock('@/lib/lead-crm-api', () => ({
  leadCrmApi: {
    healthHistory: mocks.healthHistory,
    runHealthCheck: mocks.runHealthCheck,
  },
}));

const connections: CRMConnectionView[] = [
  {
    id: 'crm-1',
    public_id: 'crm_public_1',
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
    id: 'crm-2',
    public_id: 'crm_public_2',
    provider: 'hubspot',
    name: 'HubSpot Sales',
    environment: 'production',
    status: 'degraded',
    configuration: {},
    capabilities: {},
    created_at: '2026-09-12T08:00:00Z',
    updated_at: '2026-09-12T08:00:00Z',
  },
];

const healthySnapshot: CRMHealthSnapshotView = {
  id: 'snapshot-1',
  connection_id: 'crm-1',
  status: 'healthy',
  checks: { api: 'ok', credentials: 'configured' },
  latency_ms: 41,
  checked_at: '2026-09-12T09:00:00Z',
};

describe('CRMHealthHistoryPanel', () => {
  beforeEach(() => {
    mocks.healthHistory.mockImplementation(async (connectionId: string) => connectionId === 'crm-1'
      ? [healthySnapshot]
      : [{
          id: 'snapshot-2',
          connection_id: 'crm-2',
          status: 'degraded',
          checks: { api: 'slow' },
          latency_ms: null,
          checked_at: '2026-09-12T09:30:00Z',
        }]);
    mocks.runHealthCheck.mockResolvedValue(healthySnapshot);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders safe snapshot evidence and reloads history for the selected connection', async () => {
    const user = userEvent.setup();
    render(<CRMHealthHistoryPanel connections={connections} canManage />);

    expect(await screen.findByText('41 ms')).toBeInTheDocument();
    expect(screen.getByText(/configured/)).toBeInTheDocument();
    expect(mocks.healthHistory).toHaveBeenCalledWith('crm-1', 50);

    await user.selectOptions(screen.getByLabelText('CRM health history connection'), 'crm-2');

    await waitFor(() => expect(mocks.healthHistory).toHaveBeenCalledWith('crm-2', 50));
    expect(await screen.findByText(/slow/)).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('lets a CRM manager run a recorded check and refreshes the history afterward', async () => {
    const user = userEvent.setup();
    render(<CRMHealthHistoryPanel connections={connections.slice(0, 1)} canManage />);

    await screen.findByText('41 ms');
    await user.click(screen.getByRole('button', { name: 'Run recorded check' }));

    await waitFor(() => expect(mocks.runHealthCheck).toHaveBeenCalledWith('crm-1'));
    expect(await screen.findByRole('status')).toHaveTextContent('Recorded healthy health check.');
    await waitFor(() => expect(mocks.healthHistory).toHaveBeenCalledTimes(2));
  });

  it('keeps recorded health checks read-only for viewers', async () => {
    render(<CRMHealthHistoryPanel connections={connections.slice(0, 1)} canManage={false} />);

    expect(await screen.findByText('41 ms')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run recorded check' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh history' })).toBeInTheDocument();
  });

  it('refreshes the current connection history on demand without changing the selection', async () => {
    const user = userEvent.setup();
    render(<CRMHealthHistoryPanel connections={connections} canManage />);

    await screen.findByText('41 ms');
    await user.click(screen.getByRole('button', { name: 'Refresh history' }));

    await waitFor(() => expect(mocks.healthHistory).toHaveBeenCalledTimes(2));
    expect(mocks.healthHistory).toHaveBeenLastCalledWith('crm-1', 50);
    expect(screen.getByLabelText('CRM health history connection')).toHaveValue('crm-1');
  });
});
