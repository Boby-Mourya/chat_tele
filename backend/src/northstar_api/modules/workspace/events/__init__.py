"""Workspace administrative audit and domain-event boundary."""

from .administrative_events import domain_event_name, emit_workspace_administrative_event

__all__ = ["domain_event_name", "emit_workspace_administrative_event"]
