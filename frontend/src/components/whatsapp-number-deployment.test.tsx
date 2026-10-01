import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WhatsAppNumberDeployment } from './whatsapp-number-deployment';
import type { WhatsAppConnection } from '@/types';

const mocks = vi.hoisted(() => ({ status: vi.fn(), assignNumber: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { integrations: { whatsapp: mocks } } }));
vi.mock('@/components/providers', () => ({ useWorkspace: () => ({ activeWorkspace: { id: 'workspace-1' } }) }));

const number: WhatsAppConnection = { id: 'number-1', phoneNumberId: 'meta-id', wabaId: 'waba', displayPhoneNumber: '+15550199999', verifiedName: 'Example business', status: 'connected', agentId: null, connectedAt: '2026-01-01' };
afterEach(() => { cleanup(); vi.clearAllMocks(); });
beforeEach(() => { mocks.status.mockResolvedValue({ connections: [number] }); });

describe('WhatsApp number deployment', () => {
  it('loads, assigns to a draft bot, and releases without stale state', async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    const loaded = vi.fn();
    render(<WhatsAppNumberDeployment agentId="draft-bot" onNumberChanged={changed} onNumbersLoaded={loaded} />);
    const select = screen.getByLabelText('Connected WhatsApp number');
    await waitFor(() => expect(select).toBeEnabled());
    await user.selectOptions(select, 'number-1');
    mocks.assignNumber.mockResolvedValue({ ...number, agentId: 'draft-bot' });
    await user.click(screen.getByRole('button', { name: 'Apply number assignment' }));
    await waitFor(() => expect(changed).toHaveBeenCalledWith('+15550199999', null));
    expect(mocks.assignNumber).toHaveBeenCalledWith('number-1', 'draft-bot');
    expect(screen.getByRole('button', { name: 'Apply number assignment' })).toBeDisabled();
    expect(loaded).toHaveBeenLastCalledWith([expect.objectContaining({ agentId: 'draft-bot' })]);
    await user.selectOptions(select, '');
    mocks.assignNumber.mockResolvedValue(number);
    await user.click(screen.getByRole('button', { name: 'Apply number assignment' }));
    await waitFor(() => expect(mocks.assignNumber).toHaveBeenLastCalledWith('number-1', null));
    expect(loaded).toHaveBeenLastCalledWith([number]);
    expect(screen.getByRole('button', { name: 'Apply number assignment' })).toBeDisabled();
  });

  it('retries a failed load and blocks expired or unverified numbers', async () => {
    const user = userEvent.setup();
    mocks.status.mockRejectedValueOnce(new Error('Could not load account numbers'));
    render(<WhatsAppNumberDeployment agentId="bot" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load account numbers');
    mocks.status.mockResolvedValue({ connections: [{ ...number, tokenExpiresAt: '2020-01-01' }, { ...number, id: 'number-2', status: 'needs_webhook' }] });
    await user.click(screen.getByRole('button', { name: 'Retry loading numbers' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    const select = screen.getByLabelText('Connected WhatsApp number') as HTMLSelectElement;
    expect(select.options[1]).toBeDisabled();
    expect(select.options[2]).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Apply number assignment' })).toBeDisabled();
    expect(mocks.assignNumber).not.toHaveBeenCalled();
  });

  it('reports the previous owner when a number is moved and preserves selection on failure', async () => {
    const user = userEvent.setup();
    mocks.status.mockResolvedValue({ connections: [{ ...number, agentId: 'old-bot' }] });
    const changed = vi.fn();
    render(<WhatsAppNumberDeployment agentId="new-bot" onNumberChanged={changed} />);
    await waitFor(() => expect(screen.getByLabelText('Connected WhatsApp number')).toBeEnabled());
    await user.selectOptions(screen.getByLabelText('Connected WhatsApp number'), 'number-1');
    mocks.assignNumber.mockRejectedValueOnce(Object.assign(new Error('Request failed (409)'), { detail: { detail: 'Assignment failed' } }));
    await user.click(screen.getByRole('button', { name: 'Apply number assignment' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Assignment failed');
    expect(screen.getByLabelText('Connected WhatsApp number')).toHaveValue('number-1');
    mocks.assignNumber.mockResolvedValue({ ...number, agentId: 'new-bot' });
    await user.click(screen.getByRole('button', { name: 'Apply number assignment' }));
    await waitFor(() => expect(changed).toHaveBeenCalledWith('+15550199999', 'old-bot'));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
