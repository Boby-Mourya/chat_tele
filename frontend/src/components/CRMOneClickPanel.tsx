import {
  CheckCircle2,
  CircleAlert,
  Database,
  ExternalLink,
  PlugZap,
  RefreshCw,
  Send,
  ShieldCheck,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import {
  crmOneClickApi,
  type CRMOAuthPopupMessage,
  type CRMOneClickProvider,
  type CRMReadiness,
} from '@/lib/crm-one-click-api';
import type { CRMConnectionView, CRMProviderId } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';
import '@/components/CRMOneClickPanel.css';

interface CRMOneClickPanelProps {
  connections: CRMConnectionView[];
  canManage: boolean;
  onConnectionsChanged: () => void;
}

interface SetupForm {
  name: string;
  environment: 'production' | 'sandbox';
  region: string;
  resourceUrl: string;
  azureTenantId: string;
  baseUrl: string;
  apiKey: string;
  token: string;
  authType: 'NONE' | 'BEARER' | 'API_KEY_HEADER';
  apiKeyHeader: string;
  healthPath: string;
  upsertPath: string;
  getPath: string;
  externalIdPath: string;
  readBackIdPath: string;
}

const DEFAULT_FORM: SetupForm = {
  name: '',
  environment: 'production',
  region: 'us',
  resourceUrl: '',
  azureTenantId: 'common',
  baseUrl: '',
  apiKey: '',
  token: '',
  authType: 'BEARER',
  apiKeyHeader: 'X-API-Key',
  healthPath: '',
  upsertPath: '',
  getPath: '',
  externalIdPath: '$.id',
  readBackIdPath: 'id',
};

const blockerLabels: Record<string, string> = {
  credentials_missing: 'Authorization is missing',
  connection_not_healthy: 'Provider health check is not healthy',
  schema_not_discovered: 'Provider schema has not been discovered',
  mapping_not_active: 'Lead mapping is not active',
  route_not_enabled: 'Workspace route is not enabled',
  auto_sync_new_leads_disabled: 'New-lead auto-sync is disabled',
  auto_sync_updates_disabled: 'Lead-update auto-sync is disabled',
  event_pipeline_not_enabled: 'Kafka/outbox event dispatch is not enabled',
};

function connectionFor(
  provider: CRMOneClickProvider,
  connections: CRMConnectionView[],
): CRMConnectionView | undefined {
  return connections.find((connection) => (
    connection.provider === provider.id
    && Boolean(connection.configuration.managedOAuth || connection.configuration.directConnect)
    && connection.status !== 'disabled'
  ));
}

function statusTone(status: string): 'success' | 'warning' | 'brand' | 'neutral' {
  if (status === 'healthy' || status === 'verified') return 'success';
  if (['unhealthy', 'auth_required', 'configuration_error', 'failed', 'dead_letter'].includes(status)) return 'warning';
  if (['connecting', 'queued', 'processing', 'verifying', 'retrying'].includes(status)) return 'brand';
  return 'neutral';
}

const delay = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export function CRMOneClickPanel({
  connections,
  canManage,
  onConnectionsChanged,
}: CRMOneClickPanelProps) {
  const providers = useApi(() => crmOneClickApi.providers());
  const { pushToast } = useToast();
  const [selected, setSelected] = useState<CRMOneClickProvider>();
  const [form, setForm] = useState<SetupForm>(DEFAULT_FORM);
  const [busyProvider, setBusyProvider] = useState<CRMProviderId>();
  const [testingConnection, setTestingConnection] = useState<string>();
  const [readiness, setReadiness] = useState<Record<string, CRMReadiness>>({});
  const pollGeneration = useRef(0);
  const popupRef = useRef<Window | null>(null);

  const managedConnections = useMemo(
    () => connections.filter((connection) => Boolean(
      connection.configuration.managedOAuth || connection.configuration.directConnect,
    )),
    [connections],
  );

  const refreshReadiness = useCallback(async (connectionIds?: string[]) => {
    const ids = connectionIds ?? managedConnections.map((connection) => connection.id);
    if (!ids.length) return;
    const values = await Promise.allSettled(ids.map((id) => crmOneClickApi.readiness(id)));
    setReadiness((current) => {
      const next = { ...current };
      values.forEach((value, index) => {
        if (value.status === 'fulfilled') next[ids[index]!] = value.value;
      });
      return next;
    });
  }, [managedConnections]);

  useEffect(() => {
    let active = true;
    void Promise.allSettled(managedConnections.map((connection) => crmOneClickApi.readiness(connection.id)))
      .then((values) => {
        if (!active) return;
        const next: Record<string, CRMReadiness> = {};
        values.forEach((value, index) => {
          if (value.status === 'fulfilled') next[managedConnections[index]!.id] = value.value;
        });
        setReadiness(next);
      });
    return () => { active = false; };
  }, [managedConnections]);

  useEffect(() => () => {
    pollGeneration.current += 1;
    popupRef.current?.close();
  }, []);

  const pollCertification = useCallback(async (connectionId: string, deliveryId: string) => {
    const generation = ++pollGeneration.current;
    const terminalFailures = new Set([
      'failed',
      'dead_letter',
      'auth_required',
      'mapping_error',
      'cancelled',
    ]);
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await delay(attempt === 0 ? 750 : 2_000);
      if (pollGeneration.current !== generation) return;
      try {
        const value = await crmOneClickApi.acceptanceStatus(connectionId, deliveryId);
        if (value.verified) {
          const ready = await crmOneClickApi.readiness(connectionId);
          setReadiness((current) => ({ ...current, [connectionId]: ready }));
          setTestingConnection(undefined);
          pushToast(`Live CRM certification passed. External record ${value.externalRecordId ?? 'verified'}.`);
          onConnectionsChanged();
          return;
        }
        const verificationFailed = ['failed', 'auth_required', 'unsupported'].includes(
          value.verificationStatus,
        );
        if (terminalFailures.has(value.status) || verificationFailed) {
          setTestingConnection(undefined);
          const terminalState = verificationFailed ? value.verificationStatus : value.status;
          pushToast(
            value.errorMessage ?? `CRM certification stopped in ${terminalState.replaceAll('_', ' ')} state`,
            'error',
          );
          void refreshReadiness([connectionId]);
          return;
        }
      } catch {
        // A transient refresh failure must not cancel a provider delivery already in progress.
      }
    }
    setTestingConnection(undefined);
    pushToast(
      'The provider delivery is still processing. Its exact ACK and verification state remains visible in Leads.',
      'error',
    );
  }, [onConnectionsChanged, pushToast, refreshReadiness]);

  const queueAcceptanceTest = useCallback(async (connectionId: string) => {
    setTestingConnection(connectionId);
    try {
      const result = await crmOneClickApi.acceptanceTest(connectionId);
      pushToast(result.message);
      void pollCertification(connectionId, result.deliveryId);
    } catch (error) {
      setTestingConnection(undefined);
      pushToast(
        error instanceof Error ? error.message : 'Could not send the CRM acceptance-test Lead',
        'error',
      );
    }
  }, [pollCertification, pushToast]);

  useEffect(() => {
    const receiveOAuthResult = (event: MessageEvent<unknown>) => {
      if (event.origin !== crmOneClickApi.callbackOrigin()) return;
      if (popupRef.current && event.source !== popupRef.current) return;
      const value = event.data as Partial<CRMOAuthPopupMessage> | null;
      if (!value || value.type !== 'northstar:crm-oauth') return;
      popupRef.current = null;
      setBusyProvider(undefined);
      if (!value.success) {
        pushToast(value.message ?? 'CRM authorization could not be completed', 'error');
        onConnectionsChanged();
        return;
      }
      if (value.connectionId && value.readiness) {
        setReadiness((current) => ({ ...current, [value.connectionId!]: value.readiness! }));
      }
      pushToast(value.message ?? 'CRM connected. New Leads will sync automatically.');
      onConnectionsChanged();
      if (value.connectionId) {
        void refreshReadiness([value.connectionId]);
        void queueAcceptanceTest(value.connectionId);
      }
    };
    window.addEventListener('message', receiveOAuthResult);
    return () => window.removeEventListener('message', receiveOAuthResult);
  }, [onConnectionsChanged, pushToast, queueAcceptanceTest, refreshReadiness]);

  const chooseProvider = (provider: CRMOneClickProvider) => {
    setSelected(provider);
    setForm({
      ...DEFAULT_FORM,
      name: provider.name,
      region: provider.id === 'zoho' ? 'us' : DEFAULT_FORM.region,
      baseUrl: provider.id === 'freshsales' ? 'https://your-domain.myfreshworks.com/crm/sales' : '',
    });
  };

  const startOAuth = async (provider: CRMOneClickProvider, activeForm: SetupForm = form) => {
    const popup = window.open('about:blank', `northstar-crm-${provider.id}`, 'popup,width=720,height=760');
    if (!popup) {
      pushToast('Allow popups for this site to connect the CRM securely.', 'error');
      return;
    }
    popup.document.title = `Connect ${provider.name}`;
    if (popup.document.body) popup.document.body.textContent = `Preparing ${provider.name} authorization…`;
    popupRef.current = popup;
    setBusyProvider(provider.id);
    try {
      const result = await crmOneClickApi.startOAuth(provider.id, {
        name: activeForm.name.trim() || provider.name,
        environment: activeForm.environment,
        region: provider.id === 'zoho' ? activeForm.region : undefined,
        resource_url: provider.id === 'dynamics365' ? activeForm.resourceUrl.trim() : undefined,
        azure_tenant_id: provider.id === 'dynamics365' ? activeForm.azureTenantId.trim() : undefined,
      });
      popup.location.replace(result.authorizationUrl);
      setSelected(undefined);
    } catch (error) {
      popup.close();
      popupRef.current = null;
      setBusyProvider(undefined);
      pushToast(error instanceof Error ? error.message : 'CRM connection could not be started', 'error');
    }
  };

  const activateDirect = async (provider: CRMOneClickProvider) => {
    setBusyProvider(provider.id);
    try {
      const value = await crmOneClickApi.activateDirect(provider.id, {
        name: form.name.trim() || provider.name,
        base_url: form.baseUrl.trim(),
        api_key: form.apiKey || undefined,
        token: form.token || undefined,
        auth_type: form.authType,
        api_key_header: form.apiKeyHeader,
        health_path: form.healthPath,
        upsert_path: form.upsertPath,
        get_path: form.getPath,
        external_id_path: form.externalIdPath,
        read_back_id_path: form.readBackIdPath,
      });
      setReadiness((current) => ({ ...current, [value.connectionId]: value }));
      pushToast(`${provider.name} connected. New Leads will sync automatically.`);
      setSelected(undefined);
      setForm(DEFAULT_FORM);
      onConnectionsChanged();
      void queueAcceptanceTest(value.connectionId);
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'CRM connection could not be activated', 'error');
    } finally {
      setBusyProvider(undefined);
    }
  };

  const connect = (provider: CRMOneClickProvider) => {
    const needsConfiguration = ['zoho', 'salesforce', 'dynamics365'].includes(provider.id) || provider.mode !== 'oauth';
    if (needsConfiguration) {
      chooseProvider(provider);
      return;
    }
    const defaults = { ...DEFAULT_FORM, name: provider.name };
    setForm(defaults);
    void startOAuth(provider, defaults);
  };

  const runAcceptanceTest = (connection: CRMConnectionView) => {
    void queueAcceptanceTest(connection.id);
  };

  if (providers.error) {
    return <Card><EmptyState icon={CircleAlert} title="One-click CRM setup is unavailable" description={providers.error} action={<Button onClick={providers.reload}>Retry</Button>} /></Card>;
  }

  return <Card className="crm-one-click">
    <div className="page-heading page-heading--split crm-one-click__heading">
      <div>
        <Badge tone="purple"><PlugZap /> One-click CRM</Badge>
        <h3>Connect once. Every eligible Lead flows automatically.</h3>
        <p>Northstar completes authorization, health validation, schema discovery, field mapping, workspace routing and auto-sync. A live test then proves provider ACK, external record ID and read-back verification.</p>
      </div>
      <Badge tone={managedConnections.some((item) => readiness[item.id]?.liveCertified) ? 'success' : 'neutral'}>
        <ShieldCheck /> {managedConnections.some((item) => readiness[item.id]?.liveCertified) ? 'Live certified' : 'Certification required'}
      </Badge>
    </div>

    <div className="crm-one-click__providers" aria-busy={providers.loading}>
      {providers.data?.map((provider) => {
        const connection = connectionFor(provider, connections);
        const state = connection ? readiness[connection.id] : undefined;
        return <article className="crm-one-click__provider" key={provider.id}>
          <div className="crm-one-click__provider-icon"><Database /></div>
          <div className="crm-one-click__provider-copy">
            <span><strong>{provider.name}</strong><Badge tone={connection ? statusTone(connection.status) : 'neutral'}>{connection ? connection.status.replaceAll('_', ' ') : provider.mode === 'oauth' ? 'OAuth' : 'secure credential'}</Badge></span>
            <small>{provider.supportsReadBack ? 'Provider ACK + read-back proof' : 'Provider ACK only'}</small>
            {!provider.configured ? <small className="crm-one-click__warning">Platform OAuth app credentials are not configured.</small> : null}
          </div>
          {connection ? <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => chooseProvider(provider)} disabled={!canManage}>Reconnect</Button>
            : <Button size="sm" icon={ExternalLink} onClick={() => connect(provider)} disabled={!canManage || !provider.configured || busyProvider === provider.id}>{busyProvider === provider.id ? 'Opening…' : 'Connect'}</Button>}
          {connection && state ? <div className="crm-one-click__provider-status">
            <span className={state.ready ? 'is-complete' : 'is-pending'}><i /> Setup ready</span>
            <span className={state.liveCertified ? 'is-complete' : 'is-pending'}><i /> Live Lead verified</span>
          </div> : null}
        </article>;
      })}
    </div>

    {selected ? <section className="crm-one-click__setup" aria-label={`Connect ${selected.name}`}>
      <div><h4>Connect {selected.name}</h4><p>{selected.mode === 'oauth' ? 'Northstar will open the provider consent screen. No CRM client secret is entered by the customer.' : 'The credential is encrypted server-side, tested once and never returned.'}</p></div>
      <div className="crm-one-click__form">
        <label>Connection name<input value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} /></label>
        {selected.id === 'zoho' ? <label>Zoho data center<select value={form.region} onChange={(event) => setForm((value) => ({ ...value, region: event.target.value }))}><option value="us">United States</option><option value="in">India</option><option value="eu">Europe</option><option value="au">Australia</option><option value="jp">Japan</option><option value="ca">Canada</option><option value="sa">Saudi Arabia</option><option value="cn">China</option></select></label> : null}
        {selected.id === 'salesforce' ? <label>Salesforce environment<select value={form.environment} onChange={(event) => setForm((value) => ({ ...value, environment: event.target.value as SetupForm['environment'] }))}><option value="production">Production</option><option value="sandbox">Sandbox</option></select></label> : null}
        {selected.id === 'dynamics365' ? <><label>Dynamics organization URL<input value={form.resourceUrl} onChange={(event) => setForm((value) => ({ ...value, resourceUrl: event.target.value }))} placeholder="https://your-org.crm.dynamics.com" /></label><label>Microsoft Entra tenant ID<input value={form.azureTenantId} onChange={(event) => setForm((value) => ({ ...value, azureTenantId: event.target.value }))} placeholder="common or tenant GUID" /></label></> : null}
        {selected.mode !== 'oauth' ? <label>CRM HTTPS base URL<input value={form.baseUrl} onChange={(event) => setForm((value) => ({ ...value, baseUrl: event.target.value }))} placeholder={selected.id === 'freshsales' ? 'https://your-domain.myfreshworks.com/crm/sales' : 'https://crm.example.com/api'} /></label> : null}
        {selected.id === 'freshsales' ? <label>Freshsales API key<input type="password" autoComplete="off" value={form.apiKey} onChange={(event) => setForm((value) => ({ ...value, apiKey: event.target.value }))} /></label> : null}
        {selected.id === 'generic_rest' ? <>
          <label>Authentication<select value={form.authType} onChange={(event) => setForm((value) => ({ ...value, authType: event.target.value as SetupForm['authType'] }))}><option value="BEARER">Bearer token</option><option value="API_KEY_HEADER">API-key header</option><option value="NONE">No authentication</option></select></label>
          {form.authType === 'BEARER' ? <label>Bearer token<input type="password" autoComplete="off" value={form.token} onChange={(event) => setForm((value) => ({ ...value, token: event.target.value }))} /></label> : null}
          {form.authType === 'API_KEY_HEADER' ? <><label>Header name<input value={form.apiKeyHeader} onChange={(event) => setForm((value) => ({ ...value, apiKeyHeader: event.target.value }))} /></label><label>API key<input type="password" autoComplete="off" value={form.apiKey} onChange={(event) => setForm((value) => ({ ...value, apiKey: event.target.value }))} /></label></> : null}
          <label>Health path<input value={form.healthPath} onChange={(event) => setForm((value) => ({ ...value, healthPath: event.target.value }))} placeholder="/health" /></label>
          <label>Upsert path<input value={form.upsertPath} onChange={(event) => setForm((value) => ({ ...value, upsertPath: event.target.value }))} placeholder="/leads/upsert" /></label>
          <label>Read-back path<input value={form.getPath} onChange={(event) => setForm((value) => ({ ...value, getPath: event.target.value }))} placeholder="/leads/{id}" /></label>
          <label>ACK record-ID path<input value={form.externalIdPath} onChange={(event) => setForm((value) => ({ ...value, externalIdPath: event.target.value }))} placeholder="$.data.id" /></label>
          <label>Read-back ID path<input value={form.readBackIdPath} onChange={(event) => setForm((value) => ({ ...value, readBackIdPath: event.target.value }))} placeholder="id" /></label>
        </> : null}
      </div>
      <div className="crm-one-click__setup-actions"><Button variant="secondary" onClick={() => setSelected(undefined)}>Cancel</Button><Button icon={ExternalLink} disabled={busyProvider === selected.id} onClick={() => selected.mode === 'oauth' ? void startOAuth(selected) : void activateDirect(selected)}>{busyProvider === selected.id ? 'Connecting…' : 'Connect and activate'}</Button></div>
    </section> : null}

    {managedConnections.length ? <section className="crm-one-click__connections">
      <div><h4>Connected CRM flow</h4><p>A connection is “ready” only after every stage below is active. “Live certified” requires a real Lead to be written and read back from the CRM.</p></div>
      {managedConnections.map((connection) => {
        const state = readiness[connection.id];
        return <article key={connection.id} className="crm-one-click__connection">
          <header><span><strong>{connection.name}</strong><small>{connection.provider}</small></span><Badge tone={state?.liveCertified ? 'success' : state?.ready ? 'brand' : 'warning'}>{state?.liveCertified ? 'Live certified' : state?.ready ? 'Ready for live test' : connection.status.replaceAll('_', ' ')}</Badge></header>
          {state ? <>
            <div className="crm-one-click__flow">
              {[
                ['Authorization', !state.blockers.includes('credentials_missing')],
                ['Health', !state.blockers.includes('connection_not_healthy')],
                ['Schema', !state.blockers.includes('schema_not_discovered')],
                ['Mapping', !state.blockers.includes('mapping_not_active')],
                ['Route', !state.blockers.includes('route_not_enabled')],
                ['Auto-sync', state.autoSyncNewLeads && state.autoSyncUpdates && state.eventPipelineReady],
                ['Provider proof', state.liveCertified],
              ].map(([label, complete]) => <span key={String(label)} className={complete ? 'is-complete' : 'is-pending'}>{complete ? <CheckCircle2 /> : <CircleAlert />}{String(label)}</span>)}
            </div>
            {state.blockers.length ? <div className="crm-one-click__blockers" role="alert">{state.blockers.map((blocker) => <span key={blocker}><CircleAlert /> {blockerLabels[blocker] ?? blocker.replaceAll('_', ' ')}</span>)}</div> : null}
            {state.liveCertified ? <div className="crm-one-click__certificate"><ShieldCheck /><span><strong>Provider record verified</strong><small>External ID {state.externalRecordId ?? 'record identity verified'} · {state.certifiedAt ? new Date(state.certifiedAt).toLocaleString() : 'now'}</small></span></div> : null}
          </> : <p>Checking CRM readiness…</p>}
          <footer><Button variant="secondary" icon={RefreshCw} onClick={() => void refreshReadiness([connection.id])}>Refresh</Button>{state?.ready ? <Button icon={Send} disabled={testingConnection === connection.id} onClick={() => void runAcceptanceTest(connection)}>{testingConnection === connection.id ? 'Sending and verifying…' : state.liveCertified ? 'Run another live test' : 'Send live test Lead'}</Button> : <Button icon={RefreshCw} onClick={() => void crmOneClickApi.provision(connection.id).then((value) => { setReadiness((current) => ({ ...current, [connection.id]: value })); pushToast('CRM setup repaired'); onConnectionsChanged(); }).catch((error: unknown) => pushToast(error instanceof Error ? error.message : 'CRM setup repair failed', 'error'))}>Repair setup</Button>}</footer>
        </article>;
      })}
    </section> : null}
  </Card>;
}
