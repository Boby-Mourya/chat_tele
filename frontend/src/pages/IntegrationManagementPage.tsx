import { ArrowLeft } from 'lucide-react';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth, useWorkspace } from '@/components/providers';
import { Button, Card } from '@/components/ui';
import { CRMManagementPanel } from '@/components/crm-management-panel';
import { CRMOperationalHealthPanel } from '@/components/crm-operational-health-panel';
import { CRMHealthHistoryPanel } from '@/components/crm-health-history-panel';
import { CRMDeadLetterPanel } from '@/components/crm-dead-letter-panel';
import { ChannelOperationalHealthPanel } from '@/components/channel-operational-health-panel';
import { leadCrmApi } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';

export function IntegrationManagementPage() {
  const { activeWorkspace } = useWorkspace();
  return <Management key={activeWorkspace?.id ?? 'workspace'} />;
}
function Management() {
  const { session } = useAuth();
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState('Mapping & routing');
  const result = useApi(() => leadCrmApi.connections());
  const connections = (result.data ?? []).filter(value => value.status !== 'disabled');
  const selected = params.get('connection');
  const filtered = selected ? connections.filter(value => value.id === selected) : connections;
  const canManage = session?.user.role === 'owner' || session?.user.role === 'admin';
  return <div className="page integration-catalog">
    <Link className="catalog-back" to="/integrations"><ArrowLeft size={18} />All integrations</Link>
    <div className="catalog-heading"><div><h1>Manage connections</h1><p>Review CRM mapping, lead routing and connection health.</p></div></div>
    <Card className="catalog-toolbar"><div className="catalog-filters" role="group" aria-label="Connection management">{['Mapping & routing', 'CRM health', 'Delivery issues', 'Channel health'].map(value => <button key={value} aria-pressed={tab === value} className={tab === value ? 'is-active' : ''} onClick={() => setTab(value)}>{value}</button>)}</div></Card>
    {result.error && <div role="alert" className="catalog-notice catalog-notice--error">{result.error}<Button onClick={result.reload}>Retry</Button></div>}
    {result.loading ? <p role="status">Loading connections…</p> : tab !== 'Channel health' && !connections.length ? <Card className="catalog-empty"><h2>Connect your CRM first</h2><p>Choose a CRM from the catalogue to get started.</p><Link to="/integrations">Browse integrations</Link></Card> : <>
      {tab !== 'Channel health' && selected && <div className="catalog-notice">Viewing {filtered[0]?.name ?? 'an unavailable connection'}. <Button variant="ghost" onClick={() => setParams({})}>Show all connections</Button></div>}
      {tab === 'Mapping & routing' && <CRMManagementPanel key={selected ?? 'all'} connections={filtered} canManage={canManage} onConnectionsChanged={result.reload} />}
      {tab === 'CRM health' && <><CRMOperationalHealthPanel /><CRMHealthHistoryPanel connections={filtered} canManage={canManage} /></>}
      {tab === 'Delivery issues' && <CRMDeadLetterPanel connections={filtered} />}
      {tab === 'Channel health' && <ChannelOperationalHealthPanel />}
    </>}
  </div>;
}
