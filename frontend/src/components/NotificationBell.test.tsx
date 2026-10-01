import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NotificationBell } from '@/components/NotificationBell';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  list: vi.fn(),
  unreadCount: vi.fn(),
  markRead: vi.fn(),
  markAllRead: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
  useWorkspace: () => ({ activeWorkspace: { id: 'workspace-1' } }),
}));

vi.mock('@/lib/notifications-api', () => ({
  notificationsApi: {
    list: mocks.list,
    unreadCount: mocks.unreadCount,
    markRead: mocks.markRead,
    markAllRead: mocks.markAllRead,
  },
}));

const unreadItem = {
  id: 'notification-1',
  workspaceId: 'workspace-1',
  category: 'lead',
  severity: 'info',
  title: 'New lead captured',
  body: 'A conversation was resolved into a new lead.',
  actionUrl: '/leads',
  actionLabel: 'View leads',
  metadata: {},
  readAt: null,
  createdAt: new Date().toISOString(),
};

const readItem = {
  ...unreadItem,
  id: 'notification-2',
  title: 'API key created',
  actionUrl: '/workspace',
  actionLabel: 'Review API keys',
  readAt: new Date().toISOString(),
};

describe('NotificationBell', () => {
  beforeEach(() => {
    mocks.unreadCount.mockResolvedValue(1);
    mocks.list.mockResolvedValue([unreadItem, readItem]);
    mocks.markRead.mockResolvedValue({ ...unreadItem, readAt: new Date().toISOString() });
    mocks.markAllRead.mockResolvedValue(1);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('loads unread count, opens the real inbox, and marks an item read', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><NotificationBell /></MemoryRouter>);

    expect(await screen.findByRole('button', { name: 'Notifications, 1 unread' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Notifications, 1 unread' }));

    expect(await screen.findByText('New lead captured')).toBeInTheDocument();
    expect(screen.getByText('API key created')).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith(30);

    await user.click(screen.getByText('New lead captured'));
    await waitFor(() => expect(mocks.markRead).toHaveBeenCalledWith('notification-1'));
  });

  it('marks every visible notification read from the popover', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><NotificationBell /></MemoryRouter>);

    await user.click(await screen.findByRole('button', { name: 'Notifications, 1 unread' }));
    await screen.findByText('New lead captured');
    await user.click(screen.getByRole('button', { name: 'Mark all read' }));

    await waitFor(() => expect(mocks.markAllRead).toHaveBeenCalledTimes(1));
    expect(screen.getByText('You’re all caught up')).toBeInTheDocument();
  });

  it('refreshes incoming notifications while the inbox stays open', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><NotificationBell /></MemoryRouter>);
    await user.click(await screen.findByRole('button', { name: 'Notifications, 1 unread' }));
    await screen.findByText('New lead captured');
    mocks.list.mockResolvedValue([{ ...unreadItem, id: 'incoming', title: 'New conversation message' }, unreadItem]);
    mocks.unreadCount.mockResolvedValue(2);
    expect(await screen.findByText('New conversation message', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Notifications, 2 unread' })).toBeInTheDocument();
  });

  it('keeps the top bar usable when background count refresh fails', async () => {
    mocks.unreadCount.mockRejectedValueOnce(new Error('offline'));
    render(<MemoryRouter><NotificationBell /></MemoryRouter>);

    expect(await screen.findByRole('button', { name: 'Notifications' })).toBeInTheDocument();
    expect(mocks.pushToast).not.toHaveBeenCalled();
  });
});
