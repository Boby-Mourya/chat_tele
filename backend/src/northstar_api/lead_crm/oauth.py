from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from redis.exceptions import RedisError

from northstar_api.services.rate_limit import redis_services


class OAuthStateError(RuntimeError):
    pass


OAuthResponseMode = Literal["json", "popup"]


@dataclass(frozen=True, slots=True)
class OAuthState:
    state: str
    tenant_id: UUID
    connection_id: UUID
    user_id: UUID
    provider: str
    redirect_uri: str
    code_verifier: str
    workspace_id: UUID | None = None
    response_mode: OAuthResponseMode = "json"

    @property
    def code_challenge(self) -> str:
        digest = hashlib.sha256(self.code_verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")


class OAuthStateStore:
    prefix = "northstar:crm-oauth:state:"
    ttl_seconds = 600

    async def create(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        user_id: UUID,
        provider: str,
        redirect_uri: str,
        workspace_id: UUID | None = None,
        response_mode: OAuthResponseMode = "json",
    ) -> OAuthState:
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        value = OAuthState(
            state=state,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            connection_id=connection_id,
            user_id=user_id,
            provider=provider,
            redirect_uri=redirect_uri,
            code_verifier=verifier,
            response_mode=response_mode,
        )
        payload = json.dumps(
            {
                "tenantId": str(tenant_id),
                "workspaceId": str(workspace_id) if workspace_id else None,
                "connectionId": str(connection_id),
                "userId": str(user_id),
                "provider": provider,
                "redirectUri": redirect_uri,
                "codeVerifier": verifier,
                "responseMode": response_mode,
            },
            separators=(",", ":"),
        )
        try:
            inserted = await redis_services.client.set(
                f"{self.prefix}{state}",
                payload,
                ex=self.ttl_seconds,
                nx=True,
            )
        except RedisError as exc:
            raise OAuthStateError("OAuth state store is unavailable") from exc
        if not inserted:
            raise OAuthStateError("OAuth state could not be created")
        return value

    async def consume(self, state: str) -> OAuthState:
        key = f"{self.prefix}{state}"
        try:
            pipeline = redis_services.client.pipeline(transaction=True)
            pipeline.get(key)
            pipeline.delete(key)
            raw, _ = await pipeline.execute()
        except RedisError as exc:
            raise OAuthStateError("OAuth state store is unavailable") from exc
        if not isinstance(raw, str) or not raw:
            raise OAuthStateError("OAuth state is invalid, expired, or already used")
        try:
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            workspace_raw = value.get("workspaceId")
            response_mode = str(value.get("responseMode") or "json")
            if response_mode not in {"json", "popup"}:
                raise ValueError
            return OAuthState(
                state=state,
                tenant_id=UUID(str(value["tenantId"])),
                workspace_id=UUID(str(workspace_raw)) if workspace_raw else None,
                connection_id=UUID(str(value["connectionId"])),
                user_id=UUID(str(value["userId"])),
                provider=str(value["provider"]),
                redirect_uri=str(value["redirectUri"]),
                code_verifier=str(value["codeVerifier"]),
                response_mode=cast(OAuthResponseMode, response_mode),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OAuthStateError("Stored OAuth state is corrupt") from exc


oauth_state_store = OAuthStateStore()
