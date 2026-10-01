import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { demoAgents } from '@/lib/demo-data';
import { ConversationsPage } from '@/pages/ConversationsPage';
import type { Agent, Conversation, PageResult } from '@/types';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  agentList: vi.fn<() => Promise<Agent[]>>(),
  conversationList: vi.fn<() => Promise<PageResult<Conversation>>>(),
  resolve: vi.fn<(conversationId: string, leadStatus?: string) => Promise<Conversation>>(),
  resolveEducationSalesIntent: vi.fn(),
  educationSalesSettings: vi.fn(),
  updateState: vi.fn(),
  reply: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
  useWorkspace: () => ({
    activeWorkspace: { id: 'workspace-1', name: 'NorthStar Academy' },
  }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    agents: { list: mocks.agentList },
    conversations: {
      updateState: mocks.updateState,
      reply: mocks.reply,
    },
  },
}));

vi.mock('@/lib/conversation-api', () => ({
  conversationApi: {
    list: mocks.conversationList,
    resolve: mocks.resolve,
    resolveEducationSalesIntent: mocks.resolveEducationSalesIntent,
  },
}));

vi.mock('@/lib/education-sales-settings-api', () => ({
  educationSalesSettingsApi: {
    get: mocks.educationSalesSettings,
  },
}));

const baseConversation: Conversation = {
  canUpdateLeadStatus: true,
  id: 'conversation-1',
  workspaceId: 'workspace-1',
  agentId: 'agent-1',
  visitorName: 'Student One',
  visitorEmail: 'student@example.com',
  channel: 'widget',
  state: 'open',
  sentiment: 'neutral',
  preview: 'Can you help me?',
  unread: 0,
  startedAt: '2026-09-10T00:00:00.000Z',
  updatedAt: '2026-09-10T00:01:00.000Z',
  messages: [],
};

function agentForPurpose(purpose: Agent['purpose']): Agent {
  return {
    ...structuredClone(demoAgents[0]!),
    id: 'agent-1',
    purpose,
  };
}

async function renderAndResolve(purpose: Agent['purpose']): Promise<void> {
  const agent = agentForPurpose(purpose);
  mocks.agentList.mockResolvedValue([agent]);
  mocks.conversationList.mockResolvedValue({
    items: [baseConversation],
    total: 1,
    page: 1,
    pageSize: 50,
  });
  mocks.resolve.mockResolvedValue({ ...baseConversation, state: 'resolved' });

  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <ConversationsPage />
    </MemoryRouter>,
  );
  await user.click(await screen.findByRole('button', { name: 'Resolve' }));
  await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith(baseConversation.id, 'new'));
}

describe('ConversationsPage purpose-aware resolution feedback', () => {
  beforeEach(() => {
    mocks.educationSalesSettings.mockResolvedValue({ createUpsellLeads: false });
    mocks.resolveEducationSalesIntent.mockResolvedValue({
      conversationId: baseConversation.id,
      state: 'resolved',
      leadId: 'lead-1',
      leadCreated: true,
    });
    mocks.updateState.mockResolvedValue(baseConversation);
    mocks.reply.mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('preserves the Lead Generation finalized-lead confirmation', async () => {
    await renderAndResolve('lead_generation');
    expect(mocks.pushToast).toHaveBeenCalledWith('Conversation resolved and lead saved in Leads');
  });

  it('uses a neutral confirmation for Support', async () => {
    await renderAndResolve('support');
    expect(mocks.pushToast).toHaveBeenCalledWith('Conversation resolved and lead saved in Leads');
  });

  it.each(['open', 'resolved'] as const)('keeps %s Education chats outside the lead workflow even with legacy upsell enabled', async (state) => {
    mocks.educationSalesSettings.mockResolvedValue({ createUpsellLeads: true });
    mocks.agentList.mockResolvedValue([agentForPurpose('education')]);
    mocks.conversationList.mockResolvedValue({ items: [{ ...baseConversation, purpose: 'education', state }], total: 1, page: 1, pageSize: 50 });
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);
    expect(await screen.findByText('Education chat', { exact: true })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Resolve|Reopen|Save status|sales lead/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Lead status' })).not.toBeInTheDocument();
    expect(screen.getByRole('log')).toHaveTextContent('Student learning conversation');
    expect(mocks.resolve).not.toHaveBeenCalled();
    expect(mocks.resolveEducationSalesIntent).not.toHaveBeenCalled();
  });

  it('sends Qualified with Resolve in a single request and reports queued sync', async () => {
    mocks.agentList.mockResolvedValue([agentForPurpose('support')]);
    mocks.conversationList.mockResolvedValue({ items: [baseConversation], total: 1, page: 1, pageSize: 50 });
    mocks.resolve.mockResolvedValue({ ...baseConversation, state: 'resolved', leadId: 'lead-1', leadStatus: 'qualified' });
    const user = userEvent.setup();
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Lead status' }), 'qualified');
    expect(mocks.resolve).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Resolve' }));
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledExactlyOnceWith(baseConversation.id, 'qualified'));
    expect(mocks.pushToast).toHaveBeenCalledWith(expect.stringContaining('Automatic CRM sync requested'));
    expect(mocks.updateState).not.toHaveBeenCalled();
  });

  it('loads existing lead status and saves changes on an already resolved conversation', async () => {
    const conversation = { ...baseConversation, state: 'resolved' as const, leadId: 'lead-1', leadStatus: 'contacted' };
    mocks.agentList.mockResolvedValue([agentForPurpose('support')]);
    mocks.conversationList.mockResolvedValue({ items: [conversation], total: 1, page: 1, pageSize: 50 });
    mocks.resolve.mockResolvedValue({ ...conversation, leadStatus: 'qualified' });
    const user = userEvent.setup();
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);
    const status = await screen.findByRole('combobox', { name: 'Lead status' });
    expect(status).toHaveValue('contacted');
    await user.selectOptions(status, 'qualified');
    await user.click(screen.getByRole('button', { name: 'Save status' }));
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith(baseConversation.id, 'qualified'));
    expect(mocks.updateState).not.toHaveBeenCalled();
  });

  it('keeps the selected status for retry and reports save errors', async () => {
    mocks.agentList.mockResolvedValue([agentForPurpose('support')]);
    mocks.conversationList.mockResolvedValue({ items: [baseConversation], total: 1, page: 1, pageSize: 50 });
    mocks.resolve.mockRejectedValueOnce(new Error('Connection interrupted'));
    const user = userEvent.setup();
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Lead status' }), 'qualified');
    await user.click(screen.getByRole('button', { name: 'Resolve' }));
    await waitFor(() => expect(mocks.pushToast).toHaveBeenCalledWith('Connection interrupted', 'error'));
    expect(screen.getByRole('combobox', { name: 'Lead status' })).toHaveValue('qualified');
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeEnabled();
  });

  it('disables the status selector when the user cannot edit leads', async () => {
    mocks.agentList.mockResolvedValue([agentForPurpose('support')]);
    mocks.conversationList.mockResolvedValue({ items: [{ ...baseConversation, canUpdateLeadStatus: false }], total: 1, page: 1, pageSize: 50 });
    mocks.resolve.mockResolvedValue({ ...baseConversation, state: 'resolved' });
    const user = userEvent.setup();
    render(<MemoryRouter><ConversationsPage /></MemoryRouter>);
    expect(await screen.findByRole('combobox', { name: 'Lead status' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Resolve' }));
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith(baseConversation.id, undefined));
  });

});


describe('Conversations live messages and reading position', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
    mocks.agentList.mockResolvedValue([agentForPurpose('support')]);
    mocks.educationSalesSettings.mockResolvedValue({ createUpsellLeads: false });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); vi.useRealTimers(); });

  it('refreshes WhatsApp messages and delivery receipts while preserving an unsent draft', async () => {
    const message = { id: 'wa-1', role: 'assistant' as const, content: 'Your WhatsApp reply', createdAt: baseConversation.startedAt, deliveryStatus: 'sent' as const };
    const conversation: Conversation = { ...baseConversation, channel: 'whatsapp', messages: [message] };
    mocks.conversationList.mockResolvedValue({ items: [conversation], total: 1, page: 1, pageSize: 50 });
    await act(async () => { render(<MemoryRouter><ConversationsPage /></MemoryRouter>); });
    expect(screen.getByRole('img', { name: 'Sent to WhatsApp' })).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'WhatsApp message' }), { target: { value: 'Unsent draft' } });
    mocks.conversationList.mockResolvedValue({ items: [{ ...conversation, messages: [{ ...message, deliveryStatus: 'read' }, { ...message, id: 'wa-2', role: 'user', content: 'Customer replied', deliveryStatus: undefined }] }], total: 1, page: 1, pageSize: 50 });
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByRole('img', { name: 'Read' })).toBeInTheDocument();
    expect(screen.getByRole('log')).toHaveTextContent('Customer replied');
    expect(screen.getByRole('textbox', { name: 'WhatsApp message' })).toHaveValue('Unsent draft');
  });

  it('discovers the first website conversation and updates its messages without navigation', async () => {
    mocks.conversationList.mockResolvedValueOnce({ items: [], total: 0, page: 1, pageSize: 50 });
    await act(async () => { render(<MemoryRouter><ConversationsPage /></MemoryRouter>); });
    expect(screen.getByText('No conversations here')).toBeInTheDocument();
    const conversation = { ...baseConversation, messages: [{ id: 'message-1', role: 'user' as const, content: 'A new website message', createdAt: baseConversation.startedAt }] };
    mocks.conversationList.mockResolvedValue({ items: [conversation], total: 1, page: 1, pageSize: 50 });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByRole('log', { name: 'Conversation messages' })).toHaveTextContent('A new website message');
    fireEvent.change(screen.getByPlaceholderText(/Reply as a teammate/), { target: { value: 'My unsent reply' } });
    mocks.conversationList.mockResolvedValue({ items: [{ ...conversation, messages: [...conversation.messages, { id: 'message-2', role: 'assistant', content: 'An automatic reply', createdAt: baseConversation.startedAt }] }], total: 1, page: 1, pageSize: 50 });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByRole('log')).toHaveTextContent('An automatic reply');
    expect(screen.getByPlaceholderText(/Reply as a teammate/)).toHaveValue('My unsent reply');
  });

  it('follows new messages at the bottom but preserves older reading position', async () => {
    let messages = [{ id: 'message-1', role: 'user' as const, content: 'First message', createdAt: baseConversation.startedAt }];
    const current = () => ({ items: [{ ...baseConversation, messages }], total: 1, page: 1, pageSize: 50 });
    mocks.conversationList.mockImplementation(async () => current());
    await act(async () => { render(<MemoryRouter><ConversationsPage /></MemoryRouter>); });
    const thread = screen.getByRole('log');
    let scrollHeight = 1000;
    Object.defineProperties(thread, { scrollHeight: { get: () => scrollHeight }, clientHeight: { value: 200 } });
    thread.scrollTop = 800;
    fireEvent.scroll(thread);
    messages = [...messages, { ...messages[0]!, id: 'message-2', content: 'Second message' }];
    scrollHeight = 1200;
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(thread.scrollTop).toBe(1200);
    thread.scrollTop = 100;
    fireEvent.scroll(thread);
    messages = [...messages, { ...messages[0]!, id: 'message-3', content: 'Third message' }];
    scrollHeight = 1400;
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(thread.scrollTop).toBe(100);
    fireEvent.click(screen.getByRole('button', { name: 'New messages' }));
    expect(thread.scrollTop).toBe(1400);
    expect(screen.queryByRole('button', { name: 'New messages' })).not.toBeInTheDocument();
  });

  it('keeps the conversation list open after pressing Back while updates continue', async () => {
    mocks.conversationList.mockResolvedValue({ items: [baseConversation], total: 1, page: 1, pageSize: 50 });
    await act(async () => { render(<MemoryRouter><ConversationsPage /></MemoryRouter>); });
    fireEvent.click(screen.getByRole('button', { name: 'Back to conversation list' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.queryByRole('log')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Conversation list' })).toBeInTheDocument();
  });
});
