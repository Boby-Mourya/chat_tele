import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TelegramSetupModal, trustedTelegramUrl } from './telegram-setup-modal';
import type { ChannelConnectionView } from '@/lib/lead-crm-api';

const mocks = vi.hoisted(() => ({ start: vi.fn(), status: vi.fn(), disconnect: vi.fn(), changed: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { agents: { list: vi.fn().mockResolvedValue([{ id: 'agent-1', name: 'Tutor', appearance: { deploymentChannel: 'telegram' } }]) } } }));
vi.mock('@/lib/lead-crm-api', () => ({ leadCrmApi: { startTelegramConnection: mocks.start, getTelegramProvisioningStatus: mocks.status, disconnectTelegramConnection: mocks.disconnect } }));
const bot = { managed: true, botId: '1', botName: 'Real Tutor', botUsername: 'actual_tutor_bot', studentUrl: 'https://t.me/actual_tutor_bot' };
function show() { return render(<MemoryRouter><TelegramSetupModal connections={[]} canManage onChanged={mocks.changed} onClose={() => {}} /></MemoryRouter>); }

describe('managed Telegram setup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.start.mockResolvedValue({ sessionId: 'session-1', status: 'pending', telegramUrl: 'https://t.me/manager_bot?start=opaque' });
    mocks.status.mockResolvedValue({ sessionId: 'session-1', status: 'connected', connectionId: 'connection-1', bot });
    mocks.disconnect.mockResolvedValue(undefined);
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('connects, polls, shows authoritative student URL, and disconnects without credential fields', async () => {
    const popup = { opener: {}, location: { href: '' }, close: vi.fn() };
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
    show();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled());
    expect(screen.queryByLabelText(/bot token|webhook secret|webhook url/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/setWebhook|Finish webhook setup/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }));
    expect(mocks.start).toHaveBeenCalledWith('agent-1');
    expect(popup.location.href).toBe('https://t.me/manager_bot?start=opaque');
    expect(screen.getByRole('button', { name: 'Connecting…' })).toBeDisabled();
    await waitFor(() => expect(screen.getByText('Real Tutor')).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByRole('link', { name: bot.studentUrl })).toHaveAttribute('href', bot.studentUrl);
    await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }));
    expect(mocks.disconnect).toHaveBeenCalledWith('connection-1');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled());
  });

  it('rejects untrusted redirects', async () => {
    mocks.start.mockResolvedValue({ sessionId: 's', status: 'pending', telegramUrl: 'https://evil.example.com' });
    vi.spyOn(window, 'open').mockReturnValue({ close: vi.fn(), location: {}, opener: null } as unknown as Window);
    show();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid Telegram connection URL');
    expect(mocks.status).not.toHaveBeenCalled();
  });

  it('keeps a visible Telegram link when the popup is blocked', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    show();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }));
    expect(screen.getByRole('link', { name: 'Open Telegram again' })).toHaveAttribute('href', 'https://t.me/manager_bot?start=opaque');
    expect(screen.getByText('Next: press Start in Telegram')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('stops polling when unmounted', async () => {
    vi.spyOn(window, 'open').mockReturnValue({ close: vi.fn(), location: {}, opener: null } as unknown as Window);
    const view = show();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }));
    view.unmount();
    await new Promise(resolve => setTimeout(resolve, 1100));
    expect(mocks.status).not.toHaveBeenCalled();
  });

  it('validates Telegram links', () => {
    expect(trustedTelegramUrl('https://t.me/tutor_bot')).toBe(true);
    for (const url of ['javascript:alert(1)', 'https://t.me.evil.com/tutor_bot', 'https://user:pass@t.me/tutor_bot', 'https://t.me:8443/tutor_bot']) expect(trustedTelegramUrl(url)).toBe(false);
  });

  it('adds a separate account and disconnects only the selected bot', async () => {
    const connections = [1, 2].map(number => ({ id: `bot-${number}`, public_id: `public-${number}`, workspace_id: 'workspace-1', created_at: '2026-01-01', updated_at: '2026-01-01', provider: 'telegram', agent_id: 'agent-1', name: `Bot ${number}`, status: 'healthy', configuration: { telegram: { ...bot, botUsername: `tutor_${number}_bot` } } })) as ChannelConnectionView[];
    vi.spyOn(window, 'open').mockReturnValue(null);
    render(<MemoryRouter><TelegramSetupModal connections={connections} canManage onChanged={mocks.changed} onClose={() => {}} /></MemoryRouter>);
    await userEvent.selectOptions(screen.getByLabelText('Bot account'), 'bot-2');
    await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }));
    expect(mocks.disconnect).toHaveBeenCalledWith('bot-2');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add account' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Add account' }));
    expect(screen.getByText(/Switch accounts in Telegram before pressing Start/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }));
    expect(mocks.start).toHaveBeenCalledWith('agent-1', { accountId: expect.any(String) });
    expect(mocks.disconnect).toHaveBeenCalledTimes(1);
  });
});
