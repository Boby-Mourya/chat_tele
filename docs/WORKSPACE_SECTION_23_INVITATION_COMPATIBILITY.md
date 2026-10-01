# Workspace section 23 — invitation service compatibility

Scope: Workspace module boundary only. The teammate-owned invitation implementation and HTTP registration remain unchanged.

## Canonical service path

`northstar_api.modules.workspace.services.invitation_service` exports the **same Python objects** from the established `northstar_api.services.workspace_invitations` module. This includes invitation issue/resend/list/revoke, preview/accept/signup/decline, token hashing, agent-access listing, delivery, URL creation, error and result contracts.

Do not register any extra invitation routes: `northstar_api.modules.workspace.api.workspace_invitations` remains an opt-in adapter that exposes the original `northstar_api.routers.workspace_invitations` router objects. Neither canonical adapter declares database models, regenerates tokens, changes email sending or takes over transaction ownership. The compatibility boundary is **not** a claim that the entire invitation lifecycle was newly implemented or moved into new files.

## Regression checks (committed, not verified passing)

`backend/tests/test_workspace_invitation_service_boundary_unit.py` asserts exported function/type identity against the original service, full canonical export coverage, and fresh-interpreter imports in both service-first and legacy-router-first orders. Run from `backend/`:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest tests/test_workspace_invitation_service_boundary_unit.py tests/test_workspace_service_import_order_unit.py tests/test_workspace_canonical_api_routes_unit.py tests/test_workspace_production_router_registration_unit.py
```

These import-level tests do not replace invitation issuance/acceptance/revocation, tenant isolation, email-delivery, token expiry and retry integration tests. Section 23 and the broader section 44 acceptance gate remain OPEN pending executable passing results. Do not merge either draft Workspace PR until verified.
