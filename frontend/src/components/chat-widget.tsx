import '@fontsource-variable/inter';
import {
  ArrowUp,
  Check,
  Copy,
  ExternalLink,
  MessageSquareText,
  Mic,
  MoreVertical,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api } from '@/lib/api';
import { getChatUiLocale, getWidgetLocale, localizeAgentAppearance } from '@/lib/widget-localization';
import type { Agent, ChatMessage, WidgetSession } from '@/types';

interface WidgetProps {
  agent: Agent;
  embedded?: boolean;
  startOpen?: boolean;
  publicMode?: boolean;
  initialSession?: WidgetSession;
  requestNewSession?: () => Promise<WidgetSession>;
  onClose?: () => void;
}

interface WidgetBusinessHours {
  enabled?: boolean;
  timezone?: string;
  schedule?: Record<string, string[]>;
}

function isWithinBusinessHours(raw: string | undefined): boolean {
  if (!raw) return true;
  try {
    const policy = JSON.parse(raw) as WidgetBusinessHours;
    if (!policy.enabled) return true;
    const timezone = policy.timezone || 'UTC';
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: timezone,
      weekday: 'long',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).formatToParts(new Date());
    const weekday = parts.find((part) => part.type === 'weekday')?.value.toLowerCase() ?? '';
    const hour = Number(parts.find((part) => part.type === 'hour')?.value ?? '0') % 24;
    const minute = Number(parts.find((part) => part.type === 'minute')?.value ?? '0');
    const current = hour * 60 + minute;
    const ranges = policy.schedule?.[weekday] ?? [];
    return ranges.some((range) => {
      const [start, end] = range.split('-');
      if (!start || !end) return false;
      const [startHour, startMinute] = start.split(':').map(Number);
      const [endHour, endMinute] = end.split(':').map(Number);
      if (![startHour, startMinute, endHour, endMinute].every(Number.isFinite)) return false;
      const from = startHour! * 60 + startMinute!;
      const to = endHour! * 60 + endMinute!;
      return from <= to ? current >= from && current < to : current >= from || current < to;
    });
  } catch {
    return true;
  }
}

export function ChatWidget({
  agent,
  embedded = false,
  startOpen = true,
  publicMode = false,
  initialSession,
  requestNewSession,
  onClose,
}: WidgetProps) {
  const [open, setOpen] = useState(startOpen || embedded);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [conversationCopied, setConversationCopied] = useState(false);

  const [conversationId, setConversationId] = useState<string | undefined>(
    initialSession?.conversationId,
  );

  const [widgetToken, setWidgetToken] = useState<string | undefined>(
    initialSession?.sessionToken,
  );

  const [feedbackMessageId, setFeedbackMessageId] = useState<string | null>(
    null,
  );
  const [feedbackReason, setFeedbackReason] = useState('');
  const [feedbackComment, setFeedbackComment] = useState('');
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [consentChecked, setConsentChecked] = useState(false);
  const [consented, setConsented] = useState(!agent.appearance.requireConsent);

  const scrollRef = useRef<HTMLDivElement>(null);
  const moreMenuRef = useRef<HTMLDivElement>(null);
  const controller = useRef<AbortController>();
  const selectedLanguage = agent.appearance.interfaceLanguage || agent.language || 'English';
  const locale = getWidgetLocale(selectedLanguage);
  const chatUi = getChatUiLocale(selectedLanguage);
  const stillUsingEnglishDefaults = selectedLanguage !== 'English'
    && agent.appearance.welcomeTitle === getWidgetLocale('English').welcomeTitle;
  const displayAppearance = stillUsingEnglishDefaults
    ? localizeAgentAppearance(agent.appearance, selectedLanguage)
    : agent.appearance;
  const brandMetadata = (displayAppearance.translations ?? {}) as Record<string, string>;
  const launcherIcon = brandMetadata.launcherIcon?.trim() ?? '';
  const widgetLogo = brandMetadata.widgetLogo?.trim() ?? '';
  const agentAvatar = (brandMetadata.agentAvatar || brandMetadata.botAvatar || '').trim();
  const userMessageColor = brandMetadata.userMessageColor?.trim() || agent.appearance.primaryColor;
  const agentMessageColor = brandMetadata.agentMessageColor?.trim() || agent.appearance.surfaceColor;
  const poweredByLabel = brandMetadata.poweredByLabel?.trim() ?? '';
  const brandedWidgetName = displayAppearance.widgetName?.trim() ?? '';
  const withinBusinessHours = isWithinBusinessHours(brandMetadata.businessHours);
  const offlineMessage = brandMetadata.offlineMessage?.trim() || "We'll be back soon";

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, streaming]);

  useEffect(() => {
    return () => controller.current?.abort();
  }, []);

  useEffect(() => {
    if (!moreMenuOpen) return;

    const closeMenu = (event: MouseEvent) => {
      if (!moreMenuRef.current?.contains(event.target as Node)) setMoreMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMoreMenuOpen(false);
    };

    document.addEventListener('mousedown', closeMenu);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('mousedown', closeMenu);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [moreMenuOpen]);

  useEffect(() => {
    setConsented(!agent.appearance.requireConsent);
    setConsentChecked(false);
  }, [agent.appearance.requireConsent]);

  const reset = async () => {
    controller.current?.abort();
    setMoreMenuOpen(false);
    setConversationCopied(false);

    setMessages([]);
    setConversationId(undefined);
    setWidgetToken(undefined);
    setStreaming(false);

    setFeedbackOpen(false);
    setFeedbackMessageId(null);

    if (!requestNewSession) return;

    setResetting(true);

    try {
      const created = await requestNewSession();

      setConversationId(created.conversationId);
      setWidgetToken(created.sessionToken);
    } catch {
      setMessages([
        {
          id: `session-error-${Date.now()}`,
          role: 'assistant',
          content: `${chatUi.sessionError} ${chatUi.tryAgain}`,
          createdAt: new Date().toISOString(),
        },
      ]);
    } finally {
      setResetting(false);
    }
  };

  const copyConversation = async () => {
    if (messages.length === 0) return;
    const transcript = messages
      .filter((message) => message.content.trim())
      .map((message) => `${message.role === 'user' ? chatUi.message : agent.name}: ${message.content}`)
      .join('\n\n');

    await navigator.clipboard.writeText(transcript);
    setConversationCopied(true);
    window.setTimeout(() => setConversationCopied(false), 1800);
  };

  const submitPositiveFeedback = async (messageId: string) => {
    try {
      await api.feedback(messageId, 1);
    } catch (error) {
      console.error('Positive feedback failed:', error);
    }
  };

  const openNegativeFeedback = (messageId: string) => {
    setFeedbackMessageId(messageId);
    setFeedbackReason('');
    setFeedbackComment('');
    setFeedbackOpen(true);
  };

  const submitNegativeFeedback = async () => {
  if (!feedbackMessageId) return;

  const reason = feedbackReason.trim();
  const comment = feedbackComment.trim();

  if (!reason) return;

  const feedbackText = comment
    ? `${reason}: ${comment}`
    : reason;

  try {
    await api.feedback(
      feedbackMessageId,
      -1,
      feedbackText,
    );

    setFeedbackOpen(false);
    setFeedbackMessageId(null);
    setFeedbackReason('');
    setFeedbackComment('');
  } catch (error) {
    console.error('Negative feedback failed:', error);

    window.alert(
      error instanceof Error
        ? error.message
        : 'Could not submit feedback.',
    );
  }
};

  const send = async (
    value: string,
    replaceAssistantId?: string,
  ) => {
    const content = value.trim();

    if (!content || streaming || !consented) return;

    setInput('');

    const responseId = replaceAssistantId ?? `response-${Date.now()}`;
    const userMessageId = replaceAssistantId ? undefined : `local-${Date.now()}`;
    let currentResponseId = responseId;

    if (replaceAssistantId) {
      setMessages((current) =>
        current.map((message) =>
          message.id === replaceAssistantId
            ? {
                ...message,
                content: '',
                citations: [],
              }
            : message,
        ),
      );
    } else {
      const userMessage: ChatMessage = {
        id: userMessageId!,
        role: 'user',
        content,
        createdAt: new Date().toISOString(),
      };

      setMessages((current) => [
        ...current,
        userMessage,
        {
          id: responseId,
          role: 'assistant',
          content: '',
          createdAt: new Date().toISOString(),
          citations: [],
        },
      ]);
    }

    setStreaming(true);
    controller.current = new AbortController();

    try {
      let activeConversationId = conversationId;
      let activeWidgetToken = widgetToken;

      if (
        publicMode &&
        (!activeConversationId || !activeWidgetToken)
      ) {
        const created = requestNewSession
          ? await requestNewSession()
          : await api.widget.createSession(agent.publicId);

        activeConversationId = created.conversationId;
        activeWidgetToken = created.sessionToken;

        setConversationId(activeConversationId);
        setWidgetToken(activeWidgetToken);
      }

      const events =
        publicMode &&
        activeConversationId &&
        activeWidgetToken
          ? api.widget.streamChat(
              {
                conversationId: activeConversationId,
                sessionToken: activeWidgetToken,
                message: content,
                language: selectedLanguage,
              },
              controller.current.signal,
            )
          : api.streamChat(
              {
                agentId: agent.id,
                message: content,
                conversationId,
                language: selectedLanguage,
              },
              controller.current.signal,
            );

      for await (const event of events) {
  if (event.type === 'start') {
    setConversationId(event.conversationId);

    if ('messageId' in event && event.messageId) {
      currentResponseId = event.messageId;

      setMessages((current) =>
        current.map((message) =>
          message.id === responseId
            ? {
                ...message,
                id: event.messageId,
              }
            : message,
        ),
      );
    }
  }

  if (event.type === 'token') {
    setMessages((current) =>
      current.map((message) =>
        message.id === currentResponseId
          ? {
              ...message,
              content: message.content + event.content,
            }
          : message,
      ),
    );
  }

  if (event.type === 'user_translation' && userMessageId && event.content.trim()) {
    setMessages((current) =>
      current.map((message) =>
        message.id === userMessageId
          ? { ...message, content: event.content.trim() }
          : message,
      ),
    );
  }

  if (event.type === 'citation') {
    setMessages((current) =>
      current.map((message) =>
        message.id === currentResponseId
          ? {
              ...message,
              citations: [
                ...(message.citations ?? []),
                {
                  title: event.title,
                  url: event.url,
                },
              ],
            }
          : message,
      ),
    );
  }

  if (event.type === 'error') {
    setMessages((current) =>
      current.map((message) =>
        message.id === currentResponseId
          ? {
              ...message,
              content: selectedLanguage === 'English'
                ? `${chatUi.responseError} ${event.message}`
                : `${chatUi.responseError} ${chatUi.tryAgain}`,
            }
          : message,
      ),
    );
  }
}
    } catch (error) {
      setMessages((current) =>
        current.map((message) =>
          message.id === responseId
            ? {
                ...message,
                content: selectedLanguage === 'English' && error instanceof Error
                  ? `${chatUi.responseError} ${error.message}`
                  : `${chatUi.responseError} ${chatUi.tryAgain}`,
              }
            : message,
        ),
      );
    } finally {
      setStreaming(false);
    }
  };

  const regenerate = async (messageIndex: number) => {
    if (streaming) return;

    const assistantMessage = messages[messageIndex];

    const previousMessage = messages[messageIndex - 1];

    if (
      !assistantMessage ||
      assistantMessage.role !== 'assistant' ||
      !previousMessage ||
      previousMessage.role !== 'user'
    ) {
      return;
    }

    await send(
      previousMessage.content,
      assistantMessage.id,
    );
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void send(input);
  };

  if (!open && !embedded) {
    return (
      <button
        className="widget-launcher"
        style={{
          background: agent.appearance.primaryColor,
        }}
        onClick={() => setOpen(true)}
        aria-label={`${chatUi.openChat} ${agent.name}`}
      >
        {launcherIcon ? (
          <img src={launcherIcon} alt="" style={{ width: 30, height: 30, objectFit: 'contain' }} />
        ) : agent.appearance.launcherStyle === 'bubble' ? (
          <MessageSquareText />
        ) : agent.appearance.launcherStyle === 'avatar' ? (
          <span className="widget-launcher__avatar">
            {agent.avatar.slice(0, 2)}
          </span>
        ) : (
          <Sparkles />
        )}
      </button>
    );
  }

  const translations = displayAppearance.translations;
  const newConversationLabel = translations?.newConversation ?? (agent.appearance.interfaceLanguage ? locale.translations.newConversation : 'Start a new conversation');
  const closeChatLabel = translations?.closeChat ?? (agent.appearance.interfaceLanguage ? locale.translations.closeChat : 'Close chat');
  const sendButtonLabel = translations?.sendButton ?? (agent.appearance.interfaceLanguage ? locale.translations.sendButton : 'Send message');

  return (
    <section
      className={`chat-widget ${
        embedded ? 'chat-widget--embedded' : ''
      }`}
      dir={displayAppearance.textDirection ?? 'ltr'}
      style={
        {
          '--widget-primary':
            agent.appearance.primaryColor,
          '--widget-surface':
            agent.appearance.surfaceColor,
          '--widget-user-message': userMessageColor,
          '--widget-agent-message': agentMessageColor,
          fontFamily: agent.appearance.fontFamily ?? 'Inter',
          borderRadius: agent.appearance.cornerRadius ?? 24,
        } as React.CSSProperties
      }
      aria-label={`Chat with ${agent.name}`}
    >
      <header className="widget-header">
        <div className="widget-wordmark">
          <span className="widget-logo">
            {widgetLogo ? <img src={widgetLogo} alt="" style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} /> : <Sparkles />}
          </span>

          {brandedWidgetName ? <strong>{brandedWidgetName}</strong> : <strong>northstar<span>ai</span></strong>}
        </div>

        <div className="widget-header-actions">
          <button
            onClick={() => void reset()}
            disabled={resetting || streaming}
            aria-label={newConversationLabel}
            title={newConversationLabel}
          >
            <RefreshCw />
          </button>

          <div className="widget-more-menu" ref={moreMenuRef}>
            <button
              type="button"
              aria-label={locale.moreOptions}
              aria-haspopup="menu"
              aria-expanded={moreMenuOpen}
              onClick={() => {
                setConversationCopied(false);
                setMoreMenuOpen((current) => !current);
              }}
            >
              <MoreVertical />
            </button>

            {moreMenuOpen ? (
              <div className="widget-more-popover" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  disabled={resetting || streaming}
                  onClick={() => void reset()}
                >
                  <RefreshCw />
                  <span>{newConversationLabel}</span>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  disabled={messages.length === 0}
                  onClick={() => void copyConversation()}
                >
                  {conversationCopied ? <Check /> : <Copy />}
                  <span>{conversationCopied ? chatUi.conversationCopied : chatUi.copyConversation}</span>
                </button>
              </div>
            ) : null}
          </div>

          {!embedded && onClose ? (
            <button
              onClick={onClose}
              aria-label={closeChatLabel}
            >
              <X />
            </button>
          ) : null}
        </div>
      </header>

      <div
        className="widget-body"
        ref={scrollRef}
      >
        {messages.length === 0 ? (
          <div className="widget-welcome">
            <span className="widget-orb">
              {agentAvatar ? <img src={agentAvatar} alt="" style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'cover', borderRadius: '50%' }} /> : <Sparkles />}
            </span>

            <h2>
              {displayAppearance.welcomeTitle}
            </h2>

            {displayAppearance.greetingMode !== 'never' ? (
              <p>{displayAppearance.welcomeMessage}</p>
            ) : null}

            {!withinBusinessHours ? <p role="status">{offlineMessage}</p> : null}

            {!consented ? (
              <div className="widget-consent">
                <label>
                  <input
                    type="checkbox"
                    checked={consentChecked}
                    onChange={(event) => setConsentChecked(event.target.checked)}
                  />
                  <span>{displayAppearance.consentMessage ?? chatUi.consentMessage}</span>
                </label>
                {displayAppearance.privacyPolicyUrl ? (
                  <a href={displayAppearance.privacyPolicyUrl} target="_blank" rel="noreferrer">
                    {locale.privacyPolicy} <ExternalLink />
                  </a>
                ) : null}
                <button disabled={!consentChecked} onClick={() => setConsented(true)}>
                  {locale.continueLabel}
                </button>
              </div>
            ) : (
              <div className="suggestion-list">
                {displayAppearance.suggestedQuestions
                  .filter(Boolean)
                  .map((question) => (
                    <button
                      key={question}
                      onClick={() => void send(question)}
                    >
                      {question}
                      <ArrowUp />
                    </button>
                  ))}
              </div>
            )}
          </div>
        ) : (
          <div className="message-list">
            <div className="message-day">
              <span>{locale.today}</span>
            </div>

            {messages.map((message, index) => (
              <div
                key={message.id}
                className={`chat-message chat-message--${message.role}`}
              >
                {message.role === 'assistant' ? (
                  <span className="message-avatar">
                    {agentAvatar ? <img src={agentAvatar} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} /> : <Sparkles />}
                  </span>
                ) : null}

                <div className="message-bubble" style={{ background: message.role === 'user' ? 'var(--widget-user-message)' : message.role === 'assistant' ? 'var(--widget-agent-message)' : undefined }}>
                  {message.content ||
                    (streaming &&
                    index === messages.length - 1 ? (
                      <span className="typing">
                        <i />
                        <i />
                        <i />
                      </span>
                    ) : null)}

                  {message.citations?.length ? (
                    <div className="citations">
                      {message.citations.map(
                        (citation) => (
                          <span
                            key={citation.title}
                          >
                            <ExternalLink />
                            {citation.title}
                          </span>
                        ),
                      )}
                    </div>
                  ) : null}

                  {message.role === 'assistant' ? (
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '5px',
                        marginTop: '5px',
                      }}
                    >
                      <button
                        type="button"
                        onClick={() =>
                          void submitPositiveFeedback(
                            message.id,
                          )
                        }
                        aria-label={chatUi.positiveFeedback}
                        title={chatUi.helpful}
                        style={{
                          border: 'none',
                          background: 'transparent',
                          color:
                            'var(--widget-primary)',
                          cursor: 'pointer',
                          padding: '2px',
                          display: 'flex',
                          alignItems: 'center',
                        }}
                      >
                        <ThumbsUp
                          size={8}
                          strokeWidth={2}
                        />
                      </button>

                      <button
                        type="button"
                        onClick={() =>
                          openNegativeFeedback(
                            message.id,
                          )
                        }
                        aria-label={chatUi.negativeFeedback}
                        title={chatUi.notHelpful}
                        style={{
                          border: 'none',
                          background: 'transparent',
                          color:
                            'var(--widget-primary)',
                          cursor: 'pointer',
                          padding: '2px',
                          display: 'flex',
                          alignItems: 'center',
                        }}
                      >
                        <ThumbsDown
                          size={8}
                          strokeWidth={2}
                        />
                      </button>

                      <button
                        type="button"
                        onClick={() =>
                          void regenerate(index)
                        }
                        aria-label={chatUi.regenerateAnswer}
                        title={chatUi.regenerate}
                        disabled={streaming}
                        style={{
                          border: 'none',
                          background: 'transparent',
                          color:
                            'var(--widget-primary)',
                          cursor: streaming
                            ? 'not-allowed'
                            : 'pointer',
                          padding: '2px',
                          display: 'flex',
                          alignItems: 'center',
                        }}
                      >
                        <RefreshCw
                          size={8}
                          strokeWidth={2}
                        />
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <footer className="widget-footer">
        {!withinBusinessHours && messages.length > 0 ? <p role="status">{offlineMessage}</p> : null}
        <form onSubmit={submit}>
          <textarea
            rows={1}
            value={input}
            disabled={!consented}
            onChange={(event) =>
              setInput(event.target.value)
            }
            onKeyDown={(event) => {
              if (
                event.key === 'Enter' &&
                !event.shiftKey
              ) {
                event.preventDefault();
                void send(input);
              }
            }}
            placeholder={consented ? displayAppearance.placeholder : locale.acceptConsent}
            aria-label={chatUi.message}
          />

          <div className="composer-actions">
            <button
              type="button"
              aria-label={locale.voiceInput}
              title={locale.voiceInput}
              disabled={!consented}
            >
              <Mic />
            </button>

            <span />

            <button
              type="submit"
              className="send-button"
              disabled={!consented || !input.trim() || streaming}
              aria-label={sendButtonLabel}
            >
              <ArrowUp />
            </button>
          </div>
        </form>

        <p>
          <ShieldCheck />
          {locale.safetyNotice}
        </p>

        {agent.appearance.showBranding ? (
          <small>
            {poweredByLabel || <>{locale.poweredBy}{' '}<strong><Sparkles /> Northstar AI</strong></>}
          </small>
        ) : null}
      </footer>

      {feedbackOpen ? (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.35)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
            padding: '20px',
            boxSizing: 'border-box',
          }}
        >
          <div
            style={{
              width: 'min(480px, 100%)',
              background:
                'var(--widget-surface, #ffffff)',
              borderRadius: '14px',
              padding: '22px',
              boxShadow:
                '0 16px 50px rgba(0, 0, 0, 0.22)',
              boxSizing: 'border-box',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '8px',
              }}
            >
              <h2
                style={{
                  margin: 0,
                  fontSize: '20px',
                }}
              >
                {chatUi.feedbackTitle}
              </h2>

              <button
                type="button"
                onClick={() =>
                  setFeedbackOpen(false)
                }
                aria-label={chatUi.closeFeedback}
                style={{
                  border: 'none',
                  background: 'transparent',
                  cursor: 'pointer',
                  fontSize: '20px',
                  color:
                    'var(--widget-primary)',
                }}
              >
                ×
              </button>
            </div>

            <p
              style={{
                marginTop: '4px',
                marginBottom: '18px',
              }}
            >
              {chatUi.feedbackQuestion}
            </p>

            <label
              htmlFor="feedback-reason"
              style={{
                display: 'block',
                marginBottom: '6px',
                fontWeight: 600,
              }}
            >
              {chatUi.reason}
            </label>

            <select
              id="feedback-reason"
              value={feedbackReason}
              onChange={(event) =>
                setFeedbackReason(
                  event.target.value,
                )
              }
              style={{
                width: '100%',
                padding: '10px',
                borderRadius: '8px',
                border: '1px solid #d9dfe8',
                marginBottom: '16px',
                boxSizing: 'border-box',
              }}
            >
              <option value="">
                {chatUi.selectReason}
              </option>

              <option value="Incorrect Answer">
                {chatUi.incorrectAnswer}
              </option>

              <option value="Incomplete Answer">
                {chatUi.incompleteAnswer}
              </option>

              <option value="Hallucinated Response">
                {chatUi.hallucinatedResponse}
              </option>

              <option value="Irrelevant Answer">
                {chatUi.irrelevantAnswer}
              </option>

              <option value="Other">
                {chatUi.other}
              </option>
            </select>

            <label
              htmlFor="feedback-comment"
              style={{
                display: 'block',
                marginBottom: '6px',
                fontWeight: 600,
              }}
            >
              {chatUi.additionalComments}
            </label>

            <textarea
              id="feedback-comment"
              value={feedbackComment}
              onChange={(event) =>
                setFeedbackComment(
                  event.target.value,
                )
              }
              placeholder={chatUi.commentsPlaceholder}
              rows={4}
              style={{
                width: '100%',
                padding: '10px',
                borderRadius: '8px',
                border:
                  '1px solid #d9dfe8',
                resize: 'vertical',
                boxSizing: 'border-box',
                marginBottom: '18px',
              }}
            />

            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '10px',
              }}
            >
              <button
                type="button"
                onClick={() =>
                  setFeedbackOpen(false)
                }
                style={{
                  padding: '9px 14px',
                  borderRadius: '8px',
                  border:
                    '1px solid #d9dfe8',
                  background: 'transparent',
                  cursor: 'pointer',
                }}
              >
                {chatUi.cancel}
              </button>

              <button
                type="button"
                disabled={!feedbackReason}
                onClick={() =>
                  void submitNegativeFeedback()
                }
                style={{
                  padding: '9px 14px',
                  borderRadius: '8px',
                  border: 'none',
                  background:
                    'var(--widget-primary)',
                  color: '#ffffff',
                  cursor: feedbackReason
                    ? 'pointer'
                    : 'not-allowed',
                  opacity: feedbackReason
                    ? 1
                    : 0.55,
                }}
              >
                {chatUi.submitFeedback}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function WidgetPreview({
  agent,
}: {
  agent: Agent;
}) {
  return (
    <aside className="widget-preview">
      <div className="preview-toolbar">
        <span>
          <i className="status-dot status-dot--success" />
          Live preview
        </span>

        <button
          aria-label="Open preview options"
        >
          <MoreVertical />
        </button>
      </div>

      <div className="phone-frame">
        <div className="phone-speaker" />
        <ChatWidget
          agent={agent}
          embedded
        />
      </div>

      <p>
        Changes appear here before you publish.
      </p>
    </aside>
  );
}
