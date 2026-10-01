import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatWidget } from '@/components/chat-widget';
import { demoAgents } from '@/lib/demo-data';
import type { WidgetSession } from '@/types';

describe('ChatWidget public sessions', () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo');
  });

  it('uses the supplied session factory for the first message and a reset', async () => {
    const first: WidgetSession = {
      conversationId: 'hosted-conversation-1', conversationPublicId: 'hosted-public-1', sessionToken: 'hosted-token-1', expiresAt: '2026-09-05T01:00:00Z',
    };
    const second: WidgetSession = {
      conversationId: 'hosted-conversation-2', conversationPublicId: 'hosted-public-2', sessionToken: 'hosted-token-2', expiresAt: '2026-09-05T02:00:00Z',
    };
    const requestNewSession = vi.fn()
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"type":"token","content":"Hosted reply"}\n\ndata: {"type":"done","conversationId":"hosted-conversation-1"}\n\n'));
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(<ChatWidget agent={demoAgents[0]!} embedded publicMode requestNewSession={requestNewSession} />);
    await user.type(screen.getByLabelText('Message'), 'Hello hosted widget');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    expect(await screen.findByText('Hosted reply')).toBeInTheDocument();
    expect(requestNewSession).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/widget/sessions/hosted-conversation-1/messages', expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer hosted-token-1' }),
    }));

    await user.click(screen.getByRole('button', { name: 'Start a new conversation' }));
    await waitFor(() => expect(requestNewSession).toHaveBeenCalledTimes(2));
  });

  it('renders Hindi interface copy when Hindi is selected', () => {
    const agent = structuredClone(demoAgents[0]!);
    agent.appearance.interfaceLanguage = 'Hindi';
    agent.appearance.placeholder = 'कुछ भी पूछें…';
    agent.appearance.translations = { newConversation: 'नई बातचीत', sendButton: 'भेजें', closeChat: 'चैट बंद करें', offlineMessage: 'हम जल्द वापस आएंगे' };

    render(<ChatWidget agent={agent} embedded />);

    expect(screen.getByRole('button', { name: 'नई बातचीत' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'मैं आपकी कैसे मदद कर सकता हूँ?' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /आप कौन-सी सेवाएँ देते हैं/ })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('कुछ भी पूछें…')).toBeInTheDocument();
    expect(screen.getByText('एआई से गलतियाँ हो सकती हैं। महत्वपूर्ण जानकारी जाँचें।')).toBeInTheDocument();
  });

  it('replaces an English question with the selected-language translation', async () => {
    const agent = structuredClone(demoAgents[0]!);
    agent.language = 'Hindi';
    agent.appearance.interfaceLanguage = 'Hindi';
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode([
          'data: {"type":"start","conversationId":"translated-conversation","messageId":"translated-answer"}',
          'data: {"type":"user_translation","content":"\u0928\u092e\u0938\u094d\u0924\u0947"}',
          'data: {"type":"token","content":"\u0928\u092e\u0938\u094d\u0924\u0947! \u092e\u0948\u0902 \u0906\u092a\u0915\u0940 \u092e\u0926\u0926 \u0915\u0947 \u0932\u093f\u090f \u092f\u0939\u093e\u0901 \u0939\u0942\u0901\u0964"}',
          'data: {"type":"done","conversationId":"translated-conversation"}',
          '',
        ].join('\n\n')));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    const user = userEvent.setup();

    render(<ChatWidget agent={agent} embedded />);
    await user.type(screen.getByRole('textbox'), 'hii');
    await user.click(screen.getByRole('button', { name: '\u092d\u0947\u091c\u0947\u0902' }));

    expect(await screen.findByText('\u0928\u092e\u0938\u094d\u0924\u0947')).toBeInTheDocument();
    expect(screen.queryByText('hii')).not.toBeInTheDocument();
    expect(await screen.findByText('\u0928\u092e\u0938\u094d\u0924\u0947! \u092e\u0948\u0902 \u0906\u092a\u0915\u0940 \u092e\u0926\u0926 \u0915\u0947 \u0932\u093f\u090f \u092f\u0939\u093e\u0901 \u0939\u0942\u0901\u0964')).toBeInTheDocument();
  });

  it('opens the more-options menu and runs copy and reset actions', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"type":"token","content":"A useful reply"}\n\ndata: {"type":"done","conversationId":"conversation-1"}\n\n'));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });

    render(<ChatWidget agent={demoAgents[0]!} embedded />);
    await user.type(screen.getByRole('textbox'), 'Hello');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByText('A useful reply')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'More options' }));
    await user.click(screen.getByRole('menuitem', { name: 'Copy conversation' }));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('Hello'));
    expect(screen.getByText('Conversation copied')).toBeInTheDocument();

    await user.click(screen.getByRole('menuitem', { name: 'Start a new conversation' }));
    expect(screen.queryByText('A useful reply')).not.toBeInTheDocument();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});
