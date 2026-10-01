import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppShell } from '@/components/app-shell';

const mocks = vi.hoisted(() => ({
  selectWorkspace: vi.fn(),
  createWorkspace: vi.fn(),
  logout: vi.fn(),
  pushToast: vi.fn(),
  canAccess: vi.fn(),
}));

vi.mock('@/components/NotificationBell', () => ({
  NotificationBell: () => <button type="button">Notifications</button>,
}));

vi.mock('@/components/providers', () => ({
  useAuth: () => ({
    session: {
      accessToken: 'access-token',
      user: {
        id: 'user-1',
        name: 'Workspace Owner',
        email: 'owner@example.com',
        role: 'owner',
        emailVerified: true,
      },
    },
    logout: mocks.logout,
  }),
  useToast: () => ({ pushToast: mocks.pushToast }),
  useWorkspace: () => ({
    workspaces: [
      {
        id: 'workspace-1',
        name: 'Northstar Academy',
        slug: 'northstar',
        role: 'workspace_admin',
        permissions: ['*'],
      },
      {
        id: 'workspace-2',
        name: 'CPA Division',
        slug: 'cpa',
        role: 'manager',
        permissions: ['agents.view'],
      },
    ],
    activeWorkspace: {
      id: 'workspace-1',
      name: 'Northstar Academy',
      slug: 'northstar',
      role: 'workspace_admin',
      permissions: ['*'],
    },
    loading: false,
    selectWorkspace: mocks.selectWorkspace,
    createWorkspace: mocks.createWorkspace,
  }),
}));

vi.mock('@/lib/platform-admin-api', () => ({
  platformAdminApi: { canAccess: mocks.canAccess },
}));

function renderShell() {
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<div>Overview content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('AppShell command palette integration', () => {
  beforeEach(() => {
    mocks.canAccess.mockResolvedValue(false);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('opens the palette from the existing Search button', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(screen.getByRole('dialog', { name: 'Search and commands' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Search pages and workspaces' })).toHaveFocus();
  });

  it('opens and closes the palette with Ctrl+K', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.keyboard('{Control>}k{/Control}');
    expect(screen.getByRole('dialog', { name: 'Search and commands' })).toBeInTheDocument();

    await user.keyboard('{Control>}k{/Control}');
    expect(screen.queryByRole('dialog', { name: 'Search and commands' })).not.toBeInTheDocument();
  });

  it('opens the same palette from the floating command button', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole('button', { name: 'Open command palette' }));

    expect(screen.getByRole('dialog', { name: 'Search and commands' })).toBeInTheDocument();
  });
});
