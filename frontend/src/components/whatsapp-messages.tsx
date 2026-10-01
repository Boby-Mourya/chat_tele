import { Check, CheckCheck, CircleAlert, Clock3 } from 'lucide-react';
import { Fragment } from 'react';
import type { ChatMessage } from '@/types';

export function WhatsAppDeliveryStatus({ status }: { status: ChatMessage['deliveryStatus'] }) {
  if (!status || status === 'unknown') return null;
  const labels = { pending: 'Waiting to send', sent: 'Sent to WhatsApp', delivered: 'Delivered', read: 'Read', failed: 'Delivery failed' };
  const Icon = status === 'pending' ? Clock3 : status === 'failed' ? CircleAlert : status === 'sent' ? Check : CheckCheck;
  return <span className={`wa-delivery wa-delivery--${status}`} role="img" aria-label={labels[status]} title={labels[status]}><Icon aria-hidden="true" />{status === 'failed' ? <span>Not sent</span> : null}</span>;
}

function dayLabel(date: Date) {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return 'Today';
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' });
}

export function WhatsAppMessages({ messages, visitorName, agentName }: { messages: ChatMessage[]; visitorName: string; agentName: string }) {
  return <div className="wa-messages">{messages.map((message, index) => {
    const date = new Date(message.createdAt);
    const previous = messages[index - 1];
    const newDay = !previous || new Date(previous.createdAt).toDateString() !== date.toDateString();
    const outgoing = message.role === 'agent' || message.role === 'assistant';
    return <Fragment key={message.id}>
      {newDay ? <div className="wa-day"><span>{dayLabel(date)}</span></div> : null}
      {message.role === 'system' ? <div className="wa-system">{message.content}</div> : message.content ? <article className={`wa-message wa-message--${outgoing ? 'outgoing' : 'incoming'}`} aria-label={`${outgoing ? message.role === 'agent' ? 'You' : agentName : visitorName}: ${message.content}`}>
        <div className="wa-bubble">
          {outgoing ? <span className="wa-sender">{message.role === 'agent' ? 'You' : `${agentName} · AI`}</span> : null}
          <div className="wa-message-text" dir="auto">{message.messageFormat?.type === 'table' ? message.messageFormat.body ?? message.content : message.content}</div>
          {message.messageFormat?.type === 'buttons' ? <div className="wa-message-buttons">{message.messageFormat.buttons?.map(button => <span key={button.id}>{button.title}</span>)}</div> : null}
          {message.messageFormat?.type === 'table' && message.messageFormat.table ? <div className="wa-message-table-wrap"><table className="wa-message-table"><thead><tr>{message.messageFormat.table.columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{message.messageFormat.table.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div> : null}
          {message.messageFormat && !['text', 'buttons', 'table'].includes(message.messageFormat.type) ? <RichMessageAttachment format={message.messageFormat} /> : null}
          <div className="wa-message-meta"><time dateTime={message.createdAt} title={date.toLocaleString()}>{date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</time>{outgoing ? <WhatsAppDeliveryStatus status={message.deliveryStatus} /> : null}</div>
        </div>
        {message.citations?.map((citation) => <span className="wa-citation" key={citation.title}>{citation.title}</span>)}
      </article> : null}
    </Fragment>;
  })}</div>;
}

function RichMessageAttachment({ format }: { format: NonNullable<ChatMessage['messageFormat']> }) {
  const config = format.config ?? {}; const url = String(config.url ?? '');
  if (format.type === 'image' && url) return <img className="wa-rich-media" src={url} alt="Sent WhatsApp media" />;
  if (format.type === 'video' && url) return <video className="wa-rich-media" src={url} controls preload="metadata" />;
  if (format.type === 'audio' && url) return <audio className="wa-rich-audio" src={url} controls preload="metadata" />;
  const labels: Record<string, string> = { list: 'List menu', document: `Document · ${String(config.filename ?? 'file')}`, sticker: 'Sticker', location: `Location · ${String(config.name ?? '')}`, contact: 'Shared contact', cta_url: 'Website button', flow: 'WhatsApp Flow', product: 'Product', product_list: 'Product list', catalog: 'Catalog' };
  return <div className="wa-rich-attachment">{labels[format.type] ?? format.type}</div>;
}
