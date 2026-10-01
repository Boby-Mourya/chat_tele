import { CircleAlert, RefreshCw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useAuth } from '@/components/providers';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import { channelWebhookEventsApi } from '@/lib/channel-webhook-events-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';

export interface ChannelWebhookConnectionOption {
  id: string;
  name: string;
  provider: string;
}

interface ChannelWebhookEventsPanelProps {
  connections: ChannelWebhookConnectionOption[];
}

function statusTone(status: string): 'success' | 'warning' | 'brand' | 'neutral' {
  if (status === 'processed') return 'success';
  if (status === 'received') return 'brand';
  if (status === 'ignored') return 'neutral';
  return 'warning';
}

export function ChannelWebhookEventsPanel({ connections }: ChannelWebhookEventsPanelProps) {
  const { session } = useAuth();
  const canManage = session?.user.role === 'owner' || session?.user.role === 'admin';
  const [connectionId, setConnectionId] = useState('');
  const [processingStatus, setProcessingStatus] = useState('');
  const [provider, setProvider] = useState('');
  const [actionId, setActionId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const events = useApi(
    () => channelWebhookEventsApi.list({
      connectionId: connectionId || undefined,
      processingStatus: processingStatus || undefined,
      provider: provider || undefined,
      limit: 100,
    }),
    [connectionId, processingStatus, provider],
  );
  const connectionNames = useMemo(
    () => new Map(connections.map((connection) => [connection.id, connection.name])),
    [connections],
  );
  const providers = useMemo(
    () => [...new Set(connections.map((connection) => connection.provider))].sort(),
    [connections],
  );
  const rows = events.data ?? [];

  const requeue = async (eventId: string) => {
    setActionId(eventId);
    setActionMessage(null);
    setActionError(null);
    try {
      await channelWebhookEventsApi.requeue(eventId);
      setActionMessage('Failed webhook requeued through the existing channel event pipeline.');
      events.reload();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not requeue channel webhook');
    } finally {
      setActionId(null);
    }
  };

  return <Card>
    <div className="page-heading page-heading--split">
      <div>
        <h3>Channel inbound webhook activity</h3>
        <p>Inspect safe Workspace processing evidence for provider-neutral inbound channel events. Raw payloads, headers, external event IDs, message content, provider errors, and credentials are never shown here.</p>
      </div>
      <Badge tone={rows.some((item) => item.processing_status === 'received') ? 'brand' : 'neutral'}>
        {rows.length} event{rows.length === 1 ? '' : 's'}
      </Badge>
    </div>

    <div className="integration-toolbar">
      <label>
        Processing status
        <select aria-label="Channel webhook processing status" value={processingStatus} onChange={(event) => setProcessingStatus(event.target.value)}>
          <option value="">All statuses</option>
          <option value="received">Received</option>
          <option value="processed">Processed</option>
          <option value="ignored">Ignored</option>
          <option value="rejected">Rejected</option>
          <option value="failed">Failed</option>
        </select>
      </label>
      <label>
        Provider
        <select aria-label="Channel webhook provider" value={provider} onChange={(event) => setProvider(event.target.value)}>
          <option value="">All providers</option>
          {providers.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      <label>
        Channel connection
        <select aria-label="Channel webhook connection" value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>
          <option value="">All Workspace connections</option>
          {connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name} · {connection.provider}</option>)}
        </select>
      </label>
      <Button variant="secondary" size="sm" icon={RefreshCw} disabled={events.loading} onClick={events.reload}>Refresh</Button>
    </div>

    {actionMessage ? <p role="status">{actionMessage}</p> : null}
    {actionError ? <p role="alert">{actionError}</p> : null}

    {events.loading && !events.data ? <p>Loading channel webhook activity…</p> : events.error ? (
      <EmptyState
        icon={CircleAlert}
        title="Channel webhook activity is unavailable"
        description={events.error}
        action={<Button variant="secondary" onClick={events.reload}>Try again</Button>}
      />
    ) : rows.length ? <div className="leads-table-wrap"><table className="leads-table">
      <thead><tr><th>Status</th><th>Channel</th><th>Event</th><th>Verification</th><th>Attempts</th><th>Received</th><th>Processing evidence</th><th>Action</th></tr></thead>
      <tbody>{rows.map((item) => <tr key={item.id}>
        <td><Badge tone={statusTone(item.processing_status)}>{item.processing_status}</Badge></td>
        <td>{connectionNames.get(item.connection_id) ?? item.connection_id}<small>{item.provider}</small></td>
        <td>{item.event_type}<small>Correlation {item.correlation_id}</small></td>
        <td>{item.verification_status}</td>
        <td>{item.attempt_count}</td>
        <td><time dateTime={item.received_at}>{relativeTime(item.received_at)}</time></td>
        <td>{item.processed_at ? <small>Processed {relativeTime(item.processed_at)}</small> : <small>Awaiting processing</small>}{item.error_code ? <small><code>{item.error_code}</code></small> : null}</td>
        <td>{canManage && item.can_requeue ? <Button
          variant="secondary"
          size="sm"
          disabled={actionId === item.id}
          onClick={() => void requeue(item.id)}
        >{actionId === item.id ? 'Requeueing…' : 'Requeue event'}</Button> : '—'}</td>
      </tr>)}</tbody>
    </table></div> : <EmptyState
      icon={CircleAlert}
      title="No channel webhook events found"
      description="No inbound channel webhook events match the current Workspace filters."
    />}
  </Card>;
}
