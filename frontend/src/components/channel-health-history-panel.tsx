import { Activity, CircleAlert, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import { channelHealthHistoryApi } from '@/lib/channel-health-history-api';
import { relativeTime } from '@/lib/format';
import type { ChannelConnectionView } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';

function statusTone(status: string): 'success' | 'warning' | 'brand' | 'neutral' {
  if (status === 'healthy') return 'success';
  if (['unhealthy', 'degraded', 'auth_required', 'configuration_error'].includes(status)) return 'warning';
  if (status === 'rate_limited') return 'brand';
  return 'neutral';
}

interface ChannelHealthHistoryPanelProps {
  connections: ChannelConnectionView[];
}

export function ChannelHealthHistoryPanel({ connections }: ChannelHealthHistoryPanelProps) {
  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? '');

  useEffect(() => {
    if (!connections.some((connection) => connection.id === connectionId)) {
      setConnectionId(connections[0]?.id ?? '');
    }
  }, [connections, connectionId]);

  const history = useApi(
    () => connectionId ? channelHealthHistoryApi.list(connectionId, 50) : Promise.resolve([]),
    [connectionId],
  );

  if (connections.length === 0) {
    return <Card><EmptyState
      icon={Activity}
      title="No channel health history yet"
      description="Connect a messaging channel in this Workspace before scheduled health snapshots can be recorded."
    /></Card>;
  }

  return <Card>
    <div className="page-heading page-heading--split">
      <div>
        <h3>Channel health history</h3>
        <p>Review safe scheduled connection status history for this Workspace. Provider payloads, headers, identities, and credentials are never shown here.</p>
      </div>
      <Button variant="secondary" size="sm" icon={RefreshCw} disabled={history.loading} onClick={history.reload}>Refresh history</Button>
    </div>

    <div className="integration-toolbar">
      <label>
        Channel connection
        <select aria-label="Channel health history connection" value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>
          {connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name} · {connection.provider}</option>)}
        </select>
      </label>
    </div>

    {history.loading && !history.data ? <p>Loading channel health history…</p> : history.error && !history.data ? <EmptyState
      icon={CircleAlert}
      title="Channel health history is unavailable"
      description={history.error}
      action={<Button variant="secondary" onClick={history.reload}>Try again</Button>}
    /> : !history.data?.length ? <EmptyState
      icon={Activity}
      title="No scheduled health checks recorded"
      description="The scheduled channel health monitor will add safe historical snapshots after connection checks run."
    /> : <div className="leads-table-wrap"><table className="leads-table">
      <thead><tr><th>Checked</th><th>Status</th><th>Normalized error</th></tr></thead>
      <tbody>{history.data.map((snapshot) => <tr key={snapshot.id}>
        <td><strong>{new Date(snapshot.checked_at).toLocaleString()}</strong><small>{relativeTime(snapshot.checked_at)}</small></td>
        <td><Badge tone={statusTone(snapshot.status)}>{snapshot.status}</Badge></td>
        <td>{snapshot.error_code ? <code>{snapshot.error_code}</code> : '—'}</td>
      </tr>)}</tbody>
    </table></div>}
  </Card>;
}
