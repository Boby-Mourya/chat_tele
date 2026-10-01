import { Activity, CircleAlert, RefreshCw, Send } from 'lucide-react';
import { useState } from 'react';
import { ChannelOutboundDeliveriesPanel } from '@/components/channel-outbound-deliveries-panel';
import { ChannelWebhookEventsPanel } from '@/components/channel-webhook-events-panel';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import { channelOperationsApi } from '@/lib/channel-operations-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';

function overallTone(status: string): 'success' | 'warning' | 'brand' | 'neutral' {
  if (status === 'healthy') return 'success';
  if (status === 'attention') return 'warning';
  if (status === 'active') return 'brand';
  return 'neutral';
}

function connectionTone(status: string, failed: number): 'success' | 'warning' | 'brand' | 'neutral' {
  if (failed > 0 || ['degraded', 'unhealthy', 'auth_required', 'configuration_error', 'reconnect_required', 'disabled'].includes(status)) return 'warning';
  if (['connecting', 'configured', 'rate_limited', 'unknown'].includes(status)) return 'brand';
  if (status === 'healthy') return 'success';
  return 'neutral';
}

export function ChannelOperationalHealthPanel() {
  const health = useApi(() => channelOperationsApi.health());
  const [showDeliveries, setShowDeliveries] = useState(false);
  const [showWebhookEvents, setShowWebhookEvents] = useState(false);
  const data = health.data;
  const deliveryConnections = data?.connections.map((connection) => ({
    id: connection.connection_id,
    name: connection.name,
    provider: connection.provider,
  })) ?? [];

  return <>
    <Card>
      <div className="page-heading page-heading--split">
        <div>
          <h3>Channel operational health</h3>
          <p>Current Workspace view of provider-neutral channel health, inbound webhook processing, outbound backlog, automatic retries, and terminal failures.</p>
        </div>
        <div>
          {data ? <Badge tone={overallTone(data.overall_status)}>{data.overall_status}</Badge> : null}{' '}
          <Button variant="secondary" size="sm" icon={RefreshCw} disabled={health.loading} onClick={health.reload}>Refresh</Button>
        </div>
      </div>

      {health.loading && !data ? <p>Loading channel operational health…</p> : health.error ? <EmptyState
        icon={CircleAlert}
        title="Channel operational health is unavailable"
        description={health.error}
        action={<Button variant="secondary" onClick={health.reload}>Try again</Button>}
      /> : !data || data.overall_status === 'empty' ? <EmptyState
        icon={Activity}
        title="No channel operations to monitor"
        description="Connect a provider-neutral messaging channel in this Workspace to begin monitoring delivery health."
      /> : <>
        <div className="leads-stats">
          <Card><span><Activity /></span><div><strong>{data.connection_count}</strong><small>Channel connections</small></div></Card>
          <Card><span><Send /></span><div><strong>{data.pending_deliveries}</strong><small>Pending deliveries</small></div></Card>
          <Card><span><RefreshCw /></span><div><strong>{data.retrying_deliveries}</strong><small>Retrying</small></div></Card>
          <Card><span><CircleAlert /></span><div><strong>{data.failed_deliveries}</strong><small>Terminal failures</small></div></Card>
          <Card><span><Activity /></span><div><strong>{data.pending_webhook_events}</strong><small>Inbound pending</small></div></Card>
          <Card><span><CircleAlert /></span><div><strong>{data.failed_webhook_events}</strong><small>Inbound failed</small></div></Card>
          <Card><span><Activity /></span><div><strong>{data.rejected_webhook_events}</strong><small>Inbound rejected</small></div></Card>
          <Card><span><CircleAlert /></span><div><strong>{data.stale_webhook_events}</strong><small>Inbound stale</small></div></Card>
        </div>

        <div className="leads-table-wrap"><table className="leads-table">
          <thead><tr><th>Channel</th><th>Status</th><th>Pending</th><th>Retrying</th><th>Failed</th><th>Inbound pending</th><th>Inbound failed</th><th>Inbound rejected</th><th>Inbound stale</th><th>Last activity</th></tr></thead>
          <tbody>{data.connections.map((connection) => <tr key={connection.connection_id}>
            <td><strong>{connection.name}</strong><small>{connection.provider}</small></td>
            <td><Badge tone={connectionTone(connection.status, connection.failed_deliveries + connection.failed_webhook_events + connection.stale_webhook_events)}>{connection.status}</Badge>{connection.last_error ? <small>{connection.last_error}</small> : null}</td>
            <td>{connection.pending_deliveries}</td>
            <td>{connection.retrying_deliveries}</td>
            <td>{connection.failed_deliveries}</td>
            <td>{connection.pending_webhook_events}</td>
            <td>{connection.failed_webhook_events}</td>
            <td>{connection.rejected_webhook_events}</td>
            <td>{connection.stale_webhook_events}</td>
            <td>
              {connection.last_event_at ? <small>Event {relativeTime(connection.last_event_at)}</small> : null}
              {connection.last_failure_at ? <small>Failure {relativeTime(connection.last_failure_at)}</small> : null}
              {!connection.last_event_at && !connection.last_failure_at && connection.last_health_at ? <small>Health check {relativeTime(connection.last_health_at)}</small> : null}
              {!connection.last_event_at && !connection.last_failure_at && !connection.last_health_at ? <small>No activity yet</small> : null}
            </td>
          </tr>)}</tbody>
        </table></div>
        {data.failed_deliveries > 0 || data.failed_webhook_events > 0 || data.stale_webhook_events > 0 ? <p role="status"><strong>Attention required:</strong> {data.failed_deliveries} terminal outbound delivery failure state(s), {data.failed_webhook_events} failed inbound webhook event(s), and {data.stale_webhook_events} stale inbound webhook event(s) are visible in this Workspace.</p> : null}
        {!showDeliveries ? <div className="page-heading page-heading--split">
          <div><h4>Outbound delivery evidence</h4><p>Open the safe delivery view for individual retry and terminal-failure evidence.</p></div>
          <Button variant="secondary" onClick={() => setShowDeliveries(true)}>View delivery evidence</Button>
        </div> : null}
        {!showWebhookEvents ? <div className="page-heading page-heading--split">
          <div><h4>Inbound webhook evidence</h4><p>Open the safe inbound processing view without exposing raw provider payloads, headers, messages, or credentials.</p></div>
          <Button variant="secondary" onClick={() => setShowWebhookEvents(true)}>View webhook activity</Button>
        </div> : null}
      </>}
    </Card>

    {showDeliveries ? <ChannelOutboundDeliveriesPanel connections={deliveryConnections} /> : null}
    {showWebhookEvents ? <ChannelWebhookEventsPanel connections={deliveryConnections} /> : null}
  </>;
}
