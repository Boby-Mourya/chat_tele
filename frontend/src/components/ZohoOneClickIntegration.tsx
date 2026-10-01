import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Link2,
  RefreshCw,
  Route,
  Send,
  ShieldCheck,
  Unplug,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card } from '@/components/ui';
import {
  type ZohoOneClickStatus,
  zohoOneClickApi,
} from '@/lib/zoho-one-click-api';
import '@/components/ZohoOneClickIntegration.css';

function dateTime(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : 'Not completed';
}

function badgeTone(status: ZohoOneClickStatus): 'success' | 'warning' | 'danger' | 'neutral' | 'brand' {
  if (status.connected && status.liveCertification?.status === 'verified') return 'success';
  if (status.status === 'auth_required' || status.status === 'configuration_error') return 'danger';
  if (status.status === 'connecting' || status.status === 'degraded') return 'warning';
  return 'neutral';
}

export function ZohoOneClickIntegration() {
  const { pushToast } = useToast();
  const [status, setStatus] = useState<ZohoOneClickStatus>();
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [certifying, setCertifying] = useState(false);
  const [error, setError] = useState<string>();

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      setStatus(await zohoOneClickApi.status());
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load Zoho status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    const result = url.searchParams.get('crm');
    const provider = url.searchParams.get('provider');
    if (provider === 'zoho' && result) {
      if (result === 'connected') {
        const liveTest = url.searchParams.get('liveTest');
        pushToast(
          liveTest === 'verified'
            ? 'Zoho connected and the live lead was verified'
            : 'Zoho connected',
        );
      } else {
        pushToast(
          `Zoho connection failed: ${url.searchParams.get('reason') ?? 'authorization was not completed'}`,
          'error',
        );
      }
      ['crm', 'provider', 'connectionId', 'liveTest', 'externalRecordId', 'reason']
        .forEach((key) => url.searchParams.delete(key));
      window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
    }
    void loadStatus();
  }, [loadStatus, pushToast]);

  async function connect(): Promise<void> {
    setConnecting(true);
    setError(undefined);
    try {
      const result = await zohoOneClickApi.start();
      window.location.assign(result.authorizationUrl);
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : 'Could not start Zoho OAuth';
      setError(message);
      pushToast(message, 'error');
      setConnecting(false);
    }
  }

  async function certify(): Promise<void> {
    setCertifying(true);
    setError(undefined);
    try {
      const result = await zohoOneClickApi.certify();
      pushToast(
        result.liveTest === 'verified'
          ? `Live Zoho lead verified (${result.externalRecordId ?? 'external ID stored'})`
          : `Zoho certification completed with status ${result.liveTest}`,
      );
      await loadStatus();
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : 'Zoho certification failed';
      setError(message);
      pushToast(message, 'error');
    } finally {
      setCertifying(false);
    }
  }

  const certification = status?.liveCertification;
  const ready = Boolean(
    status?.connected
    && status.mappingReady
    && status.routeReady
    && status.autoSyncNewLeads
    && certification?.status === 'verified',
  );

  return <Card className="zoho-one-click">
    <div className="zoho-one-click__header">
      <div className="zoho-one-click__brand" aria-hidden="true">ZO</div>
      <div className="zoho-one-click__title">
        <small>Recommended CRM integration</small>
        <h2>Zoho CRM — one-click connection</h2>
        <p>
          Authorize once. Northstar creates the workspace connection, enables lead sync,
          discovers the live Leads schema, activates mapping and routing, sends a real
          certification lead, and verifies it by reading it back from Zoho.
        </p>
      </div>
      {status ? <Badge tone={badgeTone(status)}>
        {ready ? 'Live and verified' : status.status.replaceAll('_', ' ')}
      </Badge> : null}
    </div>

    {loading ? <div className="zoho-one-click__loading">
      <span className="button-spinner" aria-hidden="true" />
      Loading Zoho integration status…
    </div> : null}

    {!loading && status && !status.platformConfigured ? <div className="zoho-one-click__notice" role="alert">
      <AlertTriangle />
      <div>
        <strong>The platform Zoho OAuth application must be configured by the deployment owner.</strong>
        <p>
          Missing: {status.missingConfiguration.join(', ')}. End users never enter a Zoho
          password or OAuth client secret in this screen.
        </p>
      </div>
    </div> : null}

    {!loading && status ? <>
      <ol className="zoho-one-click__flow" aria-label="Zoho integration completion stages">
        <li className={status.connected ? 'is-complete' : ''}>
          <span><Link2 /></span><div><strong>OAuth connection</strong><small>Zoho consent and encrypted refresh token</small></div>
        </li>
        <li className={status.mappingReady ? 'is-complete' : ''}>
          <span><ShieldCheck /></span><div><strong>Schema and mapping</strong><small>Live Leads metadata and active field mapping</small></div>
        </li>
        <li className={status.routeReady && status.autoSyncNewLeads ? 'is-complete' : ''}>
          <span><Route /></span><div><strong>Automatic routing</strong><small>New leads and updates flow from this workspace</small></div>
        </li>
        <li className={certification?.status === 'verified' ? 'is-complete' : ''}>
          <span><Send /></span><div><strong>Live provider test</strong><small>Upsert, acknowledgement, external ID and read-back proof</small></div>
        </li>
      </ol>

      {status.connectionId ? <div className="zoho-one-click__details">
        <div><small>Connection</small><strong>{status.connectionName ?? status.connectionId}</strong></div>
        <div><small>Automatic new leads</small><strong>{status.autoSyncNewLeads ? 'Enabled' : 'Disabled'}</strong></div>
        <div><small>Automatic updates</small><strong>{status.autoSyncUpdates ? 'Enabled' : 'Disabled'}</strong></div>
        <div><small>Mapping</small><strong>{status.mappingReady ? `Active · v${status.mappingVersion ?? 1}` : 'Pending'}</strong></div>
        <div><small>Last provider success</small><strong>{dateTime(status.lastSuccessAt)}</strong></div>
        <div><small>Live certification</small><strong>{certification?.status ?? 'Not run'}</strong></div>
        {certification?.externalRecordId ? <div className="zoho-one-click__external">
          <small>Zoho external lead ID</small><strong>{certification.externalRecordId}</strong>
        </div> : null}
      </div> : null}

      {certification?.status === 'verified' ? <div className="zoho-one-click__verified">
        <CheckCircle2 />
        <div>
          <strong>End-to-end Zoho flow verified</strong>
          <p>
            Provider acknowledgement and read-back succeeded on {dateTime(certification.verifiedAt)}.
            Verified fields: {(certification.verifiedFields ?? []).join(', ') || 'record identity'}.
          </p>
        </div>
      </div> : null}

      {status.lastError || error ? <div className="zoho-one-click__error" role="alert">
        <AlertTriangle /><span>{error ?? status.lastError}</span>
      </div> : null}

      <div className="zoho-one-click__actions">
        <Button
          icon={status.connected ? RefreshCw : Link2}
          disabled={!status.platformConfigured || connecting}
          onClick={() => void connect()}
        >
          {connecting ? 'Opening Zoho…' : status.connected ? 'Reconnect Zoho' : 'Connect Zoho'}
        </Button>
        {status.connected ? <Button
          variant="secondary"
          icon={ShieldCheck}
          disabled={certifying}
          onClick={() => void certify()}
        >
          {certifying ? 'Testing live flow…' : 'Run live verification'}
        </Button> : null}
        <Button variant="ghost" icon={RefreshCw} disabled={loading} onClick={() => void loadStatus()}>
          Refresh status
        </Button>
        {certification?.externalRecordId ? <span className="zoho-one-click__record">
          <ExternalLink /> External record stored locally
        </span> : null}
      </div>
    </> : null}

    {!loading && !status ? <div className="zoho-one-click__empty">
      <Unplug /><span>{error ?? 'Zoho integration status is unavailable.'}</span>
      <Button variant="secondary" onClick={() => void loadStatus()}>Retry</Button>
    </div> : null}
  </Card>;
}
