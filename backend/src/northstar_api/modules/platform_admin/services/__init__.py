"""Canonical platform-admin service boundary."""

from northstar_api.services.platform_admin import get_platform_tenant, list_platform_tenants, platform_overview

__all__ = ["get_platform_tenant", "list_platform_tenants", "platform_overview"]
