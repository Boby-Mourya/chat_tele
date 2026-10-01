import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '@/components/providers';
import { demoAgents, demoIntegrations } from '@/lib/demo-data';
import { DeployPage } from '@/pages/DeployPage';
import type { Agent, AgentPatch } from '@/types';

const apiMocks = vi.hoisted(() => ({
  list: vi.fn<() => Promise<Agent[]>>(),
  update: vi.fn<(agentId: string, patch: AgentPatch) => Promise<Agent>>(),
  listIntegrations: vi.fn(),
  setConnected: vi.fn(),
  streamChat: vi.fn(),
  feedback: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: {
    agents: { list: apiMocks.list, update: apiMocks.update },
    integrations: { list: apiMocks.listIntegrations, setConnected: apiMocks.setConnected },
    streamChat: apiMocks.streamChat,
    feedback: apiMocks.feedback,
  },
}));

vi.mock('@/components/chat-widget', () => ({
  ChatWidget: ({ agent }: { agent: Agent }) => <div data-testid="widget-preview">{agent.appearance.welcomeTitle}</div>,
}));

vi.mock('@/components/whatsapp-number-deployment', () => ({
  WhatsAppNumberDeployment: ({ onNumberChanged }: { onNumberChanged: (number: string | null, previousAgentId?: string | null) => void }) => <div>WhatsApp number for this bot<button onClick={() => onNumberChanged('+15550199999', 'previous-bot')}>Simulate number move</button></div>,
}));

function renderPage() {
  return render(<MemoryRouter><ToastProvider><DeployPage /></ToastProvider></MemoryRouter>);
}

describe('DeployPage', () => {
  let original: Agent;

  beforeEach(() => {
    original = structuredClone(demoAgents[0]!);
    apiMocks.list.mockResolvedValue([original]);
    apiMocks.listIntegrations.mockResolvedValue(structuredClone(demoIntegrations));
    apiMocks.setConnected.mockImplementation(async (integrationId: string, connected: boolean) => ({ ...demoIntegrations.find((item) => item.id === integrationId)!, connected }));
    apiMocks.streamChat.mockImplementation(async function* () {
      yield { type: 'start' as const, conversationId: 'preview-conversation', messageId: 'preview-answer' };
      yield { type: 'user_translation' as const, content: 'नमस्ते' };
      yield { type: 'token' as const, content: 'मैं आपकी मदद कर सकता हूँ।' };
      yield { type: 'citation' as const, title: 'Northstar knowledge base' };
      yield { type: 'done' as const, conversationId: 'preview-conversation' };
    });
    apiMocks.feedback.mockResolvedValue(undefined);
    apiMocks.update.mockImplementation(async (_agentId, patch) => ({
      ...original,
      ...patch,
      appearance: patch.appearance ?? original.appearance,
    }));
  });

  afterEach(cleanup);

  it('shows a retry after a loading failure and an empty state when there are no bots', async () => {
    const user = userEvent.setup();
    apiMocks.list.mockRejectedValueOnce(new Error('Network unavailable'));
    renderPage();
    expect(await screen.findByText('Could not load deployment settings')).toBeInTheDocument();
    apiMocks.list.mockResolvedValue([]);
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Create a bot to get started')).toBeInTheDocument();
  });

  it('locks editing during save, keeps failed drafts, and keeps Apply visible on sharing pages', async () => {
    original.appearance.deploymentChannel = 'whatsapp';
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Welcome message' }));
    const welcome = screen.getByLabelText('Welcome message text');
    fireEvent.change(welcome, { target: { value: 'Preserve this welcome' } });
    let rejectSave!: (reason: Error) => void;
    apiMocks.update.mockImplementationOnce(() => new Promise((_, reject) => { rejectSave = reject; }));
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(welcome).toBeDisabled();
    expect(screen.getByLabelText('Select deploy agent')).toBeDisabled();
    rejectSave(Object.assign(new Error('Request failed (409)'), { detail: { error: { message: 'Save temporarily unavailable' } } }));
    await screen.findByText('Save temporarily unavailable');
    expect(welcome).toHaveValue('Preserve this welcome');
    expect(welcome).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Get link' }));
    expect(screen.getByRole('button', { name: 'Apply' })).toBeEnabled();
    expect(screen.getByText(/You have unapplied changes/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reset changes' }));
    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument();
  });

  it('clears the old bot’s chat link after its number is reassigned', async () => {
    original.appearance.deploymentChannel = 'whatsapp';
    const old = { ...structuredClone(original), id: 'previous-bot', name: 'Previous bot', whatsappNumber: '+15550199999' };
    apiMocks.list.mockResolvedValue([original, old]);
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Simulate number move' }));
    await user.selectOptions(screen.getByLabelText('Select deploy agent'), 'previous-bot');
    await user.click(screen.getByRole('button', { name: 'Get link' }));
    expect(screen.queryByRole('link', { name: 'Open WhatsApp' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Choose WhatsApp number' })).toBeInTheDocument();
  });

  it('publishes appearance changes through the agent API and resets to the saved result', async () => {
    const user = userEvent.setup();
    renderPage();

    const heading = await screen.findByLabelText('Hero heading');
    const apply = screen.getByRole('button', { name: 'Apply' });
    const reset = screen.getByRole('button', { name: 'Reset changes' });
    expect(apply).toBeEnabled();
    expect(reset).toBeEnabled();

    await user.clear(heading);
    await user.type(heading, 'A sharper welcome');
    await user.click(screen.getByRole('button', { name: 'Bottom left' }));
    expect(screen.getByTestId('widget-preview')).toHaveTextContent('A sharper welcome');
    expect(apply).toBeEnabled();

    await user.click(apply);
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledTimes(1));
    expect(apiMocks.update).toHaveBeenCalledWith(original.id, {
      appearance: {
        ...original.appearance,
        position: 'bottom-left',
        welcomeTitle: 'A sharper welcome',
      },
    });
    await waitFor(() => expect(apply).toBeEnabled());
    expect(reset).toBeEnabled();

    await user.click(apply);
    await user.click(reset);
    expect(apiMocks.update).toHaveBeenCalledTimes(1);
    expect(heading).toHaveValue('A sharper welcome');

    await user.clear(heading);
    await user.type(heading, 'Discard this');
    await user.click(reset);
    expect(heading).toHaveValue('A sharper welcome');
    expect(apiMocks.update).toHaveBeenCalledTimes(1);
  });

  it('lists every created agent and switches the deployment preview', async () => {
    const user = userEvent.setup();
    const second = structuredClone(demoAgents[1]!);
    apiMocks.list.mockResolvedValue([original, second]);
    renderPage();

    const selector = await screen.findByRole('combobox', { name: 'Select deploy agent' });
    expect(selector).toHaveTextContent(original.name);
    expect(selector).toHaveTextContent(second.name);

    await user.selectOptions(selector, second.id);
    expect(screen.getByTestId('widget-preview')).toHaveTextContent(second.appearance.welcomeTitle);
  });

  it('offers deployment channels and can enable Facebook from the dropdown', async () => {
    const user = userEvent.setup();
    renderPage();

    const selector = await screen.findByRole('combobox', { name: 'Select deployment channel' });
    expect(selector).toHaveTextContent('Website widget');
    expect(selector).toHaveTextContent('WhatsApp');
    expect(selector).toHaveTextContent('Facebook Messenger');
    expect(selector).toHaveTextContent('Instagram');

    await user.selectOptions(selector, 'facebook');
    expect(screen.getByRole('heading', { name: 'Facebook Messenger', level: 2 })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Enable channel' }));
    await waitFor(() => expect(apiMocks.setConnected).toHaveBeenCalledWith('facebook', true));
  });

  it('opens every Deploy sidebar feature', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole('heading', { name: 'Look and feel', level: 2 });

    for (const label of ['Agent source', 'Toggle', 'Conversation starters', 'Color studio', 'Font studio', 'Greeting editor', 'Localization', 'GDPR & consent', 'Other', 'Get link', 'QR code', 'Instant embed', 'IFrame embed']) {
      await user.click(screen.getByRole('button', { name: label }));
      expect(screen.getByRole('heading', { name: label, level: 2 })).toBeInTheDocument();
    }
  });

  it('updates Hindi localization fields and the live preview immediately', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole('heading', { name: 'Look and feel', level: 2 });

    await user.click(screen.getByRole('button', { name: 'Localization' }));
    await user.selectOptions(screen.getByLabelText('Interface language'), 'Hindi');

    expect(screen.getByDisplayValue('नई बातचीत')).toBeInTheDocument();
    expect(screen.getByDisplayValue('भेजें')).toBeInTheDocument();
    expect(screen.getByDisplayValue('चैट बंद करें')).toBeInTheDocument();
    expect(screen.getByDisplayValue('हम जल्द वापस आएंगे')).toBeInTheDocument();
    expect(screen.getByTestId('widget-preview')).toHaveTextContent('मैं आपकी कैसे मदद कर सकता हूँ?');
  });

  it('reflects toggle and launcher changes immediately in the website preview', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole('heading', { name: 'Look and feel', level: 2 });

    await user.click(screen.getByRole('button', { name: 'Toggle' }));
    expect(screen.getByRole('button', { name: 'Preview spark launcher' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Bubble' }));
    expect(screen.getByRole('button', { name: 'Preview bubble launcher' })).toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: /Widget enabled/ }));
    expect(screen.getByText('Widget disabled')).toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: /Widget enabled/ }));
    await user.click(screen.getByRole('checkbox', { name: /Open on page load/ }));
    expect(screen.getByTestId('widget-preview')).toBeInTheDocument();
  });

  it('uses correctly labeled desktop and mobile preview canvases', async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByLabelText('Mobile website preview')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Desktop preview' }));
    expect(screen.getByLabelText('Desktop website preview')).toBeInTheDocument();
    expect(screen.getByTestId('widget-preview')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Preview spark launcher' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Toggle' }));
    expect(screen.getByRole('button', { name: 'Preview spark launcher' })).toBeInTheDocument();
    expect(screen.queryByTestId('widget-preview')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Preview spark launcher' }));
    expect(screen.getByTestId('widget-preview')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close preview widget' }));
    expect(screen.getByRole('button', { name: 'Preview spark launcher' })).toBeInTheDocument();
  });

  it('shows a compact mobile template for every integration without Test or Live controls', async () => {
    const user = userEvent.setup();
    renderPage();
    const selector = await screen.findByRole('combobox', { name: 'Select deployment channel' });

    const channels = [
      ['whatsapp', 'WhatsApp conversation preview'],
      ['instagram', 'Instagram direct-message preview'],
      ['facebook', 'Facebook Messenger preview'],
      ['slack', 'Slack preview'],
      ['teams', 'Microsoft Teams preview'],
      ['api', 'Developer API preview'],
      ['notion', 'Notion preview'],
      ['zapier', 'Zapier preview'],
    ] as const;

    for (const [channel, label] of channels) {
      await user.selectOptions(selector, channel);
      expect(screen.getByLabelText(label)).toHaveClass('channel-frame--mobile');
    }
    expect(screen.queryByRole('button', { name: 'Test' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Live' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Desktop preview' }));
    expect(screen.getByLabelText('Zapier preview')).toHaveClass('channel-frame--desktop');
  });

  it('opens the Website-style feedback options before submitting negative integration feedback', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Select deployment channel' }), 'instagram');

    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Can you help?');
    await user.click(screen.getByRole('button', { name: 'Send' }));
    await user.click(await screen.findByRole('button', { name: 'Negative feedback' }));

    expect(screen.getByRole('dialog', { name: 'Help us improve' })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Reason'), 'Incorrect Answer');
    await user.type(screen.getByLabelText('Additional comments'), 'The details are incorrect.');
    await user.click(screen.getByRole('button', { name: 'Submit feedback' }));

    await waitFor(() => expect(apiMocks.feedback).toHaveBeenCalledWith(
      'preview-answer',
      -1,
      'Incorrect Answer: The details are incorrect.',
    ));
    expect(screen.queryByRole('dialog', { name: 'Help us improve' })).not.toBeInTheDocument();
  });

  it('keeps the chosen integration and runs its localized interactive chat preview', async () => {
    const user = userEvent.setup();
    renderPage();
    const channelSelector = await screen.findByRole('combobox', { name: 'Select deployment channel' });

    await user.selectOptions(channelSelector, 'instagram');
    await user.click(screen.getByRole('button', { name: 'Localization' }));
    expect(channelSelector).toHaveValue('instagram');
    expect(screen.getByLabelText('Instagram direct-message preview')).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Interface language'), 'Hindi');
    expect(channelSelector).toHaveValue('instagram');
    const messageInput = screen.getByRole('textbox', { name: 'संदेश' });
    await user.type(messageInput, 'hii');
    await user.click(screen.getByRole('button', { name: 'भेजें' }));

    expect(await screen.findByText('नमस्ते')).toBeInTheDocument();
    expect(screen.queryByText('hii')).not.toBeInTheDocument();
    expect(await screen.findByText('मैं आपकी मदद कर सकता हूँ।')).toBeInTheDocument();
    expect(apiMocks.streamChat).toHaveBeenCalledWith(expect.objectContaining({ language: 'Hindi', message: 'hii' }), expect.any(AbortSignal));
    expect(screen.getByRole('link', { name: 'Northstar knowledge base' })).toHaveAttribute('href', `/agents/${original.id}/knowledge`);

    const positive = screen.getByRole('button', { name: 'सकारात्मक प्रतिक्रिया' });
    expect(screen.getByRole('button', { name: 'नकारात्मक प्रतिक्रिया' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'जवाब फिर से बनाएँ' })).toBeInTheDocument();
    await user.click(positive);
    await waitFor(() => expect(apiMocks.feedback).toHaveBeenCalledWith('preview-answer', 1, undefined));

    await user.click(screen.getByRole('button', { name: 'अधिक विकल्प' }));
    await user.click(screen.getByRole('menuitem', { name: 'नई बातचीत' }));
    expect(screen.queryByText('मैं आपकी मदद कर सकता हूँ।')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledWith(original.id, expect.objectContaining({
      language: 'Hindi',
      appearance: expect.objectContaining({ deploymentChannel: 'instagram', interfaceLanguage: 'Hindi' }),
    })));
  });

  it('shows only supported WhatsApp controls and uses the assigned number for sharing', async () => {
    original.appearance.deploymentChannel = 'whatsapp';
    original.whatsappNumber = '+91 81470 24024';
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('WhatsApp number for this bot');
    for (const name of ['Look and feel', 'Toggle', 'Conversation starters', 'Color studio', 'Font studio', 'Greeting editor', 'GDPR & consent', 'Other', 'Instant embed', 'IFrame embed']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByText('What services do you offer?')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Get link' }));
    expect(screen.getByRole('link', { name: 'Open WhatsApp' })).toHaveAttribute('href', 'https://wa.me/918147024024');
    await user.click(screen.getByRole('button', { name: 'Bot activation' }));
    expect(screen.getByRole('checkbox', { name: /Bot active/ })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /Open on page load/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Response language' }));
    await user.selectOptions(screen.getByLabelText('Response language'), 'Hindi');
    expect(screen.queryByLabelText('Interface language')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(apiMocks.update).toHaveBeenCalledWith(original.id, expect.objectContaining({ language: 'Hindi', appearance: expect.objectContaining({ welcomeMessage: original.appearance.welcomeMessage }) }));
    await user.selectOptions(screen.getByLabelText('Select deployment channel'), 'website');
    expect(await screen.findByRole('button', { name: 'Color studio' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Message format' })).not.toBeInTheDocument();
  });

  it('saves and reloads exact welcome copy and formatted reply structure without changing website appearance', async () => {
    original.appearance.deploymentChannel = 'whatsapp';
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Welcome message' }));
    const welcome = screen.getByLabelText('Welcome message text');
    fireEvent.change(welcome, { target: { value: 'Welcome to class!\n\nAsk your question.' } });
    (welcome as HTMLTextAreaElement).setSelectionRange(0, 16);
    await user.click(screen.getByRole('button', { name: 'Bold' }));
    expect(welcome).toHaveValue('*Welcome to class*!\n\nAsk your question.');
    const exactWelcome = (welcome as HTMLTextAreaElement).value;
    expect(within(screen.getByLabelText('WhatsApp conversation preview')).getByText('Welcome to class').tagName).toBe('STRONG');
    await user.click(screen.getByRole('button', { name: 'Message format' }));
    const structure = screen.getByLabelText('Reply structure');
    fireEvent.change(structure, { target: { value: '*{bot_name}*\n\n{message}\n\n_Thank you!_' } });
    expect(screen.getByLabelText('WhatsApp conversation preview')).toHaveTextContent('Thank you!');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenCalledWith(original.id, expect.objectContaining({ appearance: expect.objectContaining({ welcomeMessage: original.appearance.welcomeMessage, primaryColor: original.appearance.primaryColor, whatsapp: { welcomeEnabled: true, welcomeMessage: exactWelcome, replyTemplate: '*{bot_name}*\n\n{message}\n\n_Thank you!_' } }) })));
    fireEvent.change(structure, { target: { value: 'Missing answer' } });
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
    expect(screen.getByText(/Include \{message\} exactly once for/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reset changes' }));
    expect(structure).toHaveValue('*{bot_name}*\n\n{message}\n\n_Thank you!_');
    const patch = apiMocks.update.mock.calls.at(-1)![1];
    expect(patch).not.toHaveProperty('status');
    apiMocks.list.mockResolvedValue([{ ...original, ...patch }]);
    cleanup(); renderPage();
    await user.click(await screen.findByRole('button', { name: 'Welcome message' }));
    expect(screen.getByLabelText('Welcome message text')).toHaveValue(exactWelcome);
    await user.click(screen.getByRole('checkbox', { name: /Send welcome message/ }));
    expect(screen.getByLabelText('WhatsApp conversation preview')).not.toHaveTextContent('Welcome to class');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(apiMocks.update).toHaveBeenLastCalledWith(original.id, expect.objectContaining({ appearance: expect.objectContaining({ whatsapp: expect.objectContaining({ welcomeEnabled: false }) }) })));
  });
});
