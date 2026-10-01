import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WhatsAppMessages } from './whatsapp-messages';
import { WhatsAppReplyComposer } from './whatsapp-reply-composer';
import type { ChatMessage } from '@/types';

afterEach(cleanup);
const incoming: ChatMessage = { id: 'in', role: 'user', content: 'Hello', createdAt: '2026-09-14T10:00:00Z' };
const outgoing: ChatMessage = { id: 'out', role: 'assistant', content: 'Welcome', createdAt: '2026-09-15T10:01:00Z', deliveryStatus: 'sent' };
describe('WhatsApp conversation', () => {
  it('shows customer messages on the left and business replies on the right with real receipts', () => {
    const { rerender } = render(<WhatsAppMessages messages={[incoming, outgoing]} visitorName="Anan" agentName="CMA" />);
    expect(screen.getByRole('article', { name: 'Anan: Hello' })).toHaveClass('wa-message--incoming');
    expect(screen.getByRole('article', { name: 'CMA: Welcome' })).toHaveClass('wa-message--outgoing');
    expect(screen.getByRole('img', { name: 'Sent to WhatsApp' })).toBeInTheDocument();
    expect(document.querySelectorAll('.wa-day')).toHaveLength(2);
    rerender(<WhatsAppMessages messages={[incoming, { ...outgoing, deliveryStatus: 'read' }]} visitorName="Anan" agentName="CMA" />);
    expect(screen.getByRole('img', { name: 'Read' })).toHaveClass('wa-delivery--read');
    expect(screen.queryByRole('img', { name: 'Sent to WhatsApp' })).not.toBeInTheDocument();
  });
  it('does not invent ticks for messages without provider evidence or incoming messages', () => {
    render(<WhatsAppMessages messages={[{ ...incoming, deliveryStatus: 'read' }, { ...outgoing, deliveryStatus: null }, { ...outgoing, id: 'pending', content: '' }]} visitorName="Anan" agentName="CMA" />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(2);
  });
  it('shows failed and queued replies without claiming delivery', () => {
    render(<WhatsAppMessages messages={[{ ...outgoing, deliveryStatus: 'failed' }, { ...outgoing, id: 'pending', deliveryStatus: 'pending' }]} visitorName="Anan" agentName="CMA" />);
    expect(screen.getByRole('img', { name: 'Delivery failed' })).toHaveTextContent('Not sent');
    expect(screen.getByRole('img', { name: 'Waiting to send' })).toBeInTheDocument();
  });
  it('lets an operator preview and send a native quick-reply button message', async () => {
    const send = vi.fn().mockResolvedValue(true);
    render(<WhatsAppReplyComposer sending={false} onSend={send} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Buttons' }));
    fireEvent.change(screen.getByPlaceholderText('Example: Switch to CPA'), { target: { value: 'Switch to CPA' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'WhatsApp message' }), { target: { value: 'Choose your course' } });
    expect(screen.getByLabelText('Message preview')).toHaveTextContent('Switch to CPA');
    fireEvent.click(screen.getByRole('button', { name: 'Send buttons message' }));
    expect(send).toHaveBeenCalledWith({ content: 'Choose your course', messageFormat: { type: 'buttons', buttons: [{ id: 'reply_1', title: 'Switch to CPA' }] } });
  });
  it('renders stored buttons and tables as structured chat content', () => {
    render(<WhatsAppMessages messages={[
      { ...outgoing, id: 'buttons', messageFormat: { type: 'buttons', buttons: [{ id: 'cpa', title: 'CPA' }] } },
      { ...outgoing, id: 'table', content: 'Courses\n\nCourse | Status', messageFormat: { type: 'table', body: 'Courses', table: { columns: ['Course', 'Status'], rows: [['CMA', 'Active']] } } },
    ]} visitorName="Anan" agentName="CMA" />);
    expect(screen.getByText('CPA')).toBeInTheDocument();
    expect(screen.getByRole('table')).toHaveTextContent('CMA');
    expect(screen.getByText('Courses')).toBeInTheDocument();
  });
  it('sends on Enter, preserves Shift+Enter/IME composition, and inserts emoji into the draft', () => {
    const send = vi.fn();
    render(<WhatsAppReplyComposer sending={false} onSend={async () => { send(); return true; }} />);
    const input = screen.getByRole('textbox', { name: 'WhatsApp message' });
    fireEvent.change(input, { target: { value: 'Hello' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
    expect(send).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(send).toHaveBeenCalledTimes(1);
    (input as HTMLTextAreaElement).setSelectionRange(5, 5);
    fireEvent.click(screen.getByRole('button', { name: 'Insert emoji' }));
    fireEvent.click(screen.getByRole('button', { name: 'Insert 👍' }));
    expect(input).toHaveValue('Hello👍');
  });
});
