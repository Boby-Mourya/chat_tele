import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui';
import { ConversationAssignmentControl } from '@/features/workspace/conversations/ConversationAssignmentControl';
import { conversationApi } from '@/lib/conversation-api';
import type { Conversation } from '@/types';

const fields = [
  ['phone', 'Phone / WhatsApp'], ['ipAddress', 'IP address'], ['location', 'Location (approximate)'],
  ['timezone', 'Time zone'], ['language', 'Language'], ['pageSlug', 'Page slug'], ['referrer', 'Referrer'],
  ['utmSource', 'UTM source'], ['utmMedium', 'UTM medium'], ['utmCampaign', 'UTM campaign'],
  ['utmTerm', 'UTM term'], ['utmContent', 'UTM content'],
] as const;

export function VisitorDetailsEditor({ conversation, onSaved }: { conversation: Conversation; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(conversation.visitorName);
  const [email, setEmail] = useState(conversation.visitorEmail ?? '');
  const [pageUrl, setPageUrl] = useState(conversation.pageUrl ?? '');
  const [details, setDetails] = useState<Record<string, string | null>>(conversation.visitorDetails ?? {});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  function edit() {
    setName(conversation.visitorName); setEmail(conversation.visitorEmail ?? '');
    setPageUrl(conversation.pageUrl ?? ''); setDetails(conversation.visitorDetails ?? {});
    setError(''); setSaved(false); setEditing(true);
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await conversationApi.updateVisitor(conversation.id, { visitorName: name.trim(), visitorEmail: email.trim() || null,
        pageUrl: pageUrl.trim() || null, visitorDetails: Object.fromEntries(Object.entries(details).map(([key, value]) => [key, value?.trim() || null])) });
      setEditing(false); setSaved(true); onSaved();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save'); }
    finally { setBusy(false); }
  }
  return <>
    <ConversationAssignmentControl conversationId={conversation.id} />
    <section className="visitor-details-editor">
      <strong>Contact & website details</strong>
      {saved && <p role="status">Visitor details saved</p>}
      {editing ? <form onSubmit={save}>
        <label>Name<input required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
        <label>Page URL<input type="url" maxLength={2048} value={pageUrl} onChange={(event) => setPageUrl(event.target.value)} /></label>
        {fields.map(([key, label]) => <label key={key}>{label}<input maxLength={key === 'phone' ? 80 : key === 'ipAddress' ? 45 : key === 'referrer' ? 2048 : key.startsWith('utm') && key !== 'utmContent' ? 240 : 500} value={details[key] ?? ''} onChange={(event) => setDetails({ ...details, [key]: event.target.value })} /></label>)}
        {error && <p role="alert">{error}</p>}
        <Button type="submit" size="sm" disabled={busy}>{busy ? 'Saving...' : 'Save details'}</Button>
        <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => setEditing(false)}>Cancel</Button>
      </form> : <>
        <Button size="sm" variant="secondary" onClick={edit}>Edit visitor details</Button>
        <dl><div><dt>Page URL</dt><dd>{conversation.pageUrl || 'Not captured'}</dd></div>
        {fields.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{conversation.visitorDetails?.[key] || 'Not provided'}</dd></div>)}</dl>
      </>}
    </section>
  </>;
}
