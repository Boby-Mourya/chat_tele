// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MaterialmAppShell } from './MaterialmAppShell';

const mocks = vi.hoisted(() => ({
  logout: vi.fn(), selectWorkspace: vi.fn(), createWorkspace: vi.fn(), pushToast: vi.fn(), canAccess: vi.fn(),
}));
vi.mock('@/components/providers', () => ({
  useAuth: () => ({ session: { accessToken: 'test-session', user: { name: 'Test Owner', email: 'owner@example.test', role: 'owner' } }, logout: mocks.logout }),
  useToast: () => ({ pushToast: mocks.pushToast }),
  useWorkspace: () => ({ loading: false, activeWorkspace: { id: 'a', name: 'Academy A', permissions: ['*'] }, workspaces: [
    { id: 'a', name: 'Academy A', role: 'workspace_admin' }, { id: 'b', name: 'Academy B', role: 'workspace_admin' },
  ], selectWorkspace: mocks.selectWorkspace, createWorkspace: mocks.createWorkspace }),
}));
vi.mock('@/lib/platform-admin-api', () => ({ platformAdminApi: { canAccess: mocks.canAccess } }));
vi.mock('@/components/brand', () => ({ Brand: () => <span>Northstar</span> }));
vi.mock('@/components/NotificationBell', () => ({ NotificationBell: () => <button type="button">Notifications</button> }));
vi.mock('@/components/CommandPalette', () => ({ CommandPalette: ({ open }: { open: boolean }) => open ? <div role="dialog" aria-label="Search and commands">Command search</div> : null }));

const originalShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal');
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close');
beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks(); mocks.canAccess.mockResolvedValue(false); mocks.logout.mockResolvedValue(undefined);
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.setAttribute('open', ''); } });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.removeAttribute('open'); } });
});
afterEach(() => {
  cleanup();
  if (originalShowModal) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', originalShowModal);
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal');
  if (originalClose) Object.defineProperty(HTMLDialogElement.prototype, 'close', originalClose);
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'close');
});
function mount() {
  return render(<MemoryRouter><Routes><Route element={<MaterialmAppShell />}><Route path="*" element={<div>Existing page body</div>} /></Route></Routes></MemoryRouter>);
}

describe('MaterialM application shell', () => {
  it('renders existing page content and a single primary Education entry', () => {
    mount();
    expect(screen.getByText('Existing page body')).toBeInTheDocument();
    const primary = screen.getByRole('complementary', { name: 'Primary navigation' });
    expect(within(primary).getAllByRole('link', { name: 'Education' })).toHaveLength(1);
    expect(within(primary).queryByRole('link', { name: 'Courses' })).not.toBeInTheDocument();
  });
  it('persists only the collapsed-sidebar preference', async () => {
    mount();
    await userEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    expect(localStorage.getItem('northstar.academy.sidebar-collapsed')).toBe('false');
    await userEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }));
    expect(localStorage.getItem('northstar.academy.sidebar-collapsed')).toBe('true');
  });
  it('makes all primary links available in the mobile drawer and closes on navigation', async () => {
    mount();
    // jsdom does not apply the mobile media query, so expose its navigation trigger.
    const trigger = screen.getByLabelText('Open navigation');
    trigger.style.display = 'inline-flex';
    await userEvent.click(trigger);
    const drawer = await screen.findByRole('dialog', { name: 'Main navigation' });
    for (const label of ['Education', 'Conversations', 'Leads', 'Integrations', 'Deploy']) {
      expect(within(drawer).getByRole('link', { name: label })).toBeInTheDocument();
    }
    await userEvent.click(within(drawer).getByRole('link', { name: 'Education' }));
    await waitFor(() => expect(drawer).not.toHaveAttribute('open'));
  });
  it('uses the existing workspace selection callback', async () => {
    mount(); await userEvent.click(screen.getByRole('button', { name: /Workspace Academy A/ }));
    await userEvent.click(screen.getByRole('button', { name: /Academy B/ }));
    expect(mocks.selectWorkspace).toHaveBeenCalledWith('b');
  });
  it('retains keyboard command search', async () => {
    mount(); await userEvent.keyboard('{Control>}k{/Control}');
    expect(await screen.findByRole('dialog', { name: 'Search and commands' })).toBeInTheDocument();
  });
  it('retains sign-out failure handling', async () => {
    mocks.logout.mockRejectedValueOnce(new Error('Session unavailable'));
    mount(); await userEvent.click(screen.getByRole('button', { name: 'Account menu' }));
    await userEvent.click(screen.getAllByRole('button', { name: 'Sign out' })[0]!);
    expect(mocks.pushToast).toHaveBeenCalledWith('Session unavailable', 'error');
  });
});
