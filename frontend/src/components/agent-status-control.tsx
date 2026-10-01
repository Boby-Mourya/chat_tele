import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useToast } from '@/components/providers';
import { api } from '@/lib/api';
import type { Agent } from '@/types';
import './agent-status-control.css';

export function AgentStatusControl({ agent, onSaved, showEnrollmentLink = true, compact = false, onError }: {
  agent: Agent;
  onSaved: () => void;
  showEnrollmentLink?: boolean;
  compact?: boolean;
  onError?: (message: string) => void;
}) {
  const [status, setStatus] = useState(agent.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const { pushToast } = useToast();
  useEffect(() => { setStatus(agent.status); }, [agent.id, agent.status]);
  const active = status === 'active';
  const change = async (active: boolean) => {
    if (busy || status === 'training') return;
    setBusy(true); setError(''); onError?.('');
    try {
      const saved = await api.agents.update(agent.id, { status: active ? 'active' : 'draft' });
      setStatus(saved.status);
      pushToast(active ? `${agent.name} is active` : `${agent.name} is now a draft. Replies are paused.`);
      onSaved();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Could not update bot status';
      setError(message); onError?.(message);
    }
    finally { setBusy(false); }
  };
  const toggle = <button type="button" role="switch" aria-checked={active} aria-label={`${agent.name}: Active`}
    aria-busy={busy} disabled={busy || status === 'training'} onClick={() => void change(!active)}
    className={`agent-activation-switch ${active ? 'is-active' : ''}`}
    title={status === 'training' ? 'Wait for training to finish' : active ? 'Switch off to pause replies and save as draft' : 'Switch on to activate this bot'}>
    <span className="agent-activation-switch__track" aria-hidden="true"><span /></span>
    <span>{busy ? 'Saving...' : status === 'training' ? 'Training' : active ? 'Active' : 'Inactive'}</span>
  </button>;
  return <div className={`agent-status-control${compact ? ' agent-status-control--compact' : ''}`}>
    {compact ? toggle : <div className="agent-status-control__row"><div><strong>Bot status</strong><small>{busy ? 'Updating status...' : active ? 'Replies are enabled. Switch off to save as a draft.' : 'Draft: replies are paused. Switch on when ready.'}</small></div>{toggle}</div>}
    {error && !onError ? <div className="form-error" role="alert">{error}</div> : null}
    {showEnrollmentLink && agent.purpose === 'education' ? <Link className="button button--secondary button--sm" to={`/education/enrollments?agentId=${agent.id}`}>Manage enrollments</Link> : null}
  </div>;
}
