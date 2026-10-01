"""Workspace domain services.

This package exposes the current service functions through a feature-owned
boundary while the staged migration keeps compatibility modules in place.
"""

from northstar_api.modules.workspace.brand_cache import (
    cache_workspace_brand,
    cached_domain_brand,
    cached_workspace_brand,
    invalidate_brand_cache,
)
from northstar_api.modules.workspace.domain_resolution import resolve_workspace_domain
from northstar_api.modules.workspace.email_branding import deliver_workspace_email, render_workspace_email
from northstar_api.modules.workspace.member_state import is_member_suspended, save_member_status
from northstar_api.modules.workspace.security_policy import (
    email_domain_allowed,
    enforce_network_security,
    enforce_request_security,
    required_password_length,
    validate_business_timezone,
    validate_security_settings,
)
from northstar_api.modules.workspace.services.settings_service import (
    sync_developer_settings_record,
    sync_notification_settings_record,
    sync_security_policy_record,
)
from northstar_api.modules.workspace.services.team_service import (
    list_workspace_team_records,
    sync_workspace_team_records,
    update_workspace_teams,
)

__all__ = [
    "cache_workspace_brand",
    "cached_domain_brand",
    "cached_workspace_brand",
    "deliver_workspace_email",
    "email_domain_allowed",
    "enforce_network_security",
    "enforce_request_security",
    "invalidate_brand_cache",
    "is_member_suspended",
    "list_workspace_team_records",
    "render_workspace_email",
    "required_password_length",
    "resolve_workspace_domain",
    "save_member_status",
    "sync_developer_settings_record",
    "sync_notification_settings_record",
    "sync_security_policy_record",
    "sync_workspace_team_records",
    "update_workspace_teams",
    "validate_business_timezone",
    "validate_security_settings",
]
