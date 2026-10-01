"""Canonical scoped grants. This module deliberately has no runtime dependencies.

An organization grant never authorizes workspace data. Workspace administrators
receive an explicit allowlist, never a wildcard. Unknown permissions deny access.
"""
from __future__ import annotations

ORGANIZATION_PERMISSIONS = frozenset({
    "organization.view", "organization.profile.update", "organization.members.invite",
    "organization.roles.manage", "organization.ownership.transfer", "organization.audit.view",
    "workspace.create", "billing.view", "billing.manage", "security.view", "security.manage",
    "usage.view", "organization.branding.edit", "organization.branding.publish",
})

# The original product used ``*.view``/``*.manage`` names.  The public
# workspace capability contract uses more explicit CRUD-oriented names.  Keep
# both during the migration, but resolve them to one authorization decision so
# a role created with either vocabulary cannot accidentally bypass a guard.
PERMISSION_ALIASES: dict[str, str] = {
    "workspace.read": "workspace.view",
    "members.read": "members.view",
    "members.update": "members.manage",
    "members.remove": "members.manage",
    "roles.read": "roles.manage",
    "roles.create": "roles.manage",
    "roles.update": "roles.manage",
    "roles.delete": "roles.manage",
    "agents.read": "agents.view",
    "channels.read": "channels.view",
    "channels.connect": "channels.connections.manage",
    "channels.update": "channels.manage",
    "channels.disconnect": "channels.connections.manage",
    "conversations.read": "conversations.view",
    "conversations.close": "conversations.resolve",
    "leads.read": "leads.view",
    "leads.create": "leads.update",
    "crm.read": "crm.view",
    "crm.configure": "crm.manage",
    "crm.sync": "crm.manage",
    "education.read": "education.view",
    "education.manage_courses": "education.courses.manage",
    "education.manage_students": "education.students.manage",
    "education.manage_enrollments": "education.enrollments.manage",
    "analytics.read": "analytics.view",
    "analytics.export": "analytics.view",
    "api_keys.read": "api_keys.view",
    "audit.read": "audit.view",
}

_WORKSPACE_PERMISSION_NAMES = {
    "workspace.view", "workspace.update", "workspace.archive", "workspace.restore",
    "workspace.export", "workspace.delete", "members.view", "members.manage", "members.invite",
    "members.roles.assign", "roles.manage", "teams.manage", "agents.view", "agents.create",
    "agents.update", "agents.test", "agents.deploy", "agents.delete", "knowledge.view",
    "knowledge.manage", "knowledge.upload", "knowledge.approve", "knowledge.reindex",
    "knowledge.delete", "knowledge.export", "conversations.view", "conversations.reply",
    "conversations.resolve", "conversations.assign", "conversations.export", "conversations.delete",
    "leads.view", "leads.update", "leads.export", "integrations.view", "integrations.manage",
    "crm.view", "crm.manage", "crm.connections.manage", "crm.mapping.manage", "crm.deliveries.retry",
    "channels.view", "channels.manage", "channels.connections.manage", "analytics.view",
    "education.view", "education.manage", "education.courses.manage", "education.students.view",
    "education.students.manage", "education.enrollments.manage", "education.recovery.manage",
    "settings.view", "settings.manage", "branding.view", "branding.edit", "branding.publish",
    "branding.domain.manage", "audit.view", "audit.export", "api_keys.view", "api_keys.manage",
    "api_keys.create", "api_keys.rotate", "api_keys.revoke", "starter_content.read", "playground.use",
}
WORKSPACE_PERMISSIONS = frozenset(_WORKSPACE_PERMISSION_NAMES | set(PERMISSION_ALIASES))

_READ = frozenset({
    "workspace.view", "agents.view", "knowledge.view", "conversations.view", "leads.view",
    "analytics.view", "education.view", "starter_content.read",
})
WORKSPACE_GRANTS: dict[str, frozenset[str]] = {
    "workspace_admin": WORKSPACE_PERMISSIONS,
    "manager": _READ | frozenset({
        "members.view", "agents.create", "agents.update", "agents.test", "agents.deploy",
        "knowledge.manage", "conversations.reply", "conversations.resolve", "conversations.assign",
        "leads.update", "leads.export", "integrations.view", "crm.view", "education.manage",
        "settings.view", "branding.view", "playground.use",
    }),
    "operator": (_READ - {"analytics.view"}) | frozenset({
        "conversations.reply", "conversations.resolve", "conversations.assign", "leads.update",
    }),
    "analyst": _READ | frozenset({"leads.export", "integrations.view", "crm.view"}),
    "viewer": _READ,
}
ORGANIZATION_GRANTS: dict[str, frozenset[str]] = {
    "owner": ORGANIZATION_PERMISSIONS,
    "admin": ORGANIZATION_PERMISSIONS - {"organization.ownership.transfer"},
    "billing_admin": frozenset({"organization.view", "billing.view", "billing.manage", "usage.view"}),
    "security_admin": frozenset({
        "organization.view", "security.view", "security.manage", "organization.audit.view",
    }),
    "member": frozenset({"organization.view"}),
    "analyst": frozenset({"organization.view"}),
}


def effective_permissions(organization_role: str, workspace_role: str | None) -> frozenset[str]:
    return ORGANIZATION_GRANTS.get(organization_role, frozenset()) | WORKSPACE_GRANTS.get(
        workspace_role or "", frozenset()
    )


def permits(permission: str, organization_role: str, grants: frozenset[str], *, has_workspace: bool) -> bool:
    """Validate the namespace as well as the grant; wildcard strings are inert."""
    canonical = PERMISSION_ALIASES.get(permission, permission)
    if canonical in ORGANIZATION_PERMISSIONS:
        return _grant_contains(grants, canonical) and canonical in ORGANIZATION_GRANTS.get(
            organization_role, frozenset()
        )
    return has_workspace and canonical in _WORKSPACE_PERMISSION_NAMES and _grant_contains(grants, canonical)


def _grant_contains(grants: frozenset[str], canonical: str) -> bool:
    """Return whether a grant contains a canonical capability or its alias."""
    if canonical in grants:
        return True
    return any(alias in grants for alias, target in PERMISSION_ALIASES.items() if target == canonical)


def validate_delegated_permissions(requested: list[str], actor_grants: frozenset[str]) -> frozenset[str]:
    selected = frozenset(requested)
    if not selected or not selected <= WORKSPACE_PERMISSIONS:
        raise ValueError("Select known workspace permissions only")
    if any(not _grant_contains(actor_grants, PERMISSION_ALIASES.get(permission, permission)) for permission in selected):
        raise ValueError("Cannot delegate a permission you do not hold")
    return selected
