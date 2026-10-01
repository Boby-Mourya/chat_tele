import { Check, Copy, KeyRound, LockKeyhole, Plus, Trash2 } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useToast } from '@/components/providers';
import { Button, Card, Field } from '@/components/ui';
import {
  WORKSPACE_API_KEY_SCOPES,
  workspaceAPIKeyApi,
  type WorkspaceAPIKey,
  type WorkspaceAPIKeyScope,
} from '@/lib/workspace-api-keys';
import type { WorkspaceSettings } from '@/lib/workspace-api';

export function WorkspaceAPIKeysPanel({ workspace }: { workspace: WorkspaceSettings }) {
  const { pushToast } = useToast();
  const [keys, setKeys] = useState<WorkspaceAPIKey[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [newSecret, setNewSecret] = useState('');
  const [keyName, setKeyName] = useState('Production');
  const [scopes, setScopes] = useState<WorkspaceAPIKeyScope[]>(['workspace:read', 'conversations:read', 'agents:read']);
  const permissions = workspace.permissions;
  const canView = permissions === undefined || permissions.includes('*') || permissions.includes('api_keys.view');
  const canManage = permissions === undefined || permissions.includes('*') || permissions.includes('api_keys.manage');

  useEffect(() => {
    if (!canView) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setLoading(true);
      void workspaceAPIKeyApi.list()
        .then((values) => { if (active) setKeys(values); })
        .catch((error) => {
          if (active) pushToast(error instanceof Error ? error.message : 'API keys could not be loaded', 'error');
        })
        .finally(() => { if (active) setLoading(false); });
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [canView, pushToast, workspace.id]);

  function toggleScope(scope: WorkspaceAPIKeyScope) {
    setScopes((current) => current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope]);
  }

  async function createKey() {
    setCreating(true);
    try {
      const created = await workspaceAPIKeyApi.create(keyName || `Production ${keys.length + 1}`, scopes);
      const { secret, ...record } = created;
      setKeys((current) => [record, ...current.filter((item) => item.id !== record.id)]);
      setNewSecret(secret);
      pushToast('Scoped API key created');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'API key could not be created', 'error');
    } finally {
      setCreating(false);
    }
  }

  async function revokeKey(id: string) {
    setRevokingId(id);
    try {
      await workspaceAPIKeyApi.revoke(id);
      setKeys((current) => current.filter((item) => item.id !== id));
      pushToast('API key revoked');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'API key could not be revoked', 'error');
    } finally {
      setRevokingId(null);
    }
  }

  return <Card className="workspace-panel">
    <PanelHeading title="API keys" description="Create and revoke workspace-scoped credentials with explicit least-privilege scopes." />
    {!canView ? <div className="workspace-empty-row"><KeyRound /><span><strong>API key access is restricted</strong><small>Ask a workspace administrator to manage server credentials.</small></span></div> : null}
    {canManage ? <div className="setup-resource"><Field label="Key name"><input value={keyName} onChange={(event) => setKeyName(event.target.value)} /></Field><strong>Scopes</strong><div className="workspace-agent-scope__list">{WORKSPACE_API_KEY_SCOPES.map((scope) => <label key={scope}><input type="checkbox" checked={scopes.includes(scope)} onChange={() => toggleScope(scope)} /><span>{scope}</span></label>)}</div><Button icon={Plus} onClick={() => void createKey()} disabled={creating || scopes.length === 0}>{creating ? 'Creating…' : 'Create secret key'}</Button></div> : null}
    {newSecret ? <div className="workspace-secret"><LockKeyhole /><div><strong>Copy this key now</strong><small>For security, the full secret is shown only once and is not stored in plaintext.</small><code>{newSecret}</code></div><button type="button" className="icon-button" aria-label="Copy new API key" onClick={() => void navigator.clipboard.writeText(newSecret).then(() => pushToast('Secret key copied'))}><Copy /></button><button type="button" className="icon-button" aria-label="Hide new API key" onClick={() => setNewSecret('')}><Check /></button></div> : null}
    {canView ? <div className="workspace-key-list">
      {loading ? <div className="workspace-empty-row"><KeyRound /><span><strong>Loading API keys…</strong><small>Reading active credentials for this workspace.</small></span></div> : null}
      {!loading && keys.length ? keys.map((key) => <div key={key.id}><span><strong>{key.name}</strong><small>{key.scopes.join(', ')} · Created {new Date(key.createdAt).toLocaleDateString()}{key.lastUsedAt ? ` · Last used ${new Date(key.lastUsedAt).toLocaleDateString()}` : ''}</small></span><code>{key.prefix}••••</code>{canManage ? <button type="button" className="icon-button danger-hover" onClick={() => { if (window.confirm(`Revoke ${key.name}? Existing clients using it will stop working.`)) void revokeKey(key.id); }} disabled={revokingId === key.id} aria-label={`Revoke ${key.name}`}><Trash2 /></button> : null}</div>) : null}
      {!loading && keys.length === 0 ? <div className="workspace-empty-row"><KeyRound /><span><strong>No API keys yet</strong><small>Create a scoped key when you are ready to connect your backend.</small></span></div> : null}
    </div> : null}
  </Card>;
}

function PanelHeading({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="workspace-panel__heading"><span><KeyRound /></span><div><h3>{title}</h3><p>{description}</p></div>{action}</div>;
}
