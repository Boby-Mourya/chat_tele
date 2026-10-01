import { Activity, CircleAlert, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import { leadCrmApi, type CRMConnectionView } from '@/lib/lead-crm-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';

function statusTone(status: string): 'success' | 'warning' | 'brand' | 'neutral' {
  if (status === 'healthy') return 'success';
  if (['unhealthy', 'degraded', 'auth_required', 'configuration_error'].includes(status)) return 'warning';
  if (['connecting', 'rate_limited'].includes(status)) return 'brand';
  return 'neutral';
}

interface CRMHealthHistoryPanelProps {
  connections: CRMConnectionView[];
  canManage: boolean;
}

export function CRMHealthHistoryPanel({ connections, canManage }: CRMHealthHistoryPanelProps) {
  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? '');
  const [checking, setChecking] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!connections.some((connection) => connection.id === connectionId)) {
      setConnectionId(connections[0]?.id ?? '');
    }
  }, [connections, connectionId]);

  const history = useApi(
    () => connectionId ? leadCrmApi.healthHistory(connectionId, 50) : Promise.resolve([]),
    [connectionId],
  );

  const runHealthCheck = async () => {
    if (!connectionId || checking) return;
    setChecking(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const snapshot = await leadCrmApi.runHealthCheck(connectionId);
      setActionMessage(`Recorded ${snapshot.status} health check.`);
      history.reload();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'CRM health check failed');
      history.reload();
    } finally {
      setChecking(false);
    }
  };

  if (connections.length === 0) {
    return <Card><EmptyState
      icon={Activity}
      title="No CRM health history yet"
      description="Connect a CRM in this Workspace before recording health-check history."
    /></Card>;
  }

  return <Card>
    <div className="page-heading page-heading--split">
      <div>
        <h3>CRM health history</h3>
        <p>Run a recorded connection check and review safe historical status, latency, and check evidence for this Workspace.</p>
      </div>
      <div>
        <Button variant="secondary" size="sm" icon={RefreshCw} disabled={history.loading} onClick={history.reload}>Refresh history</Button>{' '}
        {canManage ? <Button size="sm" disabled={checking || !connectionId} onClick={() => void runHealthCheck()}>{checking ? 'Checking…' : 'Run recorded check'}</Button> : null}
      </div>
    </div>

    <div className="integration-toolbar">
      <label>
        CRM connection
        <select aria-label="CRM health history connection" value={connectionId} onChange={(event) => { setActionError(null); setActionMessage(null); setConnectionId(event.target.value); }}>
          {connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name} · {connection.provider}</option>)}
        </select>
      </label>
    </div>

    {actionMessage ? <p role="status">{actionMessage}</p> : null}
    {actionError ? <p role="alert">{actionError}</p> : null}

    {history.loading && !history.data ? <p>Loading CRM health history…</p> : history.error && !history.data ? <EmptyState
      icon={CircleAlert}
      title="CRM health history is unavailable"
      description={history.error}
      action={<Button variant="secondary" onClick={history.reload}>Try again</Button>}
    /> : !history.data?.length ? <EmptyState
      icon={Activity}
      title="No recorded health checks"
      description={canManage ? 'Run a recorded check to create the first safe historical snapshot.' : 'A Workspace admin can run a recorded check to create history.'}
    /> : <div className="leads-table-wrap"><table className="leads-table">
      <thead><tr><th>Checked</th><th>Status</th><th>Latency</th><th>Safe checks</th></tr></thead>
      <tbody>{history.data.map((snapshot) => <tr key={snapshot.id}>
        <td><strong>{new Date(snapshot.checked_at).toLocaleString()}</strong><small>{relativeTime(snapshot.checked_at)}</small></td>
        <td><Badge tone={statusTone(snapshot.status)}>{snapshot.status}</Badge></td>
        <td>{snapshot.latency_ms == null ? '—' : `${snapshot.latency_ms} ms`}</td>
        <td>{Object.keys(snapshot.checks).length ? <div>{Object.entries(snapshot.checks).map(([key, value]) => <small key={key}><strong>{key}:</strong> {value}</small>)}</div> : <small>No check details recorded</small>}</td>
      </tr>)}</tbody>
    </table></div>}
  </Card>;
}
