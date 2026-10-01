import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { VisitorDetailsEditor } from './visitor-details-editor';
import type { Conversation } from '@/types';
const updateVisitor = vi.hoisted(() => vi.fn());
vi.mock('@/lib/conversation-api', () => ({ conversationApi: { updateVisitor } }));
const conversation: Conversation = { id: 'one', agentId: 'agent', visitorName: 'Anonymous visitor', visitorDetails: { utmSource: 'advert' }, channel: 'widget', state: 'open', sentiment: 'neutral', preview: '', unread: 0, startedAt: '2026-09-15T00:00:00Z', updatedAt: '2026-09-15T00:00:00Z', messages: [] };
describe('visitor editor', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  it('saves edited identity and attribution together', async () => {
    updateVisitor.mockResolvedValue({});
    const onSaved = vi.fn(); const user = userEvent.setup();
    render(<VisitorDetailsEditor conversation={conversation} onSaved={onSaved} />);
    await user.click(screen.getByRole('button', { name: 'Edit visitor details' }));
    await user.clear(screen.getByLabelText('Name')); await user.type(screen.getByLabelText('Name'), 'Sam');
    await user.type(screen.getByLabelText('Email'), 'sam@example.com');
    await user.clear(screen.getByLabelText('UTM source')); await user.type(screen.getByLabelText('UTM source'), 'newsletter');
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(updateVisitor).toHaveBeenCalledWith('one', expect.objectContaining({ visitorName: 'Sam', visitorEmail: 'sam@example.com', visitorDetails: { utmSource: 'newsletter' } }));
  });
  it('retains the form when saving fails', async () => {
    updateVisitor.mockRejectedValue(new Error('Save failed'));
    const user = userEvent.setup();
    render(<VisitorDetailsEditor conversation={conversation} onSaved={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Edit visitor details' }));
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Save failed');
    expect(screen.getByLabelText('Name')).toHaveValue('Anonymous visitor');
  });
});
