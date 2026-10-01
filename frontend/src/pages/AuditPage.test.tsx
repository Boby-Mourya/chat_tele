import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuditPage } from '@/pages/AuditPage';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  exportCsv: vi.fn(),
  pushToast: vi.fn(),
}));

vi.mock('@/lib/audit-api', () => ({
  auditApi: { list: mocks.list, exportCsv: mocks.exportCsv },
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

const event = {
  id: 'audit-1',
  tenantId: 'tenant-1',
  workspaceId: 'workspace-1',
  actorUserId: 'user-1',
  action: 'workspace.patch',
  entityType: 'workspace',
  entityId: '/workspace',
  category: 'workspace',
  severity: 'info',
  outcome: 'success',
  before: {},
  after: {},
  metadata: { method: 'PATCH', route: '/workspace', statusCode: 200 },
  requestId: 'request-1',
  ipAddress: '127.0.0.1',
  userAgent: 'Vitest',
  createdAt: '2026-09-11T00:00:00Z',
};

describe('AuditPage', () => {
  beforeEach(() => {
    mocks.list.mockResolvedValue([event]);
    mocks.exportCsv.mockResolvedValue(new Blob(['created_at,action\r\n'], { type: 'text/csv' }));
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:audit-export'),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('renders durable audit metadata and reloads when filters change', async () => {
    const user = userEvent.setup();
    render(<AuditPage />);

    expect(await screen.findByText('workspace.patch')).toBeInTheDocument();
    expect(screen.getByText(/workspace · \/workspace/)).toBeInTheDocument();
    expect(screen.getByText('Visible events')).toBeInTheDocument();
    expect(screen.getByText(/"method": "PATCH"/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Audit category'), 'security');
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({
      category: 'security',
      limit: 200,
    })));
  });

  it('exports the currently filtered audit trail', async () => {
    const user = userEvent.setup();
    render(<AuditPage />);
    await screen.findByText('workspace.patch');

    await user.selectOptions(screen.getByLabelText('Audit outcome'), 'failure');
    await user.click(screen.getByRole('button', { name: 'Export CSV' }));

    await waitFor(() => expect(mocks.exportCsv).toHaveBeenCalledWith(expect.objectContaining({
      outcome: 'failure',
      limit: 200,
    })));
    expect(mocks.pushToast).toHaveBeenCalledWith('Audit CSV exported');
  });
});
