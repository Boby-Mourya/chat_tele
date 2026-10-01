import { Activity, CircleAlert, RefreshCw } from 'lucide-react';
import { Badge, Button, EmptyState } from '@/components/ui';
import { channelDeliveriesApi } from '@/lib/channel-deliveries-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';

function outcomeTone(outcome: string): 'success' | 'warning' | 'brand' | 'neutral' {
  if (['sent', 'published'].includes(outcome)) return 'success';
  if (['rejected', 'reconnect_required', 'cancelled', 'publish_failed'].includes(outcome)) return 'warning';
  if (outcome === 'failed') return 'brand';
  return 'neutral';
}

interface ChannelDeliveryAttemptsPanelProps {
  deliveryId: string;
  onClose: () => void;
}

export function ChannelDeliveryAttemptsPanel({ deliveryId, onClose }: ChannelDeliveryAttemptsPanelProps) {
  const attempts = useApi(() => channelDeliveriesApi.attempts(deliveryId, 100), [deliveryId]);

  return <div>
    <div className="page-heading page-heading--split">
      <div>
        <h4>Delivery attempt history</h4>
        <p>Safe dispatch and provider-send evidence for delivery <code>{deliveryId}</code>. Raw provider responses, recipients, message content and credentials are not exposed.</p>
      </div>
      <div>
        <Button variant="secondary" size="sm" icon={RefreshCw} disabled={attempts.loading} onClick={attempts.reload}>Refresh attempts</Button>{' '}
        <Button variant="secondary" size="sm" onClick={onClose}>Close attempts</Button>
      </div>
    </div>

    {attempts.loading && !attempts.data ? <p>Loading delivery attempt history…</p> : attempts.error && !attempts.data ? <EmptyState
      icon={CircleAlert}
      title="Delivery attempt history is unavailable"
      description={attempts.error}
      action={<Button variant="secondary" onClick={attempts.reload}>Try again</Button>}
    /> : !attempts.data?.length ? <EmptyState
      icon={Activity}
      title="No attempt history found"
      description="No completed broker-dispatch or provider-send attempt evidence has been recorded for this delivery yet."
    /> : <div className="leads-table-wrap"><table className="leads-table">
      <thead><tr><th>Recorded</th><th>Phase</th><th>Attempt</th><th>Outcome</th><th>Normalized error</th></tr></thead>
      <tbody>{attempts.data.map((attempt) => <tr key={attempt.id}>
        <td><strong>{new Date(attempt.created_at).toLocaleString()}</strong><small>{relativeTime(attempt.created_at)}</small></td>
        <td>{attempt.phase}</td>
        <td>{attempt.attempt_number}</td>
        <td><Badge tone={outcomeTone(attempt.outcome)}>{attempt.outcome}</Badge></td>
        <td>{attempt.error_code ? <code>{attempt.error_code}</code> : '—'}</td>
      </tr>)}</tbody>
    </table></div>}
  </div>;
}
