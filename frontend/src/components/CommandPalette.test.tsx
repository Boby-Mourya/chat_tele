import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ComponentProps } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CommandPalette } from '@/components/CommandPalette';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const workspace = (id: string, name: string, slug: string): WorkspaceSettings => ({
  id,
  name,
  slug,
  plan: 'business',
  memberCount: 1,
  role: 'workspace_admin',
  permissions: ['*'],
  preferences: { timezone: 'UTC', defaultLanguage: 'English', dateFormat: 'DD/MM/YYYY' },
  security: { sensitiveDataMasking: true, securityContact: null },
  whiteLabel: {
    companyName: name,
    logoDataUrl: '',
    faviconDataUrl: '',
    appIconDataUrl: '',
    primaryColor: '#000000',
    secondaryColor: '#ffffff',
    supportEmail: null,
    supportUrl: '',
    browserTitle: name,
    customDomain: '',
    dnsStatus: 'not-configured',
    brandedLogin: true,
    brandedDashboard: true,
    brandedWidget: true,
    brandedEmails: true,
    removePlatformBranding: false,
  },
});

const navigation = [
  { to: '/', label: 'Overview' },
  { to: '/agents', label: 'Agents' },
  { to: '/leads', label: 'Leads' },
];

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPalette(overrides: Partial<ComponentProps<typeof CommandPalette>> = {}) {
  const onClose = vi.fn();
  const onSelectWorkspace = vi.fn();
  const workspaces = [
    workspace('workspace-1', 'Northstar Academy', 'northstar'),
    workspace('workspace-2', 'CPA Division', 'cpa'),
  ];
  render(
    <MemoryRouter initialEntries={['/']}>
      <CommandPalette
        open
        onClose={onClose}
        navigation={navigation}
        workspaces={workspaces}
        activeWorkspaceId="workspace-1"
        onSelectWorkspace={onSelectWorkspace}
        {...overrides}
      />
      <LocationProbe />
    </MemoryRouter>,
  );
  return { onClose, onSelectWorkspace };
}

describe('CommandPalette', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('filters destinations and navigates to the selected page', async () => {
    const user = userEvent.setup();
    const { onClose } = renderPalette();

    const search = screen.getByRole('textbox', { name: 'Search pages and workspaces' });
    await user.type(search, 'agents');

    expect(screen.getByRole('option', { name: /Agents/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Overview/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('option', { name: /Agents/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('/agents');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('switches workspace without navigating away from the current page', async () => {
    const user = userEvent.setup();
    const { onClose, onSelectWorkspace } = renderPalette();

    await user.type(screen.getByRole('textbox', { name: 'Search pages and workspaces' }), 'CPA');
    await user.click(screen.getByRole('option', { name: /CPA Division/ }));

    expect(onSelectWorkspace).toHaveBeenCalledWith('workspace-2');
    expect(screen.getByTestId('location')).toHaveTextContent('/');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('supports arrow-key selection, Enter execution, and Escape close', async () => {
    const user = userEvent.setup();
    const first = renderPalette({ workspaces: [] });
    const search = screen.getByRole('textbox', { name: 'Search pages and workspaces' });

    await user.click(search);
    await user.keyboard('{ArrowDown}{Enter}');
    expect(screen.getByTestId('location')).toHaveTextContent('/agents');
    expect(first.onClose).toHaveBeenCalledTimes(1);

    cleanup();
    const second = renderPalette({ workspaces: [] });
    await user.keyboard('{Escape}');
    expect(second.onClose).toHaveBeenCalledTimes(1);
  });

  it('exposes platform administration only when the caller permits it', async () => {
    const user = userEvent.setup();
    const first = renderPalette({ canViewPlatformAdmin: false });
    await user.type(screen.getByRole('textbox', { name: 'Search pages and workspaces' }), 'platform');
    expect(screen.queryByRole('option', { name: /Platform control plane/ })).not.toBeInTheDocument();
    expect(first.onClose).not.toHaveBeenCalled();

    cleanup();
    renderPalette({ canViewPlatformAdmin: true });
    await user.type(screen.getByRole('textbox', { name: 'Search pages and workspaces' }), 'platform');
    expect(screen.getByRole('option', { name: /Platform control plane/ })).toBeInTheDocument();
  });
});
