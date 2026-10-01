import type { CRMDeliveryView } from '@/lib/lead-crm-api';

// Optional verification fields preserve compatibility with historical responses.
export type ObservableCRMDelivery = CRMDeliveryView & {
  verification_status?: string;
  verification_attempt_count?: number;
  next_verification_at?: string | null;
  verification_error_message?: string | null;
  verification_evidence?: Record<string, unknown>;
};

export function getVerificationView(delivery: ObservableCRMDelivery) {
  const state = delivery.verification_status;
  const evidence = delivery.verification_evidence;
  const proved = state === 'verified' && Boolean(delivery.verified_at) && evidence?.recordIdMatched === true;
  const fieldsProved = proved && evidence?.scope === 'mapped_fields';
  let label = 'Awaiting provider acknowledgement';
  if (delivery.acknowledged_at) label = 'Verification pending';
  if (state === 'unsupported') label = 'Read-back not supported';
  else if (state === 'failed') label = 'Verification failed';
  else if (state === 'auth_required') label = 'Reconnect to verify';
  else if (state === 'retrying') label = 'Verification retry scheduled';
  else if (proved) label = fieldsProved ? 'Mapped fields verified' : 'Record identity verified';
  else if (state === 'verified') label = 'Verification evidence unavailable';
  const verificationRetry = Boolean(delivery.acknowledged_at) && ['failed', 'auth_required', 'retrying'].includes(state ?? '');
  const writeRetry = !delivery.acknowledged_at && delivery.last_error_code !== 'ambiguous_provider_ack'
    && ['failed', 'dead_letter', 'mapping_error', 'auth_required', 'rate_limited'].includes(delivery.status);
  return {
    label,
    proved,
    error: delivery.verification_error_message ?? null,
    attempts: delivery.verification_attempt_count ?? 0,
    nextAttempt: delivery.next_verification_at ?? null,
    retryable: verificationRetry || writeRetry,
    retryLabel: verificationRetry ? 'Retry verification' : 'Retry',
  };
}
