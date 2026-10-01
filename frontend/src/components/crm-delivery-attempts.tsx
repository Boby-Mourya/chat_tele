import { useState } from 'react';
import { Button } from '@/components/ui';
import { leadCrmApi, type CRMDeliveryAttemptView } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';

interface CRMDeliveryAttemptsProps {
  deliveryId: string;
  attemptCount: number;
}

function attemptError(attempt: CRMDeliveryAttemptView): string | null {
  if (attempt.normalized_error_code && attempt.provider_error_code) {
    return `${attempt.normalized_error_code} · ${attempt.provider_error_code}`;
  }
  return attempt.normalized_error_code ?? attempt.provider_error_code ?? null;
}

export function CRMDeliveryAttempts({ deliveryId, attemptCount }: CRMDeliveryAttemptsProps) {
  const [open, setOpen] = useState(false);
  const attempts = useApi(
    () => open
      ? leadCrmApi.deliveryAttempts(deliveryId)
      : Promise.resolve([] as CRMDeliveryAttemptView[]),
    [deliveryId, open],
  );

  return <div>
    <Button
      variant="secondary"
      size="sm"
      disabled={attemptCount === 0}
      aria-expanded={open}
      onClick={() => setOpen((value) => !value)}
    >
      {open ? 'Hide attempts' : `Attempts (${attemptCount})`}
    </Button>
    {open ? <div aria-label={`CRM delivery ${deliveryId} attempts`}>
      {attempts.loading ? <small>Loading delivery attempts…</small> : null}
      {attempts.error ? <div role="alert"><small>Could not load delivery attempts: {attempts.error}</small> <Button variant="secondary" size="sm" onClick={attempts.reload}>Retry load</Button></div> : null}
      {!attempts.loading && !attempts.error && attempts.data?.length ? <ol>
        {attempts.data.map((attempt) => {
          const error = attemptError(attempt);
          return <li key={attempt.id}>
            <strong>Attempt {attempt.attempt_number}</strong>
            <small>{attempt.result_status ?? 'unknown result'}</small>
            <small>HTTP {attempt.http_status ?? '—'} · {attempt.latency_ms == null ? 'latency unavailable' : `${attempt.latency_ms} ms`}</small>
            <small>Started {new Date(attempt.started_at).toLocaleString()}{attempt.finished_at ? ` · finished ${new Date(attempt.finished_at).toLocaleString()}` : ''}</small>
            {attempt.provider_request_id ? <small>Provider request: {attempt.provider_request_id}</small> : null}
            {error ? <small>Error: {error}</small> : null}
          </li>;
        })}
      </ol> : null}
      {!attempts.loading && !attempts.error && !attempts.data?.length ? <small>No persisted delivery attempts were found.</small> : null}
    </div> : null}
  </div>;
}
