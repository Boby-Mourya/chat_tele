import { CircleAlert, RefreshCw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import { crmWebhookEventsApi } from '@/lib/crm-webhook-events-api';
import type { CRMConnectionView } from '@/lib/lead-crm-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';

interface CRMWebhookEventsPanelProps {
  connections: CRMConnectionView[];
}

function statusTone(status: string): 'success' | 'warning' | 'brand' | 'neutral' {
  if (status === 'processed') return 'success';
  if (status === 'received') return 'brand';
  if (status === 'ignored') return 'neutral';
  return 'warning';
}

export function CRMWebhookEventsPanel({ connections }: CRMWebhookEventsPanelProps) {
  const [connectionId, setConnectionId] = useState('');
  const [processingStatus, setProcessingStatus] = useState('');
  const events = useApi(
    () => crmWebhookEventsApi.list({
      connectionId: connectionId || undefined,
      processingStatus: processingStatus || undefined,
      limit: 100,
    }),
    [connectionId, processingStatus],
  );
  const connectionNames = useMemo(
    () => new Map(connections.map((connection) => [connection.id, connection.name])),
    [connections],
  );
  const rows = events.data ?? [];

  return <Card>
    <div className="page-heading page-heading--split">
      <div>
        <h3>CRM inbound webhook activity</h3>
        <p>Inspect safe processing evidence for inbound CRM events. Raw webhook payloads and headers are never shown here.</p>
      </div>
      <Badge tone={rows.some((item) => item.processing_status === 'received') ? 'brand' : 'neutral'}>
        {rows.length} event{rows.length === 1 ? '' : 's'}
      </Badge>
    </div>

    <div className="integration-toolbar">
      <label>
        Processing status
        <select aria-label="CRM webhook processing status" value={processingStatus} onChange={(event) => setProcessingStatus(event.target.value)}>
          <option value="">All statuses</option>
          <option value="received">Received</option>
          <option value="processed">Processed</option>
          <option value="ignored">Ignored</option>
        </select>
      </label>
      <label>
        CRM connection
        <select aria-label="CRM webhook connection" value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>
          <option value="">All CRM connections</option>
          {connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name}</option>)}
        </select>
      </label>
      <Button variant="secondary" size="sm" icon={RefreshCw} disabled={events.loading} onClick={events.reload}>Refresh</Button>
    </div>

    {events.loading && !events.data ? <p>Loading CRM webhook activity…</p> : events.error ? (
      <EmptyState
        icon={CircleAlert}
        title="CRM webhook activity is unavailable"
        description={events.error}
        action={<Button variant="secondary" onClick={events.reload}>Try again</Button>}
      />
    ) : rows.length ? <div className="leads-table-wrap"><table className="leads-table">
      <thead><tr><th>Status</th><th>CRM</th><th>Event</th><th>Verification</th><th>Received</th><th>Processing evidence</th></tr></thead>
      <tbody>{rows.map((item) => <tr key={item.id}>
        <td><Badge tone={statusTone(item.processing_status)}>{item.processing_status}</Badge></td>
        <td>{connectionNames.get(item.connection_id) ?? item.connection_id}<small>{item.provider}</small></td>
        <td>{item.event_type}<small>Correlation {item.correlation_id}</small></td>
        <td>{item.verification_status}</td>
        <td><time dateTime={item.received_at}>{relativeTime(item.received_at)}</time></td>
        <td>{item.processed_at ? <small>Processed {relativeTime(item.processed_at)}</small> : <small>Awaiting processing</small>}{item.last_error ? <small>{item.last_error}</small> : null}</td>
      </tr>)}</tbody>
    </table></div> : <EmptyState
      icon={CircleAlert}
      title="No CRM webhook events found"
      description="No inbound CRM webhook events match the current Workspace filters."
    />}
  </Card>;
}
