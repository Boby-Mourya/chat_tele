import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChannelHealthHistoryPanel } from '@/components/channel-health-history-panel';
import type { ChannelHealthSnapshotView } from '@/lib/channel-health-history-api';
import type { ChannelConnectionView } from '@/lib/lead-crm-api';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
}));

vi.mock('@/lib/channel-health-history-api', () => ({
  channelHealthHistoryApi: {
    list: mocks.list,
  },
}));

const connections: ChannelConnectionView[] = [
  {
    id: 'channel-1',
    public_id: 'chn_public_1',
    workspace_id: 'workspace-1',
    agent_id: 'agent-1',
    provider: 'telegram',
    name: 'Student Telegram',
    status: 'healthy',
    configuration: {},
    created_at: '2026-09-12T08:00:00Z',
    updated_at: '2026-09-12T08:00:00Z',
  },
  {
    id: 'channel-2',
    public_id: 'chn_public_2',
    workspace_id: 'workspace-1',
    agent_id: 'agent-2',
    provider: 'slack',
    name: 'Support Slack',
    status: 'auth_required',
    configuration: {},
    created_at: '2026-09-12T08:00:00Z',
    updated_at: '2026-09-12T08:00:00Z',
  },
];

const healthySnapshot: ChannelHealthSnapshotView = {
  id: 'snapshot-1',
  connection_id: 'channel-1',
  status: 'healthy',
  error_code: null,
  checked_at: '2026-09-12T18:30:00Z',
};

const authSnapshot: ChannelHealthSnapshotView = {
  id: 'snapshot-2',
  connection_id: 'channel-2',
  status: 'auth_required',
  error_code: 'credential_error',
  checked_at: '2026-09-12T18:35:00Z',
};

describe('ChannelHealthHistoryPanel', () => {
  beforeEach(() => {
    mocks.list.mockImplementation(async (connectionId: string) => connectionId === 'channel-1'
      ? [healthySnapshot]
      : [authSnapshot]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders only the safe scheduled health evidence for the selected channel', async () => {
    render(<ChannelHealthHistoryPanel connections={connections} />);

    expect(await screen.findByText('healthy')).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith('channel-1', 50);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.getByText(/Provider payloads, headers, identities, and credentials are never shown here/)).toBeInTheDocument();
    expect(screen.queryByText('access_token')).not.toBeInTheDocument();
  });

  it('loads the newly selected connection and displays only its normalized error code', async () => {
    const user = userEvent.setup();
    render(<ChannelHealthHistoryPanel connections={connections} />);

    await screen.findByText('healthy');
    await user.selectOptions(screen.getByLabelText('Channel health history connection'), 'channel-2');

    await waitFor(() => expect(mocks.list).toHaveBeenCalledWith('channel-2', 50));
    expect(await screen.findByText('auth_required')).toBeInTheDocument();
    expect(screen.getByText('credential_error')).toBeInTheDocument();
  });

  it('refreshes the current channel history without changing the selection', async () => {
    const user = userEvent.setup();
    render(<ChannelHealthHistoryPanel connections={connections} />);

    await screen.findByText('healthy');
    await user.click(screen.getByRole('button', { name: 'Refresh history' }));

    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
    expect(mocks.list).toHaveBeenLastCalledWith('channel-1', 50);
    expect(screen.getByLabelText('Channel health history connection')).toHaveValue('channel-1');
  });

  it('shows an empty-state without calling the API when there are no channel connections', async () => {
    render(<ChannelHealthHistoryPanel connections={[]} />);

    expect(screen.getByRole('heading', { name: 'No channel health history yet' })).toBeInTheDocument();
    expect(mocks.list).not.toHaveBeenCalled();
  });
});
