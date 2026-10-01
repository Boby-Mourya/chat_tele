import { useState } from 'react';
import { Badge, Button, Card, Field } from '@/components/ui';
import { useToast } from '@/components/providers';
import {
  workspaceSettingsApi,
  type DomainRecord,
  type WorkspaceSettingsBundle,
} from '@/features/workspace/settings/workspaceSettings.api';

export function BrandDomainsSettings({ bundle, onChange }: { bundle: WorkspaceSettingsBundle; onChange: (bundle: WorkspaceSettingsBundle) => void }) {
  const { pushToast } = useToast();
  const [hostname, setHostname] = useState('');
  const [busyId, setBusyId] = useState('');

  function apply(next: DomainRecord) {
    onChange({ ...bundle, domains: { domains: bundle.domains.domains.map((item) => item.id === next.id ? next : item) } });
  }
  async function add() {
    if (!hostname.trim()) return;
    setBusyId('new');
    try {
      const value = await workspaceSettingsApi.createDomain(hostname);
      onChange({ ...bundle, domains: { domains: [...bundle.domains.domains, value] } });
      setHostname('');
      pushToast('Domain added. Publish the TXT record before verification.');
    } catch (reason) { pushToast(reason instanceof Error ? reason.message : 'Domain could not be added', 'error'); }
    finally { setBusyId(''); }
  }
  async function act(domain: DomainRecord, action: 'verify' | 'activate' | 'disable') {
    setBusyId(domain.id);
    try {
      const value = action === 'verify' ? await workspaceSettingsApi.verifyDomain(domain.id)
        : action === 'activate' ? await workspaceSettingsApi.activateDomain(domain.id)
        : await workspaceSettingsApi.disableDomain(domain.id);
      apply(value);
      pushToast(action === 'verify' ? `DNS state: ${value.status}` : action === 'activate' ? `Domain state: ${value.status}` : 'Domain disabled');
    } catch (reason) { pushToast(reason instanceof Error ? reason.message : 'Domain update failed', 'error'); }
    finally { setBusyId(''); }
  }

  return <Card className="workspace-panel"><div className="workspace-panel__body">
    <h3>Custom domains</h3><p>Activation is server-controlled: TXT ownership verification must succeed first, then HTTPS/TLS readiness must pass before a hostname becomes active.</p>
    <div className="two-fields"><Field label="Portal hostname"><input value={hostname} placeholder="portal.customer.com" onChange={(event) => setHostname(event.target.value)} /></Field><div className="workspace-panel__actions"><Button disabled={busyId === 'new' || !hostname.trim()} onClick={() => void add()}>Add domain</Button></div></div>
    {bundle.domains.domains.length === 0 ? <p>No custom domains configured.</p> : null}
    {bundle.domains.domains.map((domain) => <div className="setup-resource" key={domain.id}>
      <div className="page-heading page-heading--split"><div><strong>{domain.hostname}</strong><p>Created {new Date(domain.createdAt).toLocaleString()}</p></div><Badge tone={domain.status === 'active' ? 'success' : domain.status === 'failed' ? 'warning' : 'neutral'}>{domain.status.replaceAll('_', ' ')}</Badge></div>
      <p>TXT record</p><code>{domain.verificationName}</code><p>Value</p><code>{domain.verificationValue}</code>
      {domain.failureReason ? <p role="status">{domain.failureReason}</p> : null}
      {domain.status === 'failed' ? <p>Verify DNS ownership again before checking TLS.</p> : null}
      <div className="workspace-panel__actions">
        <Button variant="secondary" disabled={busyId === domain.id || ['active', 'disabled'].includes(domain.status)} onClick={() => void act(domain, 'verify')}>Check DNS ownership</Button>
        <Button variant="secondary" disabled={busyId === domain.id || !['verified', 'certificate_pending'].includes(domain.status)} onClick={() => void act(domain, 'activate')}>Check TLS & activate</Button>
        <Button variant="danger" disabled={busyId === domain.id || domain.status === 'disabled'} onClick={() => { if (window.confirm(`Disable ${domain.hostname}? Branded login will stop resolving on this hostname.`)) void act(domain, 'disable'); }}>Disable</Button>
      </div>
    </div>)}
  </div></Card>;
}
