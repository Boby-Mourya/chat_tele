import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceAPIKeysPanel } from '@/components/WorkspaceAPIKeysPanel';
import type { WorkspaceAPIKeyCreated } from '@/lib/workspace-api-keys';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  list: vi.fn(),
  create: vi.fn(),
  revoke: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/workspace-api-keys', () => ({
  WORKSPACE_API_KEY_SCOPES: ['workspace:read', 'conversations:read', 'conversations:write', 'contacts:read', 'leads:write', 'agents:read', 'analytics:read', 'webhooks:manage'],
  workspaceAPIKeyApi: {
    list: mocks.list,
    create: mocks.create,
    revoke: mocks.revoke,
  },
}));

const workspace: WorkspaceSettings = {
  id: 'workspace-1',
  tenantId: 'tenant-1',
  tenantName: 'Northstar Academy',
  name: 'Admissions',
  slug: 'admissions',
  status: 'active',
  role: 'workspace_admin',
  permissions: ['*'],
  plan: 'business',
  memberCount: 2,
  preferences: {
    timezone: 'Asia/Calcutta',
    defaultLanguage: 'English',
    dateFormat: 'DD/MM/YYYY',
  },
  security: { sensitiveDataMasking: true, securityContact: null },
  whiteLabel: {
    companyName: 'Northstar Academy',
    logoDataUrl: '',
    faviconDataUrl: '',
    appIconDataUrl: '',
    primaryColor: '#146cf6',
    secondaryColor: '#705cf6',
    supportEmail: 'support@example.com',
    supportUrl: 'https://example.com/support',
    browserTitle: 'Northstar',
    customDomain: '',
    dnsStatus: 'not-configured',
    brandedLogin: true,
    brandedDashboard: true,
    brandedWidget: true,
    brandedEmails: true,
    removePlatformBranding: false,
  },
};

const existingKey = {
  id: 'key-1',
  name: 'Production 1',
  prefix: 'nsk_live_example',
  createdAt: '2026-09-10T00:00:00Z',
  lastUsedAt: null,
  scopes: ['conversations:read'] as const,
};

const createdKey: WorkspaceAPIKeyCreated = {
  id: 'key-2',
  name: 'Production 2',
  prefix: 'nsk_live_created',
  secret: 'nsk_live_created-full-secret-value',
  createdAt: '2026-09-11T00:00:00Z',
  lastUsedAt: null,
  scopes: ['conversations:read'] as const,
};

describe('WorkspaceAPIKeysPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('confirm', vi.fn(() => true));
    mocks.list.mockResolvedValue([existingKey]);
    mocks.create.mockResolvedValue(createdKey);
    mocks.revoke.mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('loads server-backed keys and shows a newly created secret only once', async () => {
    const user = userEvent.setup();
    render(<WorkspaceAPIKeysPanel workspace={workspace} />);

    expect(await screen.findByText('Production 1')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create secret key' }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith('Production', ['workspace:read', 'conversations:read', 'agents:read']));
    expect(await screen.findByText('nsk_live_created-full-secret-value')).toBeInTheDocument();
    expect(screen.getByText('Production 2')).toBeInTheDocument();
    expect(localStorage.getItem('northstar.workspace.api-keys')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Hide new API key' }));
    expect(screen.queryByText('nsk_live_created-full-secret-value')).not.toBeInTheDocument();
  });

  it('revokes a key through the backend and removes it from the active list', async () => {
    const user = userEvent.setup();
    render(<WorkspaceAPIKeysPanel workspace={workspace} />);
    expect(await screen.findByText('Production 1')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Revoke Production 1' }));

    await waitFor(() => expect(mocks.revoke).toHaveBeenCalledWith('key-1'));
    expect(screen.queryByText('Production 1')).not.toBeInTheDocument();
  });

  it('does not request or expose API keys to users without API-key permissions', () => {
    render(<WorkspaceAPIKeysPanel workspace={{ ...workspace, permissions: ['workspace.view'] }} />);

    expect(screen.getByText('API key access is restricted')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create secret key' })).not.toBeInTheDocument();
    expect(mocks.list).not.toHaveBeenCalled();
  });

  it('keeps the existing demo/offline capability when permission metadata is absent', async () => {
    render(<WorkspaceAPIKeysPanel workspace={{ ...workspace, permissions: undefined }} />);

    expect(await screen.findByText('Production 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create secret key' })).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledTimes(1);
  });
});
