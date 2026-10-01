from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from northstar_api.lead_crm.domain import ChannelProvider


@dataclass(frozen=True, slots=True)
class ChannelConnectionContext:
    tenant_id: UUID
    connection_id: UUID
    provider: ChannelProvider
    configuration: dict[str, Any]
    credentials: dict[str, Any] = field(repr=False)
    public_id: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalSender:
    external_id: str | None = None
    name: str | None = None
    phone: str | None = None
    email: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalMessage:
    external_message_id: str | None
    message_type: str
    text: str | None
    provider_timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class CanonicalInboundEvent:
    event_id: UUID
    tenant_id: UUID
    provider: ChannelProvider
    connection_key: str
    external_event_id: str
    event_type: str
    sender: CanonicalSender
    message: CanonicalMessage | None
    correlation_id: str
    received_at: datetime
    conversation_reference: str | None = None
    campaign_attribution: dict[str, Any] = field(default_factory=dict)
    raw_event_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ChannelConnector(ABC):
    provider: ChannelProvider

    @abstractmethod
    async def verify(
        self,
        context: ChannelConnectionContext,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def normalize(
        self,
        context: ChannelConnectionContext,
        *,
        payload: dict[str, Any],
        correlation_id: str,
        received_at: datetime,
        raw_event_id: UUID | None = None,
    ) -> list[CanonicalInboundEvent]:
        raise NotImplementedError

    async def health_check(self, context: ChannelConnectionContext) -> dict[str, str]:
        return {"status": "unknown"}


class ChannelRegistry:
    def __init__(self) -> None:
        self._connectors: dict[ChannelProvider, ChannelConnector] = {}
        self._defaults_loaded = False

    def _ensure_defaults(self) -> None:
        if self._defaults_loaded:
            return
        self._defaults_loaded = True
        from northstar_api.lead_crm.channel_providers import register_default_channel_connectors
        from northstar_api.lead_crm.slack_channel import SlackConnector

        register_default_channel_connectors()
        # Slack used the generic signed connector before its native runtime was added.
        # Replace only that compatibility registration; API/widget/custom stay unchanged.
        self._connectors[ChannelProvider.SLACK] = SlackConnector()

    def register(self, connector: ChannelConnector) -> None:
        if connector.provider in self._connectors:
            raise ValueError(f"Channel connector already registered: {connector.provider.value}")
        self._connectors[connector.provider] = connector

    def get(self, provider: ChannelProvider) -> ChannelConnector:
        self._ensure_defaults()
        try:
            return self._connectors[provider]
        except KeyError as exc:
            raise KeyError(f"Channel connector is not registered: {provider.value}") from exc

    def providers(self) -> tuple[ChannelProvider, ...]:
        self._ensure_defaults()
        return tuple(self._connectors)


channel_registry = ChannelRegistry()
