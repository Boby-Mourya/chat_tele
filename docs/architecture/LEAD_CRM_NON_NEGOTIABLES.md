# Lead + CRM Architecture Non-Negotiables

1. No provider-specific CRM logic inside LeadService.
2. No CRM logic inside channel connectors.
3. Every external channel normalizes to a canonical event before business processing.
4. Every CRM provider implements the shared CRM connector contract.
5. Every tenant-owned query and write is tenant scoped; PostgreSQL tenant tables use RLS in production.
6. Every externally received event is idempotent and replay-safe.
7. Every CRM delivery is durably persisted before execution.
8. Lead persistence/qualification and sync requests use the transactional outbox pattern.
9. External API, queue, worker or provider failure must never silently lose a persisted lead.
10. Credentials, refresh tokens, access tokens, client secrets and API keys are never plaintext in logs or frontend responses.
11. Every outbound CRM delivery has explicit acknowledgement state.
12. Business-critical connectors support read-back verification where the provider permits it.
13. Every integration connection has explicit health state rather than a single global up/down flag.
14. Every request/event/delivery carries a correlation/request identifier through the processing chain.
15. Provider-specific field schemas never become the canonical Lead schema.
16. Adding a CRM must not require changing LeadService or channel connectors.
17. Adding a channel must not require changing CRM connectors.
18. Dead-letter inspection, retry and cancellation operations are authorized and audited.
19. Production frontend/runtime must not silently substitute demo/localStorage data when backend operations fail.
20. Existing WhatsApp functionality remains operational throughout the migration.
21. Lead lifecycle state and CRM delivery state are separate state machines.
22. A lead may route to zero, one or multiple CRM connections independently.
23. Provider record IDs belong in external-reference/delivery records, not provider-specific columns on Lead.
24. Health probes must not create real customer/CRM records.
25. Live provider success is never claimed without actual credential-backed validation; mock-tested providers are explicitly marked live-validation-pending.
