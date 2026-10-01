import { WhatsApp } from '@/components/provider-logo';
import { useEffect, useState } from 'react';
import { Plus, RefreshCw, ExternalLink } from 'lucide-react';
import { Badge, Button, Field, Modal } from '@/components/ui';
import { api } from '@/lib/api';
import type { WhatsAppAccount, WhatsAppConnection } from '@/types';
import './whatsapp-account-manager.css';

const emptyForm = { name: '', appId: '', appSecret: '', accessToken: '', wabaId: '', verifyToken: '' };

export function WhatsAppAccountManager({ open, onClose, onConnectionChanged, onEmbedded }: { open: boolean; onClose: () => void; onConnectionChanged: (connected: boolean) => void; onEmbedded: () => void }) {
  const [accounts, setAccounts] = useState<WhatsAppAccount[]>([]);
  const [numbers, setNumbers] = useState<WhatsAppConnection[]>([]);
  const [agentNames, setAgentNames] = useState<Record<string, string>>({});
  const [selectedId, setSelectedId] = useState('');
  const [available, setAvailable] = useState<{ id: string; displayPhoneNumber: string; verifiedName: string }[]>([]);
  const [phoneId, setPhoneId] = useState('');
  const [pin, setPin] = useState('');
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const selected = accounts.find((account) => account.id === selectedId);
  const close = () => { if (!busy) { setForm(emptyForm); setPin(''); setEditingId(null); setAdding(false); onClose(); } };
  useEffect(() => {
    if (!open) return;
    let active = true;
    void Promise.all([api.integrations.whatsapp.accounts(), api.integrations.whatsapp.status(), api.agents.list()]).then(([items, status, agents]) => {
      if (!active) return;
      setAccounts(items); setNumbers(status.connections ?? []);
      setAgentNames(Object.fromEntries(agents.map((agent) => [agent.id, agent.name])));
      setSelectedId((id) => items.some((item) => item.id === id) ? id : items[0]?.id ?? '');
      if (!items.length) setAdding(true);
    }).catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : 'Could not load accounts'); });
    return () => { active = false; };
  }, [open, revision]);
  useEffect(() => {
    if (!open || !selectedId) return;
    let active = true;
    void api.integrations.whatsapp.accountNumbers(selectedId).then((items) => { if (active) { setAvailable(items); setPhoneId(''); setPin(''); } })
      .catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : 'Could not load numbers'); });
    return () => { active = false; };
  }, [open, selectedId, revision]);
  const act = async (operation: () => Promise<void>) => {
    setBusy(true); setError(''); setNotice('');
    try { await operation(); setRevision((value) => value + 1); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not complete this step'); }
    finally { setBusy(false); setPin(''); }
  };
  const save = () => act(async () => {
    const account = editingId ? await api.integrations.whatsapp.updateAccount(editingId, form) : await api.integrations.whatsapp.addAccount(form);
    setAccounts((items) => [...items.filter((item) => item.id !== account.id), account]); setSelectedId(account.id); setAdding(false); setForm(emptyForm); setEditingId(null);
    setNotice('Account verified and saved. Activate its webhook, then register the numbers you want to use.');
  });
  return <Modal open={open} onClose={close} closeDisabled={busy} title="WhatsApp accounts and numbers" description="Connect your accounts, register multiple numbers, then choose a number for each bot in Deploy." size="lg" footer={<Button disabled={busy} onClick={close}>Done</Button>}>
    <div className="whatsapp-manager">
      <div className="whatsapp-manager__brand"><span className="whatsapp-logo"><WhatsApp /></span><div><strong>Your WhatsApp Business accounts</strong><small>Credentials are encrypted on the server.</small></div></div>
      {error ? <div role="alert" className="integration-error">{error}</div> : null}{notice ? <p role="status">{notice}</p> : null}
      <div className="whatsapp-manager__actions"><Button icon={Plus} disabled={busy} onClick={() => { setAdding(true); setEditingId(null); setForm(emptyForm); }}>Add account</Button><Button variant="secondary" disabled={busy} onClick={() => { setForm(emptyForm); setPin(''); onEmbedded(); }}>Use Facebook signup</Button></div>
      {adding ? <form className="whatsapp-form whatsapp-account-form" onSubmit={(event) => { event.preventDefault(); void save(); }}>
        <h3>{editingId ? 'Update account credentials' : 'Add your Meta account'}</h3><p>Use the app and system-user access token that can manage this WhatsApp Business Account. The token needs WhatsApp management and messaging permissions. Saved secrets are never displayed; enter replacement credentials when updating an account.</p>
        {([{ key: 'name', label: 'Account name', secret: false }, { key: 'appId', label: 'Meta App ID', secret: false }, { key: 'appSecret', label: 'Meta App secret', secret: true }, { key: 'wabaId', label: 'WhatsApp Business Account ID', secret: false }, { key: 'accessToken', label: 'System-user access token', secret: true }, { key: 'verifyToken', label: 'Webhook verification token', secret: true }] as const).map(({ key, label, secret }) => <Field key={key} label={label} htmlFor={`wa-account-${key}`} hint={key === 'verifyToken' ? 'Choose a secret of at least 32 characters. Meta uses it to verify the callback.' : undefined}><input id={`wa-account-${key}`} type={secret ? 'password' : 'text'} autoComplete="off" required minLength={key === 'verifyToken' ? 32 : undefined} value={form[key]} disabled={busy} onChange={(event) => setForm((value) => ({ ...value, [key]: event.target.value }))} /></Field>)}
        <div className="whatsapp-manager__actions"><Button type="submit" disabled={busy || Object.values(form).some((value) => !value.trim())}>{busy ? 'Verifying…' : 'Verify and save account'}</Button>{accounts.length ? <Button type="button" variant="secondary" disabled={busy} onClick={() => { setAdding(false); setForm(emptyForm); }}>Cancel</Button> : null}</div>
      </form> : null}
      {accounts.length ? <Field label="Business account" htmlFor="wa-account-select"><select id="wa-account-select" value={selectedId} disabled={busy} onChange={(event) => { setSelectedId(event.target.value); setAvailable([]); setPhoneId(''); setPin(''); }}>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name} — {account.wabaId}</option>)}</select></Field> : null}
      {selected ? <>
        <Button variant="secondary" disabled={busy} onClick={() => { setAdding(true); setEditingId(selected.id); setForm({ ...emptyForm, name: selected.name, appId: selected.appId, wabaId: selected.wabaId }); }}>Update account credentials</Button>
        <Badge tone={selected.status === 'connected' ? 'success' : 'warning'}>{selected.status === 'connected' ? 'Webhook connected' : 'Webhook setup needed'}</Badge>
        <Field label="Account webhook callback URL" htmlFor="wa-account-webhook" hint="This URL is generated for this account. Configure WhatsApp messages webhooks in your Meta app, then activate the callback here."><input id="wa-account-webhook" readOnly value={selected.webhookUrl} onFocus={(event) => event.target.select()} /></Field>
        {!selected.webhookUrl.startsWith('https://') ? <p role="alert">Your account is saved. Start ngrok to get a public HTTPS callback before deployment.</p> : null}
        <Button variant="secondary" icon={RefreshCw} disabled={busy || !selected.webhookUrl.startsWith('https://')} onClick={() => void act(async () => { await api.integrations.whatsapp.connectWebhook(selected.id); setNotice('Meta accepted the account webhook subscription.'); onConnectionChanged(numbers.length > 0); })}>Activate / refresh webhook</Button>
        <h3>Register another number</h3><p>Numbers come directly from this business account in Meta. Add and verify new phone numbers in WhatsApp Manager, then refresh this list.</p>
        <a href="https://business.facebook.com/wa/manage/phone-numbers/" target="_blank" rel="noreferrer">Open WhatsApp Manager <ExternalLink size={14} /></a>
        <Field label="WhatsApp number" htmlFor="wa-number-select"><select id="wa-number-select" value={phoneId} disabled={busy} onChange={(event) => setPhoneId(event.target.value)}><option value="">Choose a number to register</option>{available.filter((item) => !numbers.some((number) => number.phoneNumberId === item.id)).map((item) => <option key={item.id} value={item.id}>{item.displayPhoneNumber || item.id} — {item.verifiedName}</option>)}</select></Field>
        <Field label="Number registration PIN" htmlFor="wa-number-pin" hint="Enter the existing six-digit PIN, or choose one for a newly registered number."><input id="wa-number-pin" type="password" inputMode="numeric" autoComplete="off" value={pin} maxLength={6} disabled={busy} onChange={(event) => setPin(event.target.value.replace(/\D/g, '').slice(0, 6))} /></Field>
        <div className="whatsapp-manager__actions"><Button disabled={busy || !phoneId || !/^\d{6}$/.test(pin)} onClick={() => void act(async () => { await api.integrations.whatsapp.addNumber(selected.id, phoneId, pin); onConnectionChanged(true); setNotice('Number registered. Choose it for a bot in Deploy.'); })}>Register number</Button><Button variant="secondary" disabled={busy} onClick={() => setRevision((value) => value + 1)}>Refresh numbers</Button></div>
      </> : null}
      <h3>Workspace numbers</h3>{numbers.length ? <ul>{numbers.map((number) => <li key={number.id ?? number.phoneNumberId}><strong>{number.displayPhoneNumber || number.phoneNumberId}</strong> — {number.verifiedName} — {number.agentId ? `Bot: ${agentNames[number.agentId] ?? number.agentId}` : 'Not assigned'} ({number.status})</li>)}</ul> : <p>No numbers registered yet. Add an account above to get started.</p>}
      <a className="button button--primary" href="/deploy">Choose a number for a bot in Deploy</a>
    </div>
  </Modal>;
}
