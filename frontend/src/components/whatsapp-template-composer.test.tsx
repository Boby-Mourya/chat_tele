import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { WhatsAppTemplateComposer } from './whatsapp-template-composer';

const mocks = vi.hoisted(() => ({ templates: vi.fn(), sendTemplate: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { integrations: { whatsapp: mocks } } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it('requires an approved template, filled parameters and consent before queueing', async () => {
  mocks.templates.mockResolvedValue([{ name: 'follow_up', language: 'en', preview: 'Hello {{1}}', fields: [{ component: 'body', name: '1' }], unsupportedReason: null }]);
  mocks.sendTemplate.mockResolvedValue({ id: 'message' });
  const user = userEvent.setup();
  render(<WhatsAppTemplateComposer agentId="agent" conversationId="conversation" />);
  await user.click(screen.getByRole('button', { name: 'Send WhatsApp template' }));
  await user.click(screen.getByRole('tab', { name: /Approved by Meta/ }));
  await screen.findByRole('option', { name: 'follow_up (en)' });
  await user.selectOptions(screen.getByLabelText('Approved template'), '0');
  expect(screen.getByRole('button', { name: 'Queue template' })).toBeDisabled();
  await user.type(screen.getByLabelText('body 1'), 'Customer');
  await user.click(screen.getByRole('checkbox'));
  await user.click(screen.getByRole('button', { name: 'Queue template' }));
  await screen.findByRole('status');
  expect(mocks.sendTemplate).toHaveBeenCalledWith('conversation', { name: 'follow_up', language: 'en', parameters: ['Customer'], consentConfirmed: true });
  expect(screen.queryByRole('button', { name: 'Queue template' })).not.toBeInTheDocument();
});

it('shows provider errors without claiming success', async () => {
  mocks.templates.mockRejectedValue(new Error('Reconnect WhatsApp'));
  const user = userEvent.setup();
  render(<WhatsAppTemplateComposer agentId="agent" conversationId="conversation" />);
  await user.click(screen.getByRole('button', { name: 'Send WhatsApp template' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Reconnect WhatsApp');
  await user.click(screen.getByRole('tab', { name: /Approved by Meta/ }));
  expect(screen.getByRole('button', { name: 'Queue template' })).toBeDisabled();
});

it('opens the purpose-specific editable template library', async () => {
  mocks.templates.mockResolvedValue([]);
  const user = userEvent.setup();
  render(<WhatsAppTemplateComposer agentId="agent" conversationId="conversation" purpose="education" />);
  await user.click(screen.getByRole('button', { name: 'Send WhatsApp template' }));
  expect(screen.getByRole('tab', { name: /Education/ })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getAllByRole('button', { name: /Enrollment|Class reminder|Study plan/ }).length).toBeGreaterThan(0);
  const header = screen.getByLabelText('Header');
  await user.clear(header);
  await user.type(header, 'A brighter learning journey');
  expect(screen.getByText('A brighter learning journey')).toBeInTheDocument();
});
