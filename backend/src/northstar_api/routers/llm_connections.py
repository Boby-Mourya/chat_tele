"""Workspace LLM provider catalog and encrypted connection management."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.llm_providers import (
    PROVIDER_BY_ID,
    ProviderId,
    ProviderModel,
    validate_endpoint,
    provider_catalog,
)
from northstar_api.models import LLMConnection
from northstar_api.schemas import APIModel
from northstar_api.security import Principal

router = APIRouter(prefix="/llm", tags=["llm"])
DB = Annotated[AsyncSession, Depends(get_session)]
ViewPrincipal = Annotated[Principal, Depends(require_permissions("integrations.view"))]
ManagePrincipal = Annotated[Principal, Depends(require_permissions("integrations.manage"))]


class LLMConnectionCreate(APIModel):
    provider: ProviderId
    name: str = Field(min_length=2, max_length=160)
    endpoint_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=1, max_length=2000)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def validate_connection(self) -> "LLMConnectionCreate":
        provider = PROVIDER_BY_ID[self.provider]
        endpoint = self.endpoint_url or provider.default_base_url
        validate_endpoint(endpoint, allow_local=provider.supports_local_url)
        if provider.requires_api_key and not self.api_key:
            raise ValueError("An API key is required for this provider")
        if self.provider == "ollama" and self.api_key:
            # Ollama accepts an optional bearer token for hosted or secured servers.
            self.api_key = self.api_key.strip()
        self.endpoint_url = endpoint
        return self


class LLMConnectionPatch(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    endpoint_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=1, max_length=2000)
    metadata: dict[str, str] | None = Field(default=None, max_length=20)
    clear_api_key: bool = False


class LLMConnectionOut(APIModel):
    id: UUID
    name: str
    provider: ProviderId
    endpoint_url: str
    status: str
    has_api_key: bool
    metadata: dict[str, str]
    created_at: datetime
    updated_at: datetime


def _out(value: LLMConnection) -> LLMConnectionOut:
    return LLMConnectionOut(
        id=value.id,
        name=value.name,
        provider=value.provider,
        endpoint_url=value.endpoint_url,
        status=value.status,
        has_api_key=value.credentials_encrypted is not None,
        metadata=dict(value.metadata_json or {}),
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _encrypt(api_key: str | None) -> bytes | None:
    if not api_key:
        return None
    try:
        return credential_store.encrypt({"apiKey": api_key})
    except CredentialStoreError as exc:
        raise HTTPException(status_code=503, detail="Credential encryption is not configured") from exc


@router.get("/providers", response_model=list[dict[str, object]])
async def list_providers(_: ViewPrincipal) -> list[dict[str, object]]:
    return provider_catalog()


@router.get("/models", response_model=list[ProviderModel])
async def list_models(provider: ProviderId, _: ViewPrincipal) -> list[ProviderModel]:
    return PROVIDER_BY_ID[provider].models


@router.get("/connections", response_model=list[LLMConnectionOut])
async def list_connections(principal: ViewPrincipal, session: DB) -> list[LLMConnectionOut]:
    values = await session.scalars(
        select(LLMConnection)
        .where(
            LLMConnection.tenant_id == principal.tenant_id,
            LLMConnection.workspace_id == principal.workspace_id,
        )
        .order_by(LLMConnection.created_at.desc())
    )
    return [_out(value) for value in values]


@router.post("/connections", response_model=LLMConnectionOut, status_code=201)
async def create_connection(payload: LLMConnectionCreate, principal: ManagePrincipal, session: DB) -> LLMConnectionOut:
    assert principal.workspace_id is not None
    try:
        value = LLMConnection(
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            name=payload.name.strip(),
            provider=payload.provider,
            endpoint_url=payload.endpoint_url or PROVIDER_BY_ID[payload.provider].default_base_url,
            credentials_encrypted=_encrypt(payload.api_key),
            metadata_json=payload.metadata,
        )
        session.add(value)
        await session.commit()
        await session.refresh(value)
    except Exception as exc:
        await session.rollback()
        if "uq_llm_connections_workspace_name" in str(exc):
            raise HTTPException(status_code=409, detail="A connection with this name already exists") from None
        raise
    return _out(value)


@router.patch("/connections/{connection_id}", response_model=LLMConnectionOut)
async def update_connection(
    connection_id: UUID, payload: LLMConnectionPatch, principal: ManagePrincipal, session: DB
) -> LLMConnectionOut:
    value = await session.scalar(
        select(LLMConnection).where(
            LLMConnection.id == connection_id,
            LLMConnection.tenant_id == principal.tenant_id,
            LLMConnection.workspace_id == principal.workspace_id,
        )
    )
    if value is None:
        raise HTTPException(status_code=404, detail="LLM connection not found")
    if payload.name is not None:
        value.name = payload.name.strip()
    if payload.endpoint_url is not None:
        value.endpoint_url = validate_endpoint(
            payload.endpoint_url,
            allow_local=PROVIDER_BY_ID[value.provider].supports_local_url,
        )
    if payload.clear_api_key:
        value.credentials_encrypted = None
    elif payload.api_key is not None:
        value.credentials_encrypted = _encrypt(payload.api_key)
    if payload.metadata is not None:
        value.metadata_json = payload.metadata
    if PROVIDER_BY_ID[value.provider].requires_api_key and value.credentials_encrypted is None:
        raise HTTPException(status_code=422, detail="This provider requires an API key")
    await session.commit()
    await session.refresh(value)
    return _out(value)


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(connection_id: UUID, principal: ManagePrincipal, session: DB) -> None:
    value = await session.scalar(
        select(LLMConnection).where(
            LLMConnection.id == connection_id,
            LLMConnection.tenant_id == principal.tenant_id,
            LLMConnection.workspace_id == principal.workspace_id,
        )
    )
    if value is None:
        raise HTTPException(status_code=404, detail="LLM connection not found")
    await session.delete(value)
    await session.commit()
