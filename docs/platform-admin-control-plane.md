# Platform control-plane access

Platform administration is separate from tenant and workspace membership. A
platform operator may be enabled in either of these ways:

1. `PLATFORM_ADMIN_EMAILS` provides the backwards-compatible deployment
   allowlist and grants the configured account the full platform capability set.
2. The `platform_admin_assignments` table stores a durable role (`owner`,
   `operations`, `billing`, `support`, or `auditor`) and an optional narrower
   permission list for an individual user.

The table is created by migration `0061_platform_admin_assignments`. Operators
with `platform.admins.manage` can manage assignments through:

```text
GET /api/v1/platform-admin/operators
PUT /api/v1/platform-admin/operators/{user_id}
```

Every assignment change requires a reason and creates a security audit event.
High-risk routes separately require `platform.tenants.manage`,
`platform.billing.manage`, or `platform.support.impersonate`. API keys cannot
access the control plane, and support sessions remain time-limited and
revocable.
