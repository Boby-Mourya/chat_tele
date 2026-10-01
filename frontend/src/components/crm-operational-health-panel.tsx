import { Activity, CircleAlert, RefreshCw } from 'lucide-react';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import { crmOperationsApi } from '@/lib/crm-operations-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';

function overallTone(status: string): 'success' | 'warning' | 'brand' | 'neutral' {
  if (status === 'healthy') return 'success';
  if (status === 'attention') return 'warning';
  if (status === 'active') return 'brand';
  return 'neutral';
}

function connectionTone(status: string, failed: number, deadLetters: number): 'success' | 'warning' | 'brand' | 'neutral' {
  if (failed > 0 || deadLetters > 0 || ['degraded', 'unhealthy', 'auth_required', 'configuration_error', 'disabled'].includes(status)) return 'warning';
  if (['connecting', 'rate_limited'].includes(status)) return 'brand';
  if (status === 'healthy') return 'success';
  return 'neutral';
}

export function CRMOperationalHealthPanel() {
  const health = useApi(() => crmOperationsApi.health());
  const data = health.data;

  return <Card>
    <div className="page-heading page-heading--split">
      <div>
        <h3>CRM operational health</h3>
        <p>Current Workspace view of connection health, delivery backlog, retries, failures, and unresolved dead-letter incidents.</p>
      </div>
      <div>
        {data ? <Badge tone={overallTone(data.overall_status)}>{data.overall_status}</Badge> : null}{' '}
        <Button variant="secondary" size="sm" icon={RefreshCw} disabled={health.loading} onClick={health.reload}>Refresh</Button>
      </div>
    </div>

    {health.loading && !data ? <p>Loading CRM operational health…</p> : health.error ? <EmptyState
      icon={CircleAlert}
      title="CRM operational health is unavailable"
      description={health.error}
      action={<Button variant="secondary" onClick={health.reload}>Try again</Button>}
    /> : !data || data.overall_status === 'empty' ? <EmptyState
      icon={Activity}
      title="No CRM operations to monitor"
      description="Connect a CRM in this Workspace to begin monitoring delivery health."
    /> : <>
      <div className="leads-stats">
        <Card><span><Activity /></span><div><strong>{data.connection_count}</strong><small>CRM connections</small></div></Card>
        <Card><span><Activity /></span><div><strong>{data.pending_deliveries}</strong><small>Pending deliveries</small></div></Card>
        <Card><span><RefreshCw /></span><div><strong>{data.retrying_deliveries}</strong><small>Retrying</small></div></Card>
        <Card><span><CircleAlert /></span><div><strong>{data.open_dead_letters}</strong><small>Open dead letters</small></div></Card>
      </div>

      <div className="leads-table-wrap"><table className="leads-table">
        <thead><tr><th>CRM</th><th>Status</th><th>Pending</th><th>Retrying</th><th>Failed</th><th>Dead letters</th><th>Last activity</th></tr></thead>
        <tbody>{data.connections.map((connection) => <tr key={connection.connection_id}>
          <td><strong>{connection.name}</strong><small>{connection.provider}</small></td>
          <td><Badge tone={connectionTone(connection.status, connection.failed_deliveries, connection.open_dead_letters)}>{connection.status}</Badge>{connection.last_error ? <small>{connection.last_error}</small> : null}</td>
          <td>{connection.pending_deliveries}</td>
          <td>{connection.retrying_deliveries}</td>
          <td>{connection.failed_deliveries}</td>
          <td>{connection.open_dead_letters}</td>
          <td>
            {connection.last_success_at ? <small>Success {relativeTime(connection.last_success_at)}</small> : null}
            {connection.last_failure_at ? <small>Failure {relativeTime(connection.last_failure_at)}</small> : null}
            {!connection.last_success_at && !connection.last_failure_at && connection.last_health_at ? <small>Health check {relativeTime(connection.last_health_at)}</small> : null}
            {!connection.last_success_at && !connection.last_failure_at && !connection.last_health_at ? <small>No activity yet</small> : null}
          </td>
        </tr>)}</tbody>
      </table></div>
      {data.failed_deliveries > 0 || data.open_dead_letters > 0 ? <p role="status"><strong>Attention required:</strong> {data.failed_deliveries} failed delivery state(s) and {data.open_dead_letters} unresolved dead-letter incident(s) are visible in this Workspace.</p> : null}
    </>}
  </Card>;
}
