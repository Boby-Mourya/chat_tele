# CRM delivery verification and recovery

This runbook covers the implemented delivery/verification hardening only. The full Lead/Omnichannel/Any-CRM module remains in progress and release-blocked; see [the implementation tracker](../lead-crm-implementation-status.md).

## Evidence and deployment boundary

Code commit `f650e7379e990d380e0eb2de2e2613eba371a34a` passed [CI run 34257700348](https://github.com/ooarchitect92/Chat/actions/runs/34257700348), including the disposable Docker topology, migration `0010_crm_verification`, and CRM API/column checks. This does not mean a customer or production environment has been migrated or deployed. CodeQL publication and broader acceptance remain open.

Before an approved deployment, take and test a recoverable database backup, rehearse the complete upgrade with representative existing records, review the migration, and ensure API and all CRM workers use the same release and encryption-key configuration. Retain encryption keys through backup/recovery. Do not rotate an encryption key by replacing it without a supported re-encryption/migration procedure.

## Read the states separately

| Evidence | Meaning | What it does not prove |
|---|---|---|
| Queued/processing | A durable delivery is awaiting or attempting a write | Remote provider acceptance |
| `acknowledged_at` | The provider acceptance was persisted locally | Read-back or matching business fields |
| `verification_status=pending/retrying` | A separate read-back is due | A need to resend the original write |
| `verification_status=unsupported` | The connector has no supported read-back | Verification success |
| `verification_status=failed/auth_required` | Read-back needs intervention | That the acknowledged remote write failed |
| `verified_at` plus positive `verification_evidence` | Record identity was matched, plus explicitly configured comparison fields when present | Every possible remote field is correct |

Default verification scope is `record_identity`. `mapped_fields` additionally compares the configured payload paths to read-back paths. The UI must never infer positive verification solely from a 2xx write response, an old status string, or an empty GET response.

## Configure optional field verification

A connection configuration may contain `readBackIdPath` and `verificationFields`. For example, a connector whose GET response wraps properties may use:

```json
{
  "readBackIdPath": "id",
  "verificationFields": {
    "email": "properties.email"
  },
  "verificationMaxAttempts": 5
}
```

The left side refers to the frozen transmitted payload; the right side refers to the returned record. Match paths and semantics to the actual provider contract. Missing or unequal values do not count as proof. Evidence retains field names and comparison scope rather than the whole provider response. Do not put credentials in public connection configuration.

## Retry an acknowledged delivery

Inspect the provider ACK, external record ID, verification status/error/attempts, last health and activity. Correct expired credentials or configuration through approved administration. An admin may request:

```text
POST /api/v1/crm/deliveries/{delivery_id}/retry
```

For an acknowledged delivery in a retryable verification state, this queues verification only. The verification cycle budget resets; total verification attempts remain historical. The worker must not issue another create/update as a consequence of that GET retry. The UI labels this action **Retry verification**.

An unsupported-read-back connector remains acknowledged; it is not a failed verification that should be made green by changing status in the database.

## Retry an unacknowledged write

The same admin endpoint checks the persisted state before scheduling a write retry. Correct the underlying mapping, credential or provider problem first. A payload already frozen for a delivery is not silently rebuilt during retries. A changed lead/mapping should be routed as a new delivery rather than mutating the evidence of an earlier attempt.

A prior provider acceptance followed by failed local ACK persistence can leave `last_error_code=ambiguous_provider_ack`. Automatic and blind manual resend are blocked. Reconcile the actual provider record and request identity with authorized operator tooling before any recovery decision. A safe automated operator resolution workflow for this case is not claimed to be complete. Do not force the delivery back to queued in SQL.

## Cancel safely

```text
POST /api/v1/crm/deliveries/{delivery_id}/cancel
```

Cancellation is denied once processing/sent/verifying/acknowledged/verified state makes local cancellation an unsafe assertion about remote work. Cancellation cannot undo a provider record already created. Provider-side deletion is a separate authorized operation and is not performed by this endpoint.

## Runtime components and diagnostics

The topology contains `crm-router`, `crm-delivery`, `crm-reconciliation`, `channel-event-consumer`, and `crm-webhook-consumer`, alongside the existing outbox and platform workers. Inspect their logs together with delivery ID, connection ID, tenant scope and correlation ID. Never publish logs containing credentials or customer payloads.

```bash
docker compose ps
docker compose logs --tail=100 crm-router crm-delivery crm-reconciliation crm-webhook-consumer channel-event-consumer
docker compose exec -T api alembic current
```

The expected head for this release is `0010_crm_verification`. Investigate restarted/unhealthy workers and outstanding verification work; container presence alone does not prove broker consumption, remote delivery, or full operational readiness.

## Security sign-off

[Issue #31](https://github.com/ooarchitect92/Chat/issues/31) records GitHub's disabled-code-scanning rejection. An authorized administrator must check private-repository entitlement and policy, enable the feature when approved, rerun both CodeQL languages for the final code, and review findings. Do not change repository visibility, purchase a plan, suppress findings, or make a required security gate optional as a workaround.
