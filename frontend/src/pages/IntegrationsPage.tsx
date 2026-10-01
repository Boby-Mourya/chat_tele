import { ProviderLogo } from '@/components/provider-logo';
import { Facebook, Instagram } from '@/components/social-icons';
import { BookOpen, Check, CircleAlert, Code2, Database, Hash, MessageCircle, PlugZap, RefreshCw, Search, Terminal, Users, Zap } from 'lucide-react';
import { useMemo, useState } from 'react';
import { ChannelHealthHistoryPanel } from '@/components/channel-health-history-panel';
import { ChannelOperationalHealthPanel } from '@/components/channel-operational-health-panel';
import { CRMDeadLetterPanel } from '@/components/crm-dead-letter-panel';
import { CRMHealthHistoryPanel } from '@/components/crm-health-history-panel';
import { CRMManagementPanel } from '@/components/crm-management-panel';
import { CRMOperationalHealthPanel } from '@/components/crm-operational-health-panel';
import { CRMWebhookEventsPanel } from '@/components/crm-webhook-events-panel';
import { useAuth, useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, PageLoader } from '@/components/ui';
import { WhatsAppIntegrationModal } from '@/components/whatsapp-integration-modal';
import { api } from '@/lib/api';
import { leadCrmApi, type CRMProviderId } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';
import type { Integration } from '@/types';

const iconMap = { code: Code2, hash: Hash, message: MessageCircle, zap: Zap, book: BookOpen, terminal: Terminal, users: Users, facebook: Facebook, instagram: Instagram };
const oauthProviders = new Set<CRMProviderId>(['zoho', 'salesforce', 'hubspot', 'dynamics365', 'pipedrive']);

function healthTone(status: string): 'success' | 'warning' | 'brand' | 'neutral' {
  if (status === 'healthy') return 'success';
  if (['unhealthy', 'auth_required', 'configuration_error', 'degraded', 'reconnect_required'].includes(status)) return 'warning';
  if (['connecting', 'rate_limited'].includes(status)) return 'brand';
  return 'neutral';
}

function channelWebhookUrl(path?: string): string {
  if (!path) return '';
  const configuredApi = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
  const apiUrl = new URL(configuredApi, window.location.origin);
  const apiBasePath = apiUrl.pathname.replace(/\/api\/v1\/?$/, '').replace(/\/$/, '');
  return `${apiUrl.origin}${apiBasePath}${path}`;
}

export function IntegrationsPage() {
  const result = useApi(() => api.integrations.list());
  const crmProviders = useApi(() => leadCrmApi.providers());
  const crmConnections = useApi(() => leadCrmApi.connections());
  const channelConnections = useApi(() => leadCrmApi.channelConnections());
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<'all' | Integration['category']>('all');
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const [whatsAppOpen, setWhatsAppOpen] = useState(false);
  const [showChannelOperationalHealth, setShowChannelOperationalHealth] = useState(false);
  const [showChannelHealthHistory, setShowChannelHealthHistory] = useState(false);
  const [showHealthHistory, setShowHealthHistory] = useState(false);
  const [showWebhookEvents, setShowWebhookEvents] = useState(false);
  const [crmProvider, setCrmProvider] = useState<CRMProviderId>('zoho');
  const [crmName, setCrmName] = useState('');
  const [crmClientId, setCrmClientId] = useState('');
  const [crmClientSecret, setCrmClientSecret] = useState('');
  const [crmApiKey, setCrmApiKey] = useState('');
  const [crmBaseUrl, setCrmBaseUrl] = useState('');
  const [channelProvider, setChannelProvider] = useState('telegram');
  const [channelName, setChannelName] = useState('');
  const [channelAgentId, setChannelAgentId] = useState('');
  const [channelBotToken, setChannelBotToken] = useState('');
  const [channelSecret, setChannelSecret] = useState('');
  const [channelAccessToken, setChannelAccessToken] = useState('');
  const [channelVerifyToken, setChannelVerifyToken] = useState('');
  const [channelAccountId, setChannelAccountId] = useState('');
  const canManage = session?.user.role === 'owner' || session?.user.role === 'admin';
  const items = useMemo(() => result.data?.filter((item) => (category === 'all' || item.category === category) && `${item.name} ${item.description}`.toLowerCase().includes(search.toLowerCase())) ?? [], [category, result.data, search]);

  const activate = async (item: Integration) => {
    if (item.id === 'whatsapp') {
      if (!canManage) return;
      setWhatsAppOpen(true);
      return;
    }
    const current = overrides[item.id] ?? item.connected;
    const next = !current;
    await api.integrations.setConnected(item.id, next);
    setOverrides((values) => ({ ...values, [item.id]: next }));
    pushToast(`${item.name} ${next ? 'connected' : 'disconnected'}`);
  };

  const createCrm = async () => {
    if (!crmName.trim()) return pushToast('Enter a connection name', 'error');
    try {
      const configuration: Record<string, unknown> = {};
      const credentials: Record<string, unknown> = {};
      if (crmBaseUrl.trim()) configuration.baseUrl = crmBaseUrl.trim();
      if (crmClientId.trim()) credentials.client_id = crmClientId.trim();
      if (crmClientSecret) credentials.client_secret = crmClientSecret;
      if (crmApiKey) credentials.api_key = crmApiKey;
      const created = await leadCrmApi.createConnection({ provider: crmProvider, name: crmName.trim(), configuration, credentials });
      pushToast(`${created.name} created`);
      setCrmName(''); setCrmClientId(''); setCrmClientSecret(''); setCrmApiKey(''); setCrmBaseUrl('');
      crmConnections.reload();
      if (oauthProviders.has(crmProvider)) {
        const oauth = await leadCrmApi.startOAuth(created.id);
        window.location.assign(oauth.authorizationUrl);
      } else {
        await leadCrmApi.testConnection(created.id);
        crmConnections.reload();
      }
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Could not create CRM connection', 'error');
    }
  };

  const createChannel = async () => {
    if (!channelName.trim() || !channelAgentId.trim()) return pushToast('Connection name and Agent ID are required', 'error');
    if (channelProvider === 'telegram' && !channelBotToken.trim()) return pushToast('Telegram Bot token is required', 'error');
    if (channelProvider === 'telegram' && !channelSecret.trim()) return pushToast('Telegram webhook secret is required', 'error');
    if (channelProvider === 'instagram' && !channelAccountId.trim()) return pushToast('Instagram professional account ID is required', 'error');
    if (channelProvider === 'instagram' && !channelAccessToken.trim()) return pushToast('Instagram access token is required', 'error');
    if (channelProvider === 'instagram' && !channelSecret.trim()) return pushToast('Instagram app secret is required', 'error');
    if (channelProvider === 'instagram' && !channelVerifyToken.trim()) return pushToast('Instagram webhook verify token is required', 'error');
    if (channelProvider === 'facebook_messenger' && !channelAccountId.trim()) return pushToast('Facebook Page ID is required', 'error');
    if (channelProvider === 'facebook_messenger' && !channelAccessToken.trim()) return pushToast('Facebook Page access token is required', 'error');
    if (channelProvider === 'facebook_messenger' && !channelSecret.trim()) return pushToast('Facebook app secret is required', 'error');
    if (channelProvider === 'facebook_messenger' && !channelVerifyToken.trim()) return pushToast('Facebook webhook verify token is required', 'error');
    if (channelProvider === 'slack' && !channelBotToken.trim()) return pushToast('Slack Bot token is required', 'error');
    if (channelProvider === 'slack' && !channelSecret.trim()) return pushToast('Slack signing secret is required', 'error');
    try {
      const credentials: Record<string, unknown> = {};
      const configuration: Record<string, unknown> = {
        agentId: channelAgentId.trim(),
        leadCaptureDefault: { createLead: true, qualify: false, syncToCRM: false },
      };
      if (channelProvider === 'telegram') {
        credentials.bot_token = channelBotToken.trim();
        credentials.webhook_secret = channelSecret.trim();
      } else if (channelProvider === 'instagram') {
        credentials.access_token = channelAccessToken.trim();
        credentials.app_secret = channelSecret.trim();
        credentials.verify_token = channelVerifyToken.trim();
        configuration.instagramAccountId = channelAccountId.trim();
        configuration.apiVersion = 'v26.0';
      } else if (channelProvider === 'facebook_messenger') {
        credentials.page_access_token = channelAccessToken.trim();
        credentials.app_secret = channelSecret.trim();
        credentials.verify_token = channelVerifyToken.trim();
        configuration.pageId = channelAccountId.trim();
        configuration.apiVersion = 'v26.0';
      } else if (channelProvider === 'slack') {
        credentials.bot_token = channelBotToken.trim();
        credentials.signing_secret = channelSecret.trim();
      } else if (channelSecret) {
        credentials.webhook_secret = channelSecret;
      }
      await leadCrmApi.createChannelConnection({
        provider: channelProvider,
        name: channelName.trim(),
        agentId: channelAgentId.trim(),
        configuration,
        credentials,
      });
      pushToast(`${channelName.trim()} created`);
      setChannelName(''); setChannelAgentId(''); setChannelBotToken(''); setChannelSecret(''); setChannelAccessToken(''); setChannelVerifyToken(''); setChannelAccountId('');
      channelConnections.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Could not create channel connection', 'error');
    }
  };

  const testCrm = async (id: string) => {
    try { const result = await leadCrmApi.testConnection(id); pushToast(`CRM health: ${result.status}`); crmConnections.reload(); }
    catch (error) { pushToast(error instanceof Error ? error.message : 'CRM health check failed', 'error'); }
  };
  const reconnectCrm = async (id: string) => {
    try { const result = await leadCrmApi.reconnect(id); window.location.assign(result.authorizationUrl); }
    catch (error) { pushToast(error instanceof Error ? error.message : 'Could not reconnect CRM', 'error'); }
  };
  const refreshSchema = async (id: string) => {
    try { await leadCrmApi.refreshSchema(id); pushToast('CRM field schema refreshed'); }
    catch (error) { pushToast(error instanceof Error ? error.message : 'Schema refresh failed', 'error'); }
  };

  if (result.loading || crmProviders.loading || crmConnections.loading || channelConnections.loading) return <PageLoader />;
  return <div className="page integrations-page">
    <div className="page-heading"><h2>Integrations</h2><p>Connect messaging sources to Northstar and route qualified leads to any CRM through durable, monitored deliveries.</p></div>

    <Card>
      <div className="page-heading page-heading--split"><div><h3>Messaging channels</h3><p>Webhook connections feed one canonical contact/lead pipeline. Existing WhatsApp Embedded Signup remains available below.</p></div><Badge tone="purple">Omnichannel ingress</Badge></div>
      {channelConnections.data?.length ? <div className="integration-grid">{channelConnections.data.map((connection) => <Card className="integration-card" key={connection.id}><div className="integration-card__icon"><ProviderLogo provider={connection.provider} /></div><div className="integration-card__copy"><span><h3>{connection.name}</h3><Badge tone={healthTone(connection.status)}>{connection.status}</Badge></span><p>{connection.provider} · Last event {connection.last_event_at ? new Date(connection.last_event_at).toLocaleString() : 'not received yet'}</p>{connection.provider === 'slack' && connection.webhook_path ? <small>Slack Events API Request URL: <code>{channelWebhookUrl(connection.webhook_path)}</code></small> : null}{connection.last_error ? <small>{connection.last_error}</small> : null}</div>{canManage ? <Button variant="secondary" size="sm" onClick={() => void leadCrmApi.testChannelConnection(connection.id).then(() => { pushToast('Channel test completed'); channelConnections.reload(); }).catch((error: unknown) => pushToast(error instanceof Error ? error.message : 'Channel test failed', 'error'))}>Test</Button> : null}</Card>)}</div> : <p>No provider-neutral channel connections configured yet.</p>}
      {canManage ? <div className="integration-toolbar"><select value={channelProvider} onChange={(event) => { setChannelProvider(event.target.value); setChannelBotToken(''); setChannelSecret(''); setChannelAccessToken(''); setChannelVerifyToken(''); setChannelAccountId(''); }} aria-label="Channel provider"><option value="telegram">Telegram</option><option value="instagram">Instagram</option><option value="facebook_messenger">Facebook Messenger</option><option value="slack">Slack</option><option value="api">Developer API</option><option value="custom">Custom webhook</option></select><input value={channelName} onChange={(event) => setChannelName(event.target.value)} placeholder="Connection name" /><input value={channelAgentId} onChange={(event) => setChannelAgentId(event.target.value)} placeholder="Agent ID" />{channelProvider === 'telegram' ? <input type="password" value={channelBotToken} onChange={(event) => setChannelBotToken(event.target.value)} placeholder="Telegram Bot token" autoComplete="off" /> : null}{channelProvider === 'slack' ? <input type="password" value={channelBotToken} onChange={(event) => setChannelBotToken(event.target.value)} placeholder="Slack Bot token" autoComplete="off" /> : null}{channelProvider === 'instagram' ? <><input value={channelAccountId} onChange={(event) => setChannelAccountId(event.target.value)} placeholder="Instagram professional account ID" /><input type="password" value={channelAccessToken} onChange={(event) => setChannelAccessToken(event.target.value)} placeholder="Instagram access token" autoComplete="off" /></> : null}{channelProvider === 'facebook_messenger' ? <><input value={channelAccountId} onChange={(event) => setChannelAccountId(event.target.value)} placeholder="Facebook Page ID" /><input type="password" value={channelAccessToken} onChange={(event) => setChannelAccessToken(event.target.value)} placeholder="Facebook Page access token" autoComplete="off" /></> : null}<input type="password" value={channelSecret} onChange={(event) => setChannelSecret(event.target.value)} placeholder={channelProvider === 'telegram' ? 'Telegram webhook secret token' : channelProvider === 'instagram' ? 'Instagram app secret' : channelProvider === 'facebook_messenger' ? 'Facebook app secret' : channelProvider === 'slack' ? 'Slack signing secret' : 'Webhook/App secret'} autoComplete="off" />{channelProvider === 'instagram' ? <input type="password" value={channelVerifyToken} onChange={(event) => setChannelVerifyToken(event.target.value)} placeholder="Instagram webhook verify token" autoComplete="off" /> : null}{channelProvider === 'facebook_messenger' ? <input type="password" value={channelVerifyToken} onChange={(event) => setChannelVerifyToken(event.target.value)} placeholder="Facebook webhook verify token" autoComplete="off" /> : null}<Button onClick={() => void createChannel()}>Add channel</Button></div> : null}
      {canManage && channelProvider === 'telegram' ? <p className="integration-helper">Telegram requires the Bot token from BotFather and a private webhook secret token. Secrets are encrypted server-side and are never returned by the connection API.</p> : null}
      {canManage && channelProvider === 'instagram' ? <p className="integration-helper">Instagram outbound replies require a Professional account access token with messaging permission, the Professional account ID, Meta app secret, and a private webhook verify token. Secrets are encrypted server-side and never returned by the connection API.</p> : null}
      {canManage && channelProvider === 'facebook_messenger' ? <p className="integration-helper">Facebook Messenger outbound replies require a Page access token with pages_messaging permission, the Facebook Page ID, Meta app secret, and a private webhook verify token. Secrets are encrypted server-side and never returned by the connection API.</p> : null}
      {canManage && channelProvider === 'slack' ? <p className="integration-helper">Slack requires a Bot token with chat:write and the app Signing Secret. Copy the Slack Events API Request URL shown on the connection card after creation, then subscribe to message/app mention events. Secrets are encrypted server-side and never returned by the connection API.</p> : null}
    </Card>

    {showChannelOperationalHealth ? <ChannelOperationalHealthPanel /> : <Card>
      <div className="page-heading page-heading--split">
        <div><h3>Channel operational health</h3><p>Review current connection health, outbound backlog, automatic retries, and terminal delivery failures for this Workspace.</p></div>
        <Button variant="secondary" onClick={() => setShowChannelOperationalHealth(true)}>View channel operations</Button>
      </div>
    </Card>}

    {showChannelHealthHistory ? <ChannelHealthHistoryPanel connections={channelConnections.data ?? []} /> : <Card>
      <div className="page-heading page-heading--split">
        <div><h3>Channel health history</h3><p>Review safe scheduled status history for each Workspace messaging connection without exposing provider payloads or credentials.</p></div>
        <Button variant="secondary" onClick={() => setShowChannelHealthHistory(true)}>View channel health history</Button>
      </div>
    </Card>}

    <Card>
      <div className="page-heading page-heading--split"><div><h3>CRM destinations</h3><p>Each connection has independent auth, schema, mapping, routing, health, retry, ACK and verification state.</p></div><Badge tone="purple">Any-CRM egress</Badge></div>
      {crmConnections.data?.length ? <div className="integration-grid">{crmConnections.data.map((connection) => <Card className="integration-card" key={connection.id}><div className="integration-card__icon"><Database /></div><div className="integration-card__copy"><span><h3>{connection.name}</h3><Badge tone={healthTone(connection.status)}>{connection.status}</Badge></span><p>{connection.provider} · {connection.environment}{connection.last_success_at ? ` · Last success ${new Date(connection.last_success_at).toLocaleString()}` : ''}</p>{connection.last_error ? <small>{connection.last_error}</small> : null}</div>{canManage ? <div><Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => void testCrm(connection.id)}>Test</Button> <Button variant="secondary" size="sm" onClick={() => void refreshSchema(connection.id)}>Schema</Button> {oauthProviders.has(connection.provider) ? <Button variant="secondary" size="sm" onClick={() => void reconnectCrm(connection.id)}>Reconnect</Button> : null}</div> : null}</Card>)}</div> : <p>No CRM destinations configured yet.</p>}
      {canManage ? <div className="integration-toolbar"><select value={crmProvider} onChange={(event) => setCrmProvider(event.target.value as CRMProviderId)} aria-label="CRM provider">{crmProviders.data?.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}</select><input value={crmName} onChange={(event) => setCrmName(event.target.value)} placeholder="Connection name" />{oauthProviders.has(crmProvider) ? <><input value={crmClientId} onChange={(event) => setCrmClientId(event.target.value)} placeholder="OAuth client ID" /><input type="password" value={crmClientSecret} onChange={(event) => setCrmClientSecret(event.target.value)} placeholder="OAuth client secret" /></> : <><input value={crmBaseUrl} onChange={(event) => setCrmBaseUrl(event.target.value)} placeholder="HTTPS base URL" /><input type="password" value={crmApiKey} onChange={(event) => setCrmApiKey(event.target.value)} placeholder="API key / credential" /></>}<Button onClick={() => void createCrm()}>Add CRM</Button></div> : null}
    </Card>

    <CRMManagementPanel connections={crmConnections.data ?? []} canManage={canManage} onConnectionsChanged={crmConnections.reload} />
    <CRMOperationalHealthPanel />
    {showHealthHistory ? <CRMHealthHistoryPanel connections={crmConnections.data ?? []} canManage={canManage} /> : <Card>
      <div className="page-heading page-heading--split">
        <div><h3>CRM health history</h3><p>Run recorded health checks and review safe historical status and latency evidence for each Workspace CRM.</p></div>
        <Button variant="secondary" onClick={() => setShowHealthHistory(true)}>View health history</Button>
      </div>
    </Card>}
    <CRMDeadLetterPanel connections={crmConnections.data ?? []} />
    {showWebhookEvents ? <CRMWebhookEventsPanel connections={crmConnections.data ?? []} /> : <Card>
      <div className="page-heading page-heading--split">
        <div><h3>CRM inbound webhook activity</h3><p>Review safe inbound processing status and correlation evidence without exposing webhook payloads or headers.</p></div>
        <Button variant="secondary" onClick={() => setShowWebhookEvents(true)}>View webhook activity</Button>
      </div>
    </Card>}

    <Card className="integration-hero"><div><span className="integration-hero__icon"><PlugZap /></span><span><Badge tone="purple">Integration marketplace</Badge><h3>Your AI agent, everywhere work happens.</h3><p>Keep knowledge in sync and give customers fast answers on every channel.</p></span></div><div className="integration-orbits"><span><Hash /></span><span><Database /></span><span><MessageCircle /></span><span><Zap /></span></div></Card>
    <div className="integration-toolbar"><div className="category-tabs">{(['all', 'channel', 'data', 'automation', 'developer'] as const).map((item) => <button key={item} className={category === item ? 'is-active' : ''} onClick={() => setCategory(item)}>{item === 'all' ? 'All integrations' : item}</button>)}</div><div className="search-box"><Search /><input aria-label="Search integrations" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search integrations" /></div></div>
    {result.error ? <Card><EmptyState icon={CircleAlert} title="Couldn't load integrations" description={result.error} action={<Button onClick={result.reload}>Try again</Button>} /></Card> : items.length ? <div className="integration-grid">{items.map((item) => {
      const Icon = iconMap[item.icon as keyof typeof iconMap] ?? PlugZap;
      const branded = ['whatsapp', 'slack', 'telegram', 'facebook_messenger', 'instagram', 'notion', 'zapier'].includes(item.id);
      const connected = overrides[item.id] ?? item.connected;
      const requiresAdmin = item.id === 'whatsapp' && !canManage;
      return <Card className="integration-card" key={item.id}><div className="integration-card__icon">{branded ? <ProviderLogo provider={item.id} /> : <Icon />}</div><div className="integration-card__copy"><span><h3>{item.name}</h3>{item.comingSoon ? <Badge>Coming soon</Badge> : requiresAdmin ? <Badge>Admin access</Badge> : connected ? <Badge tone="success"><Check /> Connected</Badge> : null}</span><p>{item.description}</p></div><Button variant={connected ? 'secondary' : 'primary'} size="sm" disabled={item.comingSoon || requiresAdmin} title={requiresAdmin ? 'A workspace owner or admin must manage WhatsApp' : undefined} onClick={() => void activate(item)}>{item.comingSoon ? 'Notify me' : requiresAdmin ? 'Admin only' : connected ? 'Manage' : 'Connect'}</Button></Card>;
    })}</div> : <Card><EmptyState icon={PlugZap} title="No integrations found" description="Try another name or category." /></Card>}
    <WhatsAppIntegrationModal open={whatsAppOpen} onClose={() => setWhatsAppOpen(false)} onConnectionChanged={(connected) => setOverrides((values) => ({ ...values, whatsapp: connected }))} />
  </div>;
}
