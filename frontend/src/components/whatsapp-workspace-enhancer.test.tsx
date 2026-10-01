import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { demoAgents } from '@/lib/demo-data';
import { InteractiveChannelWorkspace, InteractiveWhatsAppWorkspace } from '@/components/whatsapp-workspace-enhancer';
import type { ChatStreamEvent, Conversation, WhatsAppStatus } from '@/types';

const apiMocks = vi.hoisted(() => ({
  getAgent: vi.fn(),
  status: vi.fn(),
  integrationsList: vi.fn(),
  conversationsList: vi.fn(),
  reply: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: {
    agents: { get: apiMocks.getAgent },
    integrations: { list: apiMocks.integrationsList, whatsapp: { status: apiMocks.status } },
    conversations: { list: apiMocks.conversationsList, reply: apiMocks.reply },
    streamChat: apiMocks.streamChat,
  },
}));

function stream(events: ChatStreamEvent[]) {
  return (async function* () { for (const event of events) yield event; })();
}

describe('Interactive channel workspace', () => {
  const agent = structuredClone(demoAgents[0]!);
  const liveConversation: Conversation = {
    id: 'conv-whatsapp',
    agentId: agent.id,
    visitorName: 'Student',
    channel: 'whatsapp',
    state: 'open',
    sentiment: 'neutral',
    preview: 'Real WhatsApp question',
    unread: 1,
    startedAt: '2026-09-08T06:00:00.000Z',
    updatedAt: '2026-09-08T06:01:00.000Z',
    messages: [{ id: 'msg-in', role: 'user', content: 'Real WhatsApp question', createdAt: '2026-09-08T06:01:00.000Z' }],
  };

  beforeEach(() => {
    agent.appearance.deploymentChannel = 'whatsapp';
    agent.language = 'English';
    agent.appearance.interfaceLanguage = 'English';
    apiMocks.getAgent.mockResolvedValue(agent);
    apiMocks.status.mockResolvedValue({
      enabled: true,
      connected: true,
      connection: null,
      connections: [{
        wabaId: 'waba-1', phoneNumberId: 'phone-1', displayPhoneNumber: '+91 99999 11111', verifiedName: 'Northstar',
        agentId: agent.id, status: 'connected', connectedAt: '2026-09-08T06:00:00.000Z',
      }],
    } satisfies WhatsAppStatus);
    apiMocks.integrationsList.mockResolvedValue([]);
    apiMocks.conversationsList.mockResolvedValue({ items: [liveConversation], total: 1, page: 1, pageSize: 50 });
    apiMocks.reply.mockResolvedValue({ id: 'agent-reply', role: 'agent', content: 'Human reply', createdAt: '2026-09-08T06:02:00.000Z' });
    apiMocks.streamChat.mockImplementation(() => stream([
      { type: 'start', conversationId: 'preview-conversation', messageId: 'preview-message' },
      { type: 'token', content: 'Hello ' },
      { type: 'token', content: 'from the bot' },
      { type: 'done', conversationId: 'preview-conversation' },
    ]));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('lets the workspace owner chat with the selected agent in WhatsApp test mode', async () => {
    const user = userEvent.setup();
    render(<InteractiveWhatsAppWorkspace agentId={agent.id} />);

    const input = await screen.findByLabelText('Test channel message');
    await user.type(input, 'Can you help me?');
    await user.click(screen.getByRole('button', { name: 'Send test message' }));

    expect(await screen.findByText('Hello from the bot')).toBeInTheDocument();
    expect(apiMocks.streamChat).toHaveBeenCalledWith(expect.objectContaining({
      agentId: agent.id,
      message: 'Can you help me?',
      language: 'English',
      visitorId: 'workspace-whatsapp-test-preview',
    }), expect.any(AbortSignal));
  });

  it('shows the newest real WhatsApp thread and sends a live reply', async () => {
    const user = userEvent.setup();
    render(<InteractiveWhatsAppWorkspace agentId={agent.id} />);

    await user.click(await screen.findByRole('button', { name: 'Live' }));
    expect(await screen.findByText('Real WhatsApp question')).toBeInTheDocument();
    expect(screen.getByText(/\+91 99999 11111/)).toBeInTheDocument();

    await user.type(screen.getByLabelText('Live channel reply'), 'Human reply');
    await user.click(screen.getByRole('button', { name: 'Send live reply' }));

    await waitFor(() => expect(apiMocks.reply).toHaveBeenCalledWith('conv-whatsapp', 'Human reply'));
  });

  it('uses the selected language in an Instagram-style interactive preview', async () => {
    const user = userEvent.setup();
    apiMocks.streamChat.mockImplementation(() => stream([
      { type: 'start', conversationId: 'instagram-preview', messageId: 'preview-message' },
      { type: 'user_translation', content: 'नमस्ते' },
      { type: 'token', content: 'नमस्ते! मैं आपकी मदद कर सकता हूँ।' },
      { type: 'done', conversationId: 'instagram-preview' },
    ]));

    render(<InteractiveChannelWorkspace agentId={agent.id} channel="instagram" language="Hindi" />);

    expect(await screen.findByText('कोई सवाल पूछें, मैं सबसे उपयोगी जवाब ढूँढूँगा।')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'परीक्षण' })).toBeInTheDocument();
    const input = screen.getByLabelText('Test channel message');
    expect(input).toHaveAttribute('placeholder', 'कुछ भी पूछें…');

    await user.type(input, 'hello');
    await user.click(screen.getByRole('button', { name: 'Send test message' }));

    expect(await screen.findByText('नमस्ते')).toBeInTheDocument();
    expect(await screen.findByText('नमस्ते! मैं आपकी मदद कर सकता हूँ।')).toBeInTheDocument();
    expect(apiMocks.streamChat).toHaveBeenCalledWith(expect.objectContaining({
      agentId: agent.id,
      language: 'Hindi',
      visitorId: 'workspace-instagram-test-preview',
    }), expect.any(AbortSignal));
  });

  it('keeps Live clickable for Instagram even without a provider integration', async () => {
    const user = userEvent.setup();
    apiMocks.integrationsList.mockResolvedValue([]);
    apiMocks.conversationsList.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 50 });
    apiMocks.streamChat.mockImplementation(() => stream([
      { type: 'start', conversationId: 'instagram-live-preview', messageId: 'preview-message' },
      { type: 'token', content: 'Live preview reply' },
      { type: 'done', conversationId: 'instagram-live-preview' },
    ]));

    render(<InteractiveChannelWorkspace agentId={agent.id} channel="instagram" language="English" />);

    await user.click(await screen.findByRole('button', { name: 'Live' }));
    expect(await screen.findByText(/Live preview · English/)).toBeInTheDocument();

    const input = screen.getByLabelText('Live channel reply');
    expect(input).not.toBeDisabled();
    await user.type(input, 'Show me the live preview');
    await user.click(screen.getByRole('button', { name: 'Send live reply' }));

    expect(await screen.findByText('Live preview reply')).toBeInTheDocument();
    expect(apiMocks.streamChat).toHaveBeenCalledWith(expect.objectContaining({
      agentId: agent.id,
      message: 'Show me the live preview',
      visitorId: 'workspace-instagram-live-preview',
    }), expect.any(AbortSignal));
  });
});
