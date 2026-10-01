import { CheckCircle2, ExternalLink, LockKeyhole, RefreshCw } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Button, Field, Modal } from '@/components/ui';
import { api } from '@/lib/api';
import { crmOneClickApi, type CRMOneClickProvider, type CRMOAuthPopupMessage } from '@/lib/crm-one-click-api';
import { channelFields, channelSetupPayload, type CatalogIntegration, type ConnectionField } from '@/lib/integration-catalog';
import { leadCrmApi, type ChannelConnectionView, type CRMConnectionView, type CRMProviderId } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';
import { TelegramSetupModal } from '@/components/telegram-setup-modal';

interface Props {
  item: CatalogIntegration;
  provider?: CRMOneClickProvider;
  crmConnections: CRMConnectionView[];
  channelConnections: ChannelConnectionView[];
  canManage: boolean;
  onClose: () => void;
  onChanged: () => void;
}

export function IntegrationSetupModal(props: Props) {
  if (props.item.id === 'telegram') return <TelegramSetupModal connections={props.channelConnections} canManage={props.canManage} onClose={props.onClose} onChanged={props.onChanged} />;
  return <StandardIntegrationSetupModal {...props} />;
}

function StandardIntegrationSetupModal({ item, provider, crmConnections, channelConnections, canManage, onClose, onChanged }: Props) {
  const isChannel = item.category === 'Channels';
  const connections = (isChannel ? channelConnections : crmConnections).filter(value => value.provider === item.id);
  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? '');
  const [channelResult, setChannelResult] = useState<ChannelConnectionView | null>(null);
  const connection = connections.find(value => value.id === connectionId) ?? channelResult;
  const [editing, setEditing] = useState(!connection || connection.status === 'disabled');
  const [values, setValues] = useState<Record<string, string>>({ name: connection?.name ?? item.name, environment: connection && 'environment' in connection ? connection.environment : 'production', region: connection && 'region' in connection ? connection.region ?? 'us' : 'us', azureTenantId: 'common', authType: 'BEARER', apiKeyHeader: 'X-API-Key', agentId: connection && 'agent_id' in connection ? connection.agent_id ?? '' : '' });
  const [ownApp, setOwnApp] = useState(!provider?.configured);
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [disconnecting, setDisconnecting] = useState(false);
  const popup = useRef<Window | null>(null);
  const expectedConnection = useRef('');
  const callbacks = useRef({ onChanged });
  callbacks.current = { onChanged };
  const agents = useApi(() => isChannel ? api.agents.list() : Promise.resolve([]));
  const entitlements = useApi(() => leadCrmApi.connectionEntitlements());
  const oauth = provider?.mode === 'oauth';
  const callbackUrl = provider?.oauthRedirectUri ?? '';
  const canonicalChannel = item.id === 'facebook_messenger' ? 'facebook' : item.id;
  const planAllowed = !!entitlements.data && (isChannel ? entitlements.data.features.allowedChannels.includes(canonicalChannel) || entitlements.data.features.allowedChannels.includes(item.id) : entitlements.data.features.crm);
  const availableAgents = (agents.data ?? []).filter(agent => !agent.appearance.deploymentChannel || agent.appearance.deploymentChannel === canonicalChannel);

  useEffect(() => {
    const receive = (event: MessageEvent<CRMOAuthPopupMessage>) => {
      if (!callbackUrl || event.origin !== new URL(callbackUrl).origin || !popup.current || event.source !== popup.current) return;
      const data = event.data;
      if (!data || data.type !== 'northstar:crm-oauth' || (data.connectionId && data.connectionId !== expectedConnection.current)) return;
      popup.current.close(); popup.current = null; setWaiting(false);
      if (data.success) {
        setEditing(false);
        setMessage(data.readiness?.ready ? 'Account connected. Lead sync is enabled. Review your field mapping and routing below.' : 'Account authorized. Review mapping and sync readiness before sending leads.');
      } else setError(data.message || 'Authorization did not complete. Check your app settings and try again.');
      callbacks.current.onChanged();
    };
    window.addEventListener('message', receive);
    const timer = window.setInterval(() => {
      if (popup.current?.closed) { popup.current = null; setWaiting(false); setError('The authorization window was closed. You can try again.'); callbacks.current.onChanged(); }
    }, 700);
    return () => { window.removeEventListener('message', receive); window.clearInterval(timer); popup.current?.close(); popup.current = null; };
  }, [callbackUrl]);

  const update = (key: string, value: string) => setValues(current => ({ ...current, [key]: value }));
  const clearSecrets = () => setValues(current => Object.fromEntries(Object.entries(current).filter(([key]) => !['clientSecret', 'apiKey', 'token', 'bot_token', 'signing_secret', 'webhook_secret', 'access_token', 'page_access_token', 'app_secret', 'verify_token'].includes(key))));
  const input = (field: ConnectionField, required = true) => <Field key={field.key} label={field.label} htmlFor={`connect-${field.key}`} hint={field.hint}><input id={`connect-${field.key}`} type={field.type ?? 'text'} value={values[field.key] ?? ''} onChange={event => update(field.key, event.target.value)} placeholder={field.placeholder} required={required} maxLength={field.key === 'name' ? 160 : 4096} minLength={field.key === 'name' ? 2 : undefined} autoComplete={field.type === 'password' ? 'new-password' : 'off'} spellCheck={false} /></Field>;
  const check = async () => {
    if (!connectionId || !canManage) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const result = isChannel ? await leadCrmApi.testChannelConnection(connectionId) : await leadCrmApi.testConnection(connectionId);
      if (result.status !== 'healthy') throw new Error(`Connection needs attention (${result.status.replaceAll('_', ' ')}). Review your credentials and account permissions.`);
      setMessage(isChannel ? 'Credentials verified. Complete the webhook setup below, then send a message to your agent.' : 'Account connection verified. Review lead mapping and sync settings below.');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Connection check failed. Please try again.'); }
    finally { setBusy(false); onChanged(); }
  };
  const resumeAuthorization = async () => {
    if (!canManage || busy || waiting || !connectionId) return;
    setBusy(true); setError(''); setMessage('');
    try {
      popup.current = window.open('about:blank', `northstar-connect-${item.id}`, 'popup,width=720,height=760');
      if (!popup.current) throw new Error('Allow pop-ups, then select Authorize account again.');
      const result = await leadCrmApi.startOAuth(connectionId);
      expectedConnection.current = connectionId;
      if (!popup.current || popup.current.closed) throw new Error('Authorization window closed. Please try again.');
      popup.current.location.replace(result.authorizationUrl); setWaiting(true);
    } catch (reason) {
      popup.current?.close(); popup.current = null; setWaiting(false);
      setError(reason instanceof Error ? reason.message : 'Could not start authorization. Update the app credentials and retry.');
    } finally { setBusy(false); }
  };
  const disconnect = async () => {
    setBusy(true); setError('');
    try { if (isChannel) await leadCrmApi.disableChannelConnection(connectionId); else await leadCrmApi.disableConnection(connectionId); onChanged(); onClose(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not disconnect.'); setBusy(false); }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canManage || busy || waiting) return;
    setBusy(true); setError(''); setMessage('');
    try {
      if (oauth) {
        if (!callbackUrl) throw new Error('Connection settings are unavailable. Refresh the catalogue and try again.');
        popup.current = window.open('about:blank', `northstar-connect-${item.id}`, 'popup,width=720,height=760');
        if (!popup.current) throw new Error('Allow pop-ups for this site, then select Authorize account again.');
        const result = await crmOneClickApi.startOAuth(item.id as CRMProviderId, {
          name: values.name, environment: values.environment === 'sandbox' ? 'sandbox' : 'production',
          region: values.region, resource_url: values.resourceUrl || undefined, azure_tenant_id: values.azureTenantId,
          ...(ownApp ? { client_id: values.clientId?.trim(), client_secret: values.clientSecret } : {}),
        });
        expectedConnection.current = result.connectionId; setConnectionId(result.connectionId); clearSecrets();
        if (!popup.current || popup.current.closed) throw new Error('Authorization window closed. Please try again.');
        popup.current.location.replace(result.authorizationUrl); setWaiting(true); onChanged();
      } else if (isChannel) {
        const payload = channelSetupPayload(item.id, values);
        const saved = connectionId ? await leadCrmApi.updateChannelConnection(connectionId, payload) : await leadCrmApi.createChannelConnection(payload);
        setConnectionId(saved.id); setChannelResult(saved); clearSecrets();
        const health = await leadCrmApi.testChannelConnection(saved.id);
        if (health.status !== 'healthy') throw new Error(`Credentials could not be verified (${health.status?.replaceAll('_', ' ') ?? 'unknown'}). Enter corrected credentials and retry.`);
        setEditing(false); setMessage('Credentials verified. Finish the webhook setup below to receive customer messages.'); onChanged();
      } else {
        const result = await crmOneClickApi.activateDirect(item.id as CRMProviderId, {
          name: values.name, base_url: values.baseUrl!, api_key: values.apiKey || undefined, token: values.token || undefined,
          auth_type: values.authType as 'BEARER' | 'API_KEY_HEADER' | 'NONE', api_key_header: values.apiKeyHeader,
          health_path: values.healthPath || '', upsert_path: values.upsertPath || '', get_path: values.getPath || '',
        });
        setConnectionId(result.connectionId); clearSecrets(); setEditing(false);
        setMessage(result.ready ? 'Account connected. Lead sync is enabled. Review your mapping and routing below.' : `Account saved. Setup needs attention: ${result.blockers.join(', ')}`); onChanged();
      }
    } catch (reason) { popup.current?.close(); popup.current = null; setWaiting(false); setError(reason instanceof Error ? reason.message : 'Could not connect. Check your details and try again.'); onChanged(); }
    finally { setBusy(false); }
  };
  const webhookPath = connection && 'webhook_path' in connection ? connection.webhook_path : channelResult?.webhook_path;
  const apiBase = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api/v1';
  const webhookUrl = webhookPath ? new URL(webhookPath, new URL(apiBase, window.location.origin)).href : '';
  const localWebhook = webhookUrl && /^(localhost|127\.0\.0\.1|\[::1\])$/.test(new URL(webhookUrl).hostname);

  return <Modal open onClose={onClose} closeDisabled={busy} title={`${editing ? 'Connect' : 'Manage'} ${item.name}`} description={editing ? 'Add your account details, then verify the connection.' : 'Review your connection and complete any remaining setup.'} size="md" footer={<>{error && <div role="alert" className="catalog-notice catalog-notice--error" style={{ width: '100%' }}>{error}{!planAllowed && <><br /><Link to="/workspace?section=billing" onClick={onClose}>Review plans</Link></>}</div>}<Button variant="secondary" onClick={onClose} disabled={busy}>{waiting ? 'Cancel authorization' : 'Close'}</Button>{editing && <Button type="submit" form="integration-connect-form" disabled={!canManage || busy || waiting || (isChannel && !availableAgents.length)} icon={oauth ? ExternalLink : undefined}>{busy ? 'Connecting…' : waiting ? 'Waiting for authorization…' : oauth ? 'Authorize account' : 'Save and verify'}</Button>}</>}>
    <div className="connection-setup">
      <ol className="connection-steps" aria-label="Connection steps"><li className={editing ? 'is-current' : ''}><span>1</span>Account details</li><li className={waiting || busy ? 'is-current' : ''}><span>2</span>Verify access</li><li className={!editing ? 'is-current' : ''}><span>3</span>{isChannel ? 'Message setup' : 'Review sync'}</li></ol>

      {message && <div role="status" className="catalog-notice catalog-notice--success"><CheckCircle2 size={20} /><span>{message}</span></div>}
      {waiting && <p role="status" className="catalog-notice">Complete authorization in the provider window. This dialog will update when you return.</p>}
      {editing ? <form id="integration-connect-form" onSubmit={event => void submit(event)} className="connection-form">
        {entitlements.loading ? <p role="status">Checking available connections…</p> : entitlements.error ? <div role="alert" className="catalog-notice catalog-notice--error">Could not check plan access. <Button variant="ghost" onClick={entitlements.reload}>Try again</Button></div> : !planAllowed && <div className="catalog-notice">Your {entitlements.data?.plan} plan does not include {isChannel ? item.name : 'CRM connections'}. <Link to="/workspace?section=billing" onClick={onClose}>Review plans</Link> to enable this connection.</div>}
        <fieldset disabled={busy || waiting || !canManage}>
          {input({ key: 'name', label: 'Connection name', placeholder: `My ${item.name} account` })}
          {oauth && <>
            {provider?.supportsSandbox && <Field label="Environment" htmlFor="connect-environment"><select id="connect-environment" value={values.environment} onChange={event => update('environment', event.target.value)}><option value="production">Production</option><option value="sandbox">Sandbox</option></select></Field>}
            {item.id === 'zoho' && <Field label="Zoho data center" htmlFor="connect-region"><select id="connect-region" value={values.region} onChange={event => update('region', event.target.value)}>{[['us', 'United States'], ['in', 'India'], ['eu', 'Europe'], ['au', 'Australia'], ['jp', 'Japan'], ['ca', 'Canada'], ['sa', 'Saudi Arabia'], ['cn', 'China']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>}
            {item.id === 'dynamics365' && <>{input({ key: 'resourceUrl', label: 'Organization URL', type: 'url', placeholder: 'https://your-company.crm.dynamics.com' })}{input({ key: 'azureTenantId', label: 'Microsoft tenant ID', hint: 'Use your directory tenant ID, or common if your app supports multiple tenants.' })}</>}
            {provider?.configured && <label className="connection-checkbox"><input type="checkbox" checked={ownApp} onChange={event => setOwnApp(event.target.checked)} />Use my own OAuth app</label>}
            {ownApp && <div className="connection-app-fields"><h3>OAuth application</h3><p>Enter the app credentials from your {item.name} developer settings. You will sign in and approve access on {item.name}.</p>{input({ key: 'clientId', label: 'Client ID' })}{input({ key: 'clientSecret', label: 'Client secret', type: 'password' })}<Field label="Authorized redirect URL" htmlFor="connect-callback" hint="Copy this exact URL into your OAuth app's redirect settings."><input id="connect-callback" readOnly value={callbackUrl} onFocus={event => event.target.select()} /></Field></div>}
          </>}
          {isChannel && <><Field label="Agent" htmlFor="connect-agent" hint="Choose the agent that will answer messages on this channel."><select id="connect-agent" required value={values.agentId ?? ''} onChange={event => update('agentId', event.target.value)}><option value="">Select an agent</option>{availableAgents.map(agent => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></Field>{agents.error && <p role="alert">Could not load agents: {agents.error}</p>}{!agents.loading && !agents.error && !availableAgents.length && <p className="catalog-notice">Create an agent for {item.name} first. <Link to="/agents" onClick={onClose}>Go to Agents</Link></p>}{channelFields[item.id]?.map(field => input(field))}</>}
          {!isChannel && !oauth && <>{input({ key: 'baseUrl', label: item.id === 'freshsales' ? 'Freshsales account URL' : 'API base URL', type: 'url', placeholder: item.id === 'freshsales' ? 'https://your-company.myfreshworks.com/crm/sales' : 'https://crm.example.com/api' })}{item.id === 'freshsales' ? input({ key: 'apiKey', label: 'API key', type: 'password' }) : <><Field label="Authentication" htmlFor="connect-auth"><select id="connect-auth" value={values.authType} onChange={event => update('authType', event.target.value)}><option value="BEARER">Bearer token</option><option value="API_KEY_HEADER">API key header</option><option value="NONE">No authentication</option></select></Field>{values.authType === 'BEARER' && input({ key: 'token', label: 'Access token', type: 'password' })}{values.authType === 'API_KEY_HEADER' && <>{input({ key: 'apiKey', label: 'API key', type: 'password' })}{input({ key: 'apiKeyHeader', label: 'API key header name' })}</>}{input({ key: 'healthPath', label: 'Health check path', placeholder: '/health' }, false)}{input({ key: 'upsertPath', label: 'Lead upsert path', placeholder: '/leads/upsert' })}{input({ key: 'getPath', label: 'Lead read-back path', placeholder: '/leads/{id}', hint: 'Use {id} where the external record ID belongs. Responses must provide an id field.' })}</>}</>}
        </fieldset>
        {!isChannel && <p className="catalog-notice">Connecting enables lead sync for this workspace and prepares default field mapping. Review mapping and routing after authorization.</p>}
        <p className="connection-security"><LockKeyhole size={16} />Credentials are encrypted and are never displayed after saving.</p>
      </form> : <div className="connection-manage">
        {connections.length > 1 && <Field label="Connection" htmlFor="manage-connection"><select id="manage-connection" value={connectionId} onChange={event => { setConnectionId(event.target.value); setMessage(''); setError(''); }}>{connections.map(value => <option key={value.id} value={value.id}>{value.name}</option>)}</select></Field>}
        <div className="connection-details"><span>Account</span><strong>{connection?.name ?? values.name}</strong><span>Status</span><strong>{connection?.status.replaceAll('_', ' ') ?? 'Saved'}</strong></div>
        {isChannel && webhookUrl && <div className="connection-app-fields"><h3>Finish message setup</h3><p>{item.id === 'slack' ? 'Enable Events in your Slack app, enter this Request URL and subscribe to the message events your agent should answer.' : item.id === 'telegram' ? 'Register this URL with Telegram setWebhook, using the webhook secret you provided as secret_token.' : 'Enter this callback URL in your Meta app webhook settings, use the verify token you provided, and subscribe your account to messaging events.'}</p><Field label="Webhook URL" htmlFor="connect-webhook"><input id="connect-webhook" value={webhookUrl} readOnly onFocus={event => event.target.select()} /></Field>{localWebhook && <p className="catalog-notice">Your app is running locally. Configure a public HTTPS address before the platform can deliver customer messages to this endpoint.</p>}<p>Send a message from the platform, then refresh the connection status to confirm messages are arriving.</p></div>}
        {!isChannel && <Link className="button button--secondary button--md" to={`/integrations/advanced?connection=${connectionId}`} onClick={onClose}>Review field mapping and routing</Link>}
        <div className="connection-actions">{oauth && <Button icon={ExternalLink} disabled={busy || waiting || !canManage} onClick={() => void resumeAuthorization()}>{waiting ? 'Waiting for authorization...' : 'Authorize account'}</Button>}<Button icon={RefreshCw} variant="secondary" onClick={() => void check()} disabled={busy || !canManage}>Check connection</Button><Button variant="ghost" disabled={busy || !canManage} onClick={() => { setEditing(true); setMessage(''); setError(''); update('name', connection?.name ?? values.name ?? item.name); if (connection && 'agent_id' in connection) update('agentId', connection.agent_id ?? ''); }}>Update credentials</Button></div>
        {disconnecting ? <div className="catalog-notice"><p>Disconnect {item.name}? This stops this connection and removes its saved credentials.</p><Button variant="danger" disabled={busy} onClick={() => void disconnect()}>Confirm disconnect</Button><Button variant="ghost" disabled={busy} onClick={() => setDisconnecting(false)}>Cancel</Button></div> : <Button variant="ghost" disabled={busy || !canManage} onClick={() => setDisconnecting(true)}>Disconnect account</Button>}
      </div>}
    </div>
  </Modal>;
}
