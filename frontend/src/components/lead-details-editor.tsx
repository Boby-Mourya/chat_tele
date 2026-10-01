import { useState, type FormEvent } from 'react';
import { Button, Modal } from '@/components/ui';
import { leadLayoutApi, type LeadLayout } from '@/lib/lead-layout-api';
import type { Lead } from '@/types';

export function LeadDetailsEditor({ lead, layout, onClose, onSaved }: { lead: Lead; layout: LeadLayout; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(lead.name ?? ''); const [email, setEmail] = useState(lead.email ?? '');
  const [phone, setPhone] = useState(lead.phone ?? ''); const [consent, setConsent] = useState(lead.consent);
  const custom = [...new Map(layout.columns.filter((c) => c.source.startsWith('fields.')).map((c) => [c.source, c])).values()];
  const [values, setValues] = useState<Record<string, unknown>>(() => Object.fromEntries(custom.map((c) => [c.source.slice(7), lead.fields[c.source.slice(7)] ?? ''])));
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function save(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try { await leadLayoutApi.edit(lead.id, { name: name.trim() || null, email: email.trim() || null, phone: phone.trim() || null, consent, fields: values }); onSaved(); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not save lead'); } finally { setBusy(false); }
  }
  return <Modal open title="Edit lead details" description="Update contact details and your custom fields. Saving requests an update through your configured CRM sync rules." onClose={onClose} closeDisabled={busy}>
    <form className="lead-layout-editor" onSubmit={(e) => void save(e)}>
      <label>Name<input value={name} maxLength={160} onChange={(e) => setName(e.target.value)} /></label>
      <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <label>Phone / WhatsApp<input type="tel" value={phone} maxLength={80} onChange={(e) => setPhone(e.target.value)} /></label>
      <label className="lead-checkbox"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> Consent recorded</label>
      {custom.map((c) => { const key = c.source.slice(7); return <label key={key}>{c.label}{c.required ? ' *' : ''}{c.type === 'boolean' ? <select required={c.required} value={values[key] === true ? 'true' : values[key] === false ? 'false' : String(values[key] ?? '')} onChange={(e) => setValues({ ...values, [key]: e.target.value === '' ? null : e.target.value === 'true' })}><option value="">Not provided</option><option value="true">Yes</option><option value="false">No</option></select> : <input required={c.required} type={c.type === 'number' ? 'number' : c.type === 'date' ? 'date' : 'text'} step="any" maxLength={2000} value={String(values[key] ?? '')} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />}</label>; })}
      {error && <p role="alert" className="lead-layout-error">{error}</p>}
      <div className="lead-layout-toolbar"><Button variant="secondary" type="button" disabled={busy} onClick={onClose}>Cancel</Button><Button type="submit" disabled={busy}>{busy ? 'Saving...' : 'Save lead'}</Button></div>
    </form>
  </Modal>;
}
