import { Bold, Code2, Italic, List, ListOrdered, Quote, Strikethrough } from 'lucide-react';
import { Fragment, useRef, useState, type ReactNode } from 'react';
import { Card, Field, Switch } from '@/components/ui';
import { applyWhatsAppFormatting, formatWhatsAppReply, whatsappMessageSettings, whatsappTemplateError } from '@/lib/whatsapp-messages';
import type { Agent, AgentAppearance } from '@/types';
import './whatsapp-message-editor.css';

export function WhatsAppMessageEditor({ agent, section, onChange }: {
  agent: Agent;
  section: 'welcome' | 'format';
  onChange: (patch: Partial<AgentAppearance>) => void;
}) {
  const settings = whatsappMessageSettings(agent);
  const update = (patch: Partial<typeof settings>) => onChange({ whatsapp: { ...settings, ...patch } });
  return <Card className="deploy-panel wa-message-editor">
    <div className="deploy-panel__heading">
      <h3>{section === 'welcome' ? 'Welcome message' : 'Message format & structure'}</h3>
      <p>{section === 'welcome' ? 'Choose the exact reply sent when someone says Hi, Hello, or another short greeting.' : 'Arrange your bot’s answers with headings, spacing, lists, and a closing message.'}</p>
    </div>
    <div className="deploy-panel__body">
      {section === 'welcome' ? <>
        <Switch label="Send welcome message" checked={settings.welcomeEnabled} onChange={(welcomeEnabled) => update({ welcomeEnabled })} description="Respond to short greetings using this saved message." />
        <FormattedTextField id="wa-welcome" label="Welcome message text" value={settings.welcomeMessage ?? ''} maxLength={4096} onChange={(welcomeMessage) => update({ welcomeMessage })} error={settings.welcomeEnabled && !settings.welcomeMessage?.trim() ? 'Enter a welcome message or turn it off.' : undefined} />
        <p className="wa-editor-note">Sent after the customer messages this bot. Course enrollment and access checks still apply to education bots. Turning this off lets the bot answer greetings normally.</p>
      </> : <>
        <FormattedTextField id="wa-reply-template" label="Reply structure" value={settings.replyTemplate} maxLength={1500} onChange={(replyTemplate) => update({ replyTemplate })} error={whatsappTemplateError(settings.replyTemplate)} />
        <p className="wa-editor-note"><code>{'{message}'}</code> inserts the bot’s answer. <code>{'{bot_name}'}</code> inserts its name. Keep the answer placeholder exactly once. The welcome message uses its own format.</p>
        <div className="wa-structure-presets" aria-label="Reply structure presets">
          <button type="button" onClick={() => update({ replyTemplate: '{message}' })}>Answer only</button>
          <button type="button" onClick={() => update({ replyTemplate: '*{bot_name}*\n\n{message}' })}>Bot heading</button>
          <button type="button" onClick={() => update({ replyTemplate: '*{bot_name}*\n\n{message}\n\n_Anything else I can help with?_' })}>Heading & closing</button>
        </div>
        <p className="wa-editor-note">This structure is applied to automatic WhatsApp answers. Line breaks are preserved. Long answers are delivered in separate messages.</p>
      </>}
      <p className="wa-editor-note">Select text to apply bold, italic, strikethrough, or monospace. WhatsApp controls the font family, font size, colors, and chat layout.</p>
    </div>
  </Card>;
}

function FormattedTextField({ id, label, value, maxLength, onChange, error }: {
  id: string; label: string; value: string; maxLength: number; onChange: (value: string) => void; error?: string;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  const [formatError, setFormatError] = useState('');
  const format = (marker: string, kind: 'wrap' | 'line' = 'wrap') => {
    const node = input.current;
    if (!node) return;
    const next = applyWhatsAppFormatting(value, node.selectionStart, node.selectionEnd, marker, kind);
    if (next.value.length > maxLength) { setFormatError('Shorten the message before adding more formatting.'); return; }
    setFormatError('');
    onChange(next.value);
    requestAnimationFrame(() => { node.focus(); node.setSelectionRange(next.start, next.end); });
  };
  return <Field label={label} htmlFor={id} error={error} hint={`${value.length.toLocaleString()} / ${maxLength.toLocaleString()} characters`}>
    <div className="wa-format-toolbar" role="toolbar" aria-label={`${label} formatting`}>
      {([{ label: 'Bold', icon: Bold, marker: '*' }, { label: 'Italic', icon: Italic, marker: '_' }, { label: 'Strikethrough', icon: Strikethrough, marker: '~' }, { label: 'Monospace', icon: Code2, marker: '```' }] as const).map(({ label: title, icon: Icon, marker }) => <button key={title} type="button" aria-label={title} title={title} onMouseDown={(event) => event.preventDefault()} onClick={() => format(marker)}><Icon /></button>)}
      {([{ label: 'Bulleted list', icon: List, marker: '- ' }, { label: 'Numbered list', icon: ListOrdered, marker: '1. ' }, { label: 'Quote', icon: Quote, marker: '> ' }] as const).map(({ label: title, icon: Icon, marker }) => <button key={title} type="button" aria-label={title} title={title} onMouseDown={(event) => event.preventDefault()} onClick={() => format(marker, 'line')}><Icon /></button>)}
    </div>
    <textarea ref={input} id={id} rows={8} value={value} maxLength={maxLength} aria-invalid={Boolean(error || formatError)} onChange={(event) => { setFormatError(''); onChange(event.target.value); }} spellCheck />
    {formatError ? <small className="field__error" role="alert">{formatError}</small> : null}
  </Field>;
}

function inlineText(text: string, depth = 0): ReactNode {
  if (depth > 5) return text;
  const parts = text.split(/(```[\s\S]+?```|`[^`\n]+`|\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~)/g);
  return parts.map((part, index) => {
    if (index % 2 === 0) return <Fragment key={index}>{part}</Fragment>;
    if (part.startsWith('```') && part.endsWith('```')) return <code key={index}>{part.slice(3, -3)}</code>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith('*') && part.endsWith('*')) return <strong key={index}>{inlineText(part.slice(1, -1), depth + 1)}</strong>;
    if (part.startsWith('_') && part.endsWith('_')) return <em key={index}>{inlineText(part.slice(1, -1), depth + 1)}</em>;
    if (part.startsWith('~') && part.endsWith('~')) return <s key={index}>{inlineText(part.slice(1, -1), depth + 1)}</s>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}

export function WhatsAppText({ text }: { text: string }) {
  const blocks = text.split(/(```[\s\S]+?```)/g);
  return <div className="wa-formatted-text">{blocks.map((block, index) => index % 2 ? <code key={index}>{block.slice(3, -3)}</code> : <Fragment key={index}>{block.split('\n').map((line, lineIndex, lines) => <Fragment key={lineIndex}>{line.startsWith('> ') ? <span className="wa-text-quote">{inlineText(line.slice(2))}</span> : inlineText(line.replace(/^[-*] /, '• '))}{lineIndex < lines.length - 1 ? '\n' : null}</Fragment>)}</Fragment>)}</div>;
}

export function WhatsAppMessagePreview({ agent, device, showReply = false }: { agent: Agent; device: 'desktop' | 'mobile'; showReply?: boolean }) {
  const settings = whatsappMessageSettings(agent);
  return <section className={`wa-message-preview channel-frame channel-frame--${device}`} aria-label="WhatsApp conversation preview">
    <header><span className="wa-preview-avatar">{agent.avatar}</span><div><strong>{agent.name}</strong><small>{agent.whatsappNumber || 'No number assigned'}</small></div></header>
    <div className="wa-preview-messages">
      <span className="wa-preview-day">Message preview</span>
      {settings.welcomeEnabled && <><div className="wa-preview-bubble wa-preview-bubble--out">Hi</div><div className="wa-preview-bubble"><WhatsAppText text={settings.welcomeMessage ?? ''} /></div></>}
      {(!settings.welcomeEnabled || showReply) && <><div className="wa-preview-bubble wa-preview-bubble--out">Can you help me?</div><div className="wa-preview-bubble"><WhatsAppText text={formatWhatsAppReply(agent, 'Here is an example answer.\n\n- First useful detail\n- Next step')} /></div></>}
    </div>
    <footer>{agent.status === 'active' ? agent.whatsappNumber ? 'Active bot' : 'Assign a WhatsApp number to enable replies' : agent.status === 'draft' ? 'Draft · activate this bot to enable replies' : `Bot status: ${agent.status}`}</footer>
  </section>;
}
