import { useMemo, useRef, useState } from 'react';
import { Columns3, ListChecks, MessageSquareText, Plus, Send, Smile, Trash2, X } from 'lucide-react';
import type { ChatMessage } from '@/types';

export interface StructuredReply {
  content: string;
  messageFormat: NonNullable<ChatMessage['messageFormat']>;
}

type FormatType = StructuredReply['messageFormat']['type'];
const cells = (value: string) => value.split(',').map(item => item.trim()).filter(Boolean);
const richFormats: Array<[FormatType, string]> = [['list', 'List menu'], ['image', 'Image'], ['video', 'Video'], ['audio', 'Audio'], ['document', 'Document'], ['sticker', 'Sticker'], ['location', 'Location'], ['contact', 'Contact'], ['cta_url', 'Website CTA'], ['flow', 'WhatsApp Flow'], ['product', 'Product'], ['product_list', 'Product list'], ['catalog', 'Catalog']];

export function WhatsAppReplyComposer({ sending, onSend }: { sending: boolean; onSend: (reply: StructuredReply) => Promise<boolean> }) {
  const [format, setFormat] = useState<FormatType>('text');
  const [content, setContent] = useState('');
  const [buttons, setButtons] = useState(['']);
  const [columns, setColumns] = useState('Item, Details');
  const [rows, setRows] = useState('');
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [mediaUrl, setMediaUrl] = useState('');
  const [filename, setFilename] = useState('');
  const [configuration, setConfiguration] = useState('');
  const input = useRef<HTMLTextAreaElement>(null);
  const tableColumns = useMemo(() => cells(columns), [columns]);
  const tableRows = useMemo(() => rows.split('\n').map(cells).filter(row => row.length), [rows]);
  let parsedConfig: Record<string, unknown> | null = null;
  if (configuration.trim()) { try { parsedConfig = JSON.parse(configuration) as Record<string, unknown>; } catch { parsedConfig = null; } }
  const mediaFormat = ['image', 'video', 'audio', 'document', 'sticker'].includes(format);
  const jsonFormat = ['list', 'location', 'contact', 'cta_url', 'flow', 'product', 'product_list', 'catalog'].includes(format);
  const valid = Boolean(content.trim()) && (format === 'text'
    || (format === 'buttons' && buttons.some(button => button.trim()) && content.trim().length <= 1024)
    || (format === 'table' && tableColumns.length > 0 && tableRows.length > 0 && tableRows.every(row => row.length === tableColumns.length))
    || (mediaFormat && Boolean(mediaUrl.trim())) || (jsonFormat && parsedConfig !== null));

  const submit = async () => {
    if (!valid || sending) return;
    const messageFormat: StructuredReply['messageFormat'] = format === 'buttons'
      ? { type: 'buttons', buttons: buttons.filter(Boolean).map((title, index) => ({ id: `reply_${index + 1}`, title: title.trim() })) }
      : format === 'table'
        ? { type: 'table', table: { columns: tableColumns, rows: tableRows } }
        : format === 'text' ? { type: 'text' }
          : mediaFormat ? { type: format, config: { url: mediaUrl.trim(), ...(format === 'document' && filename.trim() ? { filename: filename.trim() } : {}) } }
            : { type: format, config: format === 'location' ? parsedConfig ?? {} : format === 'contact' ? { contact: parsedConfig } : { action: parsedConfig } };
    if (await onSend({ content: content.trim(), messageFormat })) {
      setContent(''); setRows(''); setButtons(['']); setMediaUrl(''); setFilename(''); setConfiguration('');
    }
  };

  return <div className="wa-composer-shell">
    <div className="wa-format-tabs" role="tablist" aria-label="Message format">
      {([['text', MessageSquareText, 'Text'], ['buttons', ListChecks, 'Buttons'], ['table', Columns3, 'Table']] as const).map(([value, Icon, label]) => <button key={value} type="button" role="tab" aria-selected={format === value} className={format === value ? 'is-active' : ''} onClick={() => setFormat(value)}><Icon />{label}</button>)}
      <label className="wa-more-format"><span className="sr-only">More message formats</span><select aria-label="More message formats" value={richFormats.some(([value]) => value === format) ? format : ''} onChange={event => setFormat(event.target.value as FormatType)}><option value="">More formats…</option>{richFormats.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <span>Choose exactly how this reply will be sent</span>
    </div>
    {format === 'buttons' ? <div className="wa-format-editor">
      <strong>Quick-reply buttons</strong><small>Up to 3 buttons, 20 characters each. The student taps one to reply.</small>
      <div className="wa-button-fields">{buttons.map((button, index) => <label key={index}><span>Button {index + 1}</span><input value={button} maxLength={20} placeholder={index === 0 ? 'Example: Switch to CPA' : 'Button label'} onChange={event => setButtons(items => items.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} />{buttons.length > 1 ? <button type="button" aria-label={`Remove button ${index + 1}`} onClick={() => setButtons(items => items.filter((_, itemIndex) => itemIndex !== index))}><Trash2 /></button> : null}</label>)}</div>
      {buttons.length < 3 ? <button type="button" className="wa-add-field" onClick={() => setButtons(items => [...items, ''])}><Plus />Add button</button> : null}
    </div> : null}
    {format === 'table' ? <div className="wa-format-editor">
      <strong>Table content</strong><small>Use commas between columns and a new line for each row. WhatsApp receives a readable text table.</small>
      <label><span>Column headings</span><input value={columns} placeholder="Course, Status, Expiry" onChange={event => setColumns(event.target.value)} /></label>
      <label><span>Rows</span><textarea value={rows} rows={3} placeholder={'CMA, Active, 15 Jan 2027\nCPA, Active, 20 Dec 2027'} onChange={event => setRows(event.target.value)} /></label>
      {tableRows.some(row => row.length !== tableColumns.length) ? <small className="wa-format-error">Every row must have {tableColumns.length} comma-separated cells.</small> : null}
    </div> : null}
    {mediaFormat ? <div className="wa-format-editor"><strong>{richFormats.find(([value]) => value === format)?.[1]}</strong><small>Paste a public HTTPS media URL that Meta can download.</small><label><span>Media URL</span><input value={mediaUrl} placeholder="https://example.com/media" onChange={event => setMediaUrl(event.target.value)} /></label>{format === 'document' ? <label><span>Filename</span><input value={filename} placeholder="study-guide.pdf" onChange={event => setFilename(event.target.value)} /></label> : null}</div> : null}
    {jsonFormat ? <div className="wa-format-editor"><strong>{richFormats.find(([value]) => value === format)?.[1]}</strong><small>{format === 'location' ? 'Enter latitude, longitude, name and address.' : format === 'contact' ? 'Enter a WhatsApp contact object.' : 'Enter the Meta interactive action object.'}</small><label><span>Configuration</span><textarea rows={4} value={configuration} placeholder={format === 'location' ? '{"latitude":"28.6139","longitude":"77.2090","name":"Learning Centre","address":"New Delhi"}' : format === 'contact' ? '{"name":{"formatted_name":"Counsellor"},"phones":[{"phone":"+911234567890"}]}' : '{"name":"cta_url","parameters":{"display_text":"Open portal","url":"https://example.com"}}'} onChange={event => setConfiguration(event.target.value)} /></label>{configuration.trim() && !parsedConfig ? <small className="wa-format-error">Enter valid JSON before sending.</small> : null}</div> : null}
    {(format === 'buttons' || format === 'table') && content.trim() ? <div className="wa-format-preview" aria-label="Message preview"><small>Preview</small><p>{content}</p>{format === 'buttons' ? <div>{buttons.filter(Boolean).map(button => <span key={button}>{button}</span>)}</div> : <table><thead><tr>{tableColumns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{tableRows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table>}</div> : null}
    <form className="wa-composer" onSubmit={event => { event.preventDefault(); void submit(); }}>
      {emojiOpen ? <div className="wa-emoji-picker" role="group" aria-label="Choose an emoji">{['😀', '😊', '👍', '🙏', '❤️', '🎉', '✅', '👋'].map(emoji => <button type="button" key={emoji} aria-label={`Insert ${emoji}`} onClick={() => { const start = input.current?.selectionStart ?? content.length; const end = input.current?.selectionEnd ?? content.length; setContent(content.slice(0, start) + emoji + content.slice(end)); setEmojiOpen(false); input.current?.focus(); }}>{emoji}</button>)}</div> : null}
      <button type="button" className="wa-composer-icon" aria-label={emojiOpen ? 'Close emoji picker' : 'Insert emoji'} aria-expanded={emojiOpen} disabled={sending} onClick={() => setEmojiOpen(!emojiOpen)}>{emojiOpen ? <X /> : <Smile />}</button>
      <textarea ref={input} aria-label="WhatsApp message" value={content} onChange={event => setContent(event.target.value)} placeholder={format === 'text' ? 'Type a message' : format === 'buttons' ? 'Type the message shown above the buttons' : 'Type the introduction shown above the table'} rows={1} disabled={sending} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (valid && !sending) void submit(); } }} />
      <button className="wa-send" type="submit" aria-label={sending ? 'Sending message' : `Send ${format} message`} title="Send (Enter). Shift+Enter for a new line." disabled={!valid || sending}><Send aria-hidden="true" /></button>
    </form>
  </div>;
}
