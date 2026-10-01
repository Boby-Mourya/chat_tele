import { ArrowRight, Check, RefreshCw, Search, Settings2 } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth, useWorkspace } from '@/components/providers';
import { Badge, Button, Card } from '@/components/ui';
import { IntegrationSetupModal } from '@/components/integration-setup-modal';
import { WhatsAppIntegrationModal } from '@/components/whatsapp-integration-modal';
import { api } from '@/lib/api';
import { crmOneClickApi } from '@/lib/crm-one-click-api';
import { leadCrmApi } from '@/lib/lead-crm-api';
import { integrationCatalog, integrationCategories, type CatalogIntegration, type IntegrationCategory } from '@/lib/integration-catalog';
import { useApi } from '@/lib/use-api';

export function IntegrationsHubPage() {
  const { activeWorkspace } = useWorkspace();
  return <IntegrationCatalogPage key={activeWorkspace?.id ?? 'workspace'} />;
}

function IntegrationCatalogPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<IntegrationCategory>('All integrations');
  const [selected, setSelected] = useState<CatalogIntegration | null>(() => params.get('provider') === 'telegram' ? integrationCatalog.find(item => item.id === 'telegram') ?? null : null);
  const [whatsAppOpen, setWhatsAppOpen] = useState(false);
  const canManage = session?.user.role === 'owner' || session?.user.role === 'admin';
  const providers = useApi(() => crmOneClickApi.providers());
  const crm = useApi(() => leadCrmApi.connections());
  const channels = useApi(() => leadCrmApi.channelConnections());
  const integrations = useApi(() => api.integrations.list());
  const refresh = () => { providers.reload(); crm.reload(); channels.reload(); integrations.reload(); };
  const loading = providers.loading || crm.loading || channels.loading || integrations.loading;
  const error = providers.error || crm.error || channels.error || integrations.error;
  const items = integrationCatalog.filter(item => (category === 'All integrations' || item.category === category) && `${item.name} ${item.description}`.toLowerCase().includes(search.trim().toLowerCase()));
  const connectionFor = (item: CatalogIntegration) => (item.category === 'Channels' ? channels.data : crm.data)?.find(connection => connection.provider === item.id && connection.status !== 'disabled');
  const statusFor = (item: CatalogIntegration) => {
    if (item.id === 'widget') return 'available';
    if (item.id === 'whatsapp') return integrations.data?.find(value => value.id === 'whatsapp')?.connected ? 'healthy' : undefined;
    const connection = connectionFor(item);
    if (connection?.status === 'healthy' && item.category === 'Channels' && item.id !== 'telegram' && !('last_event_at' in connection && connection.last_event_at)) return 'webhook_pending';
    return connection?.status;
  };
  const open = (item: CatalogIntegration) => {
    if (item.id === 'widget') navigate('/deploy');
    else if (item.id === 'whatsapp') setWhatsAppOpen(true);
    else setSelected(item);
  };

  return <div className="page integration-catalog">
    <div className="catalog-heading"><div><h1>Integrations</h1><p>Connect your CRM and customer channels in one place.</p></div><Link className="button button--secondary button--md" to="/integrations/advanced"><Settings2 size={18} />Manage connections</Link></div>
    <Card className="catalog-toolbar"><div className="catalog-filters" role="group" aria-label="Integration categories">{integrationCategories.map(value => <button type="button" key={value} aria-pressed={category === value} className={category === value ? 'is-active' : ''} onClick={() => setCategory(value)}>{value}</button>)}</div><label className="catalog-search"><Search size={19} /><input aria-label="Search integrations" placeholder="Search integrations" value={search} onChange={event => setSearch(event.target.value)} /></label><Button variant="ghost" size="icon" icon={RefreshCw} aria-label="Refresh connection status" disabled={loading} onClick={refresh} /></Card>
    {error && <div className="catalog-notice catalog-notice--error" role="alert">Connection information could not be loaded: {error} <Button variant="ghost" onClick={refresh}>Try again</Button></div>}
    {!canManage && <p className="catalog-notice">An owner or administrator can connect platforms for this workspace.</p>}
    {loading && <p role="status" className="catalog-loading">Refreshing connection status…</p>}
    {(['Connected', 'CRM', 'Channels', 'Developer'] as const).map(group => {
      const groupItems = items.filter(item => group === 'Connected' ? statusFor(item) === 'healthy' : item.category === group && statusFor(item) !== 'healthy');
      if (!groupItems.length) return null;
      return <section className="catalog-group" key={group} aria-label={`${group} integrations`}><div className="catalog-section-heading"><div><h2>{group === 'Connected' ? 'Connected apps' : group === 'CRM' ? 'Customer relationship management' : group === 'Channels' ? 'Customer channels' : 'Developer tools'}</h2><p>{group === 'Connected' ? 'Your connected platforms, ready to manage.' : group === 'CRM' ? 'Start with your CRM. Connect an account, authorize access and review lead sync.' : group === 'Channels' ? 'Meet your customers where they already are.' : 'Build a connection for your own platform.'}</p></div><span>{groupItems.length} {groupItems.length === 1 ? 'integration' : 'integrations'}</span></div><div className="catalog-grid">{groupItems.map(item => {
        const Icon = item.icon;
        const status = statusFor(item);
        const connected = status === 'healthy';
        const hasConnection = !!connectionFor(item) || connected;
        return <Card className="catalog-card" key={item.id}><div className="catalog-card__top"><span className={`catalog-icon catalog-icon--${item.accent}`}><Icon size={26} /></span><div><h3>{item.name}</h3>{connected ? <Badge tone="success"><Check size={14} />Connected</Badge> : status === 'webhook_pending' ? <Badge tone="warning">Finish webhook setup</Badge> : status && status !== 'available' ? <Badge tone="warning">{status === 'connecting' ? 'Authorization pending' : 'Needs attention'}</Badge> : <span className="catalog-card__category">{item.category}</span>}</div></div><p>{item.description}</p><div className="catalog-card__footer"><Button variant={hasConnection || item.id === 'widget' ? 'secondary' : 'primary'} disabled={loading || !!error || (!canManage && item.id !== 'widget')} aria-label={`${hasConnection || item.id === 'widget' ? 'Manage' : 'Connect'} ${item.name}`} onClick={() => open(item)}>{hasConnection || item.id === 'widget' ? 'Manage' : 'Connect'}<span className="sr-only"> {item.name}</span></Button>{item.id === 'zoho' && !hasConnection && <span className="catalog-recommended">Recommended</span>}{connected && item.category === 'CRM' && <Link to={`/integrations/advanced?connection=${connectionFor(item)?.id ?? ''}`} aria-label={`Manage ${item.name} mapping`}><ArrowRight size={18} /></Link>}</div></Card>;
      })}</div></section>;
    })}
    {!items.length && <Card className="catalog-empty"><Search size={28} /><h2>No integrations found</h2><p>Try another name or category.</p><Button variant="secondary" onClick={() => { setSearch(''); setCategory('All integrations'); }}>Clear filters</Button></Card>}
    {selected && <IntegrationSetupModal item={selected} provider={providers.data?.find(value => value.id === selected.id)} crmConnections={crm.data ?? []} channelConnections={channels.data ?? []} canManage={canManage} onClose={() => setSelected(null)} onChanged={refresh} />}
    <WhatsAppIntegrationModal open={whatsAppOpen} onClose={() => setWhatsAppOpen(false)} onConnectionChanged={refresh} />
  </div>;
}
