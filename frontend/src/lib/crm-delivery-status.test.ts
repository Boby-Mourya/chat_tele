import { describe, expect, it } from 'vitest';
import { getVerificationView, type ObservableCRMDelivery } from '@/lib/crm-delivery-status';

const delivery: ObservableCRMDelivery = {
  id: 'delivery-1', lead_id: 'lead-1', connection_id: 'connection-1', provider: 'generic_rest',
  operation: 'upsert', status: 'acknowledged', attempt_count: 1,
  acknowledged_at: '2026-09-08T10:00:00Z', created_at: '2026-09-08T09:59:00Z',
};

describe('CRM delivery verification presentation', () => {
  it('does not treat provider acknowledgement as verified', () => {
    expect(getVerificationView(delivery)).toMatchObject({ proved: false, label: 'Verification pending', retryable: false });
  });
  it('does not imply read-back support for a webhook-only destination', () => {
    expect(getVerificationView({ ...delivery, verification_status: 'unsupported' }))
      .toMatchObject({ proved: false, label: 'Read-back not supported', retryable: false });
  });
  it('offers a GET-only verification retry after an acknowledged write', () => {
    expect(getVerificationView({ ...delivery, verification_status: 'failed', verification_attempt_count: 5 }))
      .toMatchObject({ proved: false, attempts: 5, retryable: true, retryLabel: 'Retry verification' });
  });
  it('requires positive evidence and a verification timestamp', () => {
    expect(getVerificationView({ ...delivery, verification_status: 'verified' }).proved).toBe(false);
    expect(getVerificationView({ ...delivery, verification_status: 'verified', verified_at: delivery.acknowledged_at,
      verification_evidence: { recordIdMatched: true, scope: 'record_identity' } }))
      .toMatchObject({ proved: true, label: 'Record identity verified' });
  });
  it('distinguishes mapped-field proof from identity-only proof', () => {
    expect(getVerificationView({ ...delivery, verification_status: 'verified', verified_at: delivery.acknowledged_at,
      verification_evidence: { recordIdMatched: true, scope: 'mapped_fields', fieldsCompared: ['email'] } }))
      .toMatchObject({ proved: true, label: 'Mapped fields verified' });
  });
  it('does not offer another write for an ambiguous provider acknowledgement', () => {
    expect(getVerificationView({ ...delivery, acknowledged_at: null, status: 'failed', last_error_code: 'ambiguous_provider_ack' }).retryable).toBe(false);
  });
  it('retains normal retry for a failed unacknowledged write', () => {
    expect(getVerificationView({ ...delivery, acknowledged_at: null, status: 'dead_letter' }))
      .toMatchObject({ retryable: true, retryLabel: 'Retry' });
  });
});
