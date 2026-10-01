"""Workspace-owned feature modules.

The package intentionally does not import the FastAPI router eagerly. Workspace
contracts and policy helpers are imported by authentication/services, so keeping
this module side-effect free prevents circular imports during application startup.
The API router is registered explicitly from ``northstar_api.routers``.
"""

__all__: list[str] = []
