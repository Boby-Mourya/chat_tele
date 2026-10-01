import { Phone } from 'lucide-react';
import { WhatsApp } from './provider-logo';
import type { Conversation } from '@/types';

export function WhatsAppContactDetails({ contact }: { contact: Conversation['whatsappContact'] }) {
  if (!contact) return null;
  return <section className="wa-contact" aria-label="WhatsApp contact details">
    <h4><WhatsApp size={20} /> WhatsApp contact</h4>
    <a className="wa-contact-phone" href={`tel:${contact.phoneNumber}`}><Phone size={16} aria-hidden="true" />{contact.phoneNumber}</a>
    <p>From incoming WhatsApp messages</p>
    <dl>
      <div><dt>WhatsApp profile name</dt><dd>{contact.profileName || 'Not shared'}</dd></div>
      <div><dt>WhatsApp ID</dt><dd>{contact.waId}</dd></div>
      {contact.lastMessageAt ? <div><dt>Last incoming message</dt><dd><time dateTime={contact.lastMessageAt}>{new Date(contact.lastMessageAt).toLocaleString()}</time></dd></div> : null}
      {contact.lastMessageType ? <div><dt>Message type</dt><dd className="capitalize">{contact.lastMessageType}</dd></div> : null}
    </dl>
  </section>;
}
