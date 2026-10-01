import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { apiErrorMessage } from '@/lib/api-error-message';
import { useWorkspace } from '@/components/providers';
import { Button, Field, Badge } from '@/components/ui';
import type { WhatsAppConnection } from '@/types';

function usable(number?: WhatsAppConnection): boolean {
  return Boolean(number?.id && number.status === 'connected' && (!number.tokenExpiresAt || Date.parse(number.tokenExpiresAt) > Date.now()));
}

export function WhatsAppNumberDeployment({ agentId, onNumberChanged, onNumbersLoaded }: {
  agentId: string;
  onNumberChanged?: (number: string | null, previousAgentId?: string | null) => void;
  onNumbersLoaded?: (numbers: WhatsAppConnection[]) => void;
}) {
  const { activeWorkspace } = useWorkspace();
  const [numbers, setNumbers] = useState<WhatsAppConnection[]>([]);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const current = numbers.find((number) => number.agentId === agentId);
  const next = numbers.find((number) => number.id === selected);

  useEffect(() => {
    let active = true;
    void api.integrations.whatsapp.status().then((status) => {
      if (!active) return;
      const items = status.connections ?? [];
      setNumbers(items);
      setSelected(items.find((number) => number.agentId === agentId)?.id ?? '');
      setError('');
      onNumbersLoaded?.(items);
    }).catch((failure: unknown) => {
      if (active) setError(apiErrorMessage(failure, 'Could not load numbers'));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [agentId, activeWorkspace?.id, revision, onNumbersLoaded]);

  const refresh = () => { setLoading(true); setError(''); setRevision((value) => value + 1); };
  const assign = async () => {
    const connectionId = selected || current?.id;
    if (!connectionId || busy || loading || (selected && !usable(next))) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await api.integrations.whatsapp.assignNumber(connectionId, selected ? agentId : null);
      const updated = numbers.map((number) => number.id === saved.id ? saved : number.agentId === agentId ? { ...number, agentId: null } : number);
      setNumbers(updated);
      onNumberChanged?.(saved.agentId === agentId ? saved.displayPhoneNumber || null : null, next?.agentId);
      onNumbersLoaded?.(updated);
      setNotice(selected ? 'Number assigned. Activate this bot when you are ready for it to reply.' : 'Number released. You can assign it to another bot.');
    } catch (failure) { setError(apiErrorMessage(failure, 'Could not update deployment')); }
    finally { setBusy(false); }
  };

  return <div className="whatsapp-manager">
    <h3>WhatsApp number for this bot</h3>
    <Badge tone={usable(current) ? 'success' : 'neutral'}>{loading ? 'Loading numbers…' : current ? current.displayPhoneNumber || 'Number assigned' : 'No number assigned'}</Badge>
    {current && !usable(current) && !loading ? <p role="status">This number needs reconnection or webhook setup in Integrations before the bot can reply.</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    <Field label="Connected WhatsApp number" htmlFor="deploy-whatsapp-number" hint="Assign a number to a draft or active bot. One number routes to one bot.">
      <select id="deploy-whatsapp-number" value={selected} disabled={busy || loading} onChange={(event) => setSelected(event.target.value)}>
        <option value="">No number assigned</option>
        {numbers.map((number) => <option key={number.id ?? number.phoneNumberId} value={number.id} disabled={!usable(number)}>{number.displayPhoneNumber || 'Number display unavailable'} — {number.verifiedName}{number.agentId === agentId ? ' (this bot)' : number.agentId ? ' (assigned to another bot)' : ' (available)'}{!usable(number) ? ' — setup required' : ''}</option>)}
      </select>
    </Field>
    {next?.agentId && next.agentId !== agentId ? <p>This will move the selected number from its current bot to this bot.</p> : null}
    {selected !== (current?.id ?? '') ? <p>Changing deployment closes existing WhatsApp threads and cancels pending replies on the affected numbers. New messages use the new assignment.</p> : null}
    <div className="whatsapp-manager__actions">
      <Button disabled={busy || loading || selected === (current?.id ?? '') || Boolean(selected && !usable(next))} onClick={() => void assign()}>{busy ? 'Updating deployment…' : 'Apply number assignment'}</Button>
      <Button variant="secondary" disabled={busy || loading} onClick={refresh}>{error ? 'Retry loading numbers' : 'Refresh numbers'}</Button>
      <a className="button button--secondary" href="/integrations">Add accounts or numbers</a>
    </div>
  </div>;
}
