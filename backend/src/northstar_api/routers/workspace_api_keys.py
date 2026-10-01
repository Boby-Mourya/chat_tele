from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.modules.workspace.api_key_scopes import permissions_for_api_key_scopes
from northstar_api.security import Principal
from northstar_api.services.notifications import create_notification
from northstar_api.services.workspace_api_keys import (
    WorkspaceAPIKeyError,
    issue_workspace_api_key,
    list_workspace_api_keys,
    revoke_workspace_api_key,
)
from northstar_api.workspace_api_key_schemas import (
    WorkspaceAPIKeyCreate,
    WorkspaceAPIKeyCreated,
    WorkspaceAPIKeyOut,
)
from northstar_api.workspace_api_keys import WorkspaceAPIKey

router = APIRouter(prefix="/workspace/api-keys", tags=["workspace API keys"])
APIKeyViewPrincipal = Annotated[Principal, Depends(require_permissions("api_keys.view"))]
APIKeyManagePrincipal = Annotated[Principal, Depends(require_permissions("api_keys.manage"))]


def _require_interactive_session(principal: Principal) -> None:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys cannot manage API keys",
        )


def _out(record: WorkspaceAPIKey) -> WorkspaceAPIKeyOut:
    return WorkspaceAPIKeyOut(
        id=record.id,
        name=record.name,
        prefix=record.prefix,
        scopes=list(record.scopes or []),
        created_at=record.created_at,
        last_used_at=record.last_used_at,
    )


@router.get("", response_model=list[WorkspaceAPIKeyOut])
async def get_workspace_api_keys(
    principal: APIKeyViewPrincipal,
    session: DBSession,
) -> list[WorkspaceAPIKeyOut]:
    _require_interactive_session(principal)
    assert principal.workspace_id is not None
    values = await list_workspace_api_keys(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
    )
    return [_out(item) for item in values]


@router.post("", response_model=WorkspaceAPIKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_workspace_api_key(
    payload: WorkspaceAPIKeyCreate,
    principal: APIKeyManagePrincipal,
    session: DBSession,
) -> WorkspaceAPIKeyCreated:
    _require_interactive_session(principal)
    assert principal.workspace_id is not None
    delegated = permissions_for_api_key_scopes(payload.scopes)
    if not delegated <= principal.permissions:
        raise HTTPException(status_code=403, detail="Cannot issue an API key with scopes outside your workspace permissions")
    issued = await issue_workspace_api_key(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        created_by_user_id=principal.user_id,
        name=payload.name,
        scopes=payload.scopes,
    )
    await create_notification(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        recipient_user_id=principal.user_id,
        title="API key created",
        body=f"{issued.record.name} was created with {len(issued.record.scopes)} scopes. Store the secret securely because it is shown only once.",
        dedupe_key=f"api-key-created:{issued.record.id}",
        category="security",
        severity="info",
        action_url="/workspace/settings/developer",
        action_label="Review API keys",
        metadata={"apiKeyId": str(issued.record.id), "prefix": issued.record.prefix, "scopes": list(issued.record.scopes)},
    )
    await session.commit()
    await session.refresh(issued.record)
    return WorkspaceAPIKeyCreated(
        **_out(issued.record).model_dump(),
        secret=issued.secret,
    )


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_api_key(
    api_key_id: UUID,
    principal: APIKeyManagePrincipal,
    session: DBSession,
) -> Response:
    _require_interactive_session(principal)
    assert principal.workspace_id is not None
    try:
        revoked = await revoke_workspace_api_key(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            api_key_id=api_key_id,
        )
        await create_notification(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            recipient_user_id=principal.user_id,
            title="API key revoked",
            body=f"{revoked.name} was revoked and can no longer authenticate requests.",
            dedupe_key=f"api-key-revoked:{revoked.id}",
            category="security",
            severity="warning",
            action_url="/workspace/settings/developer",
            action_label="Review API keys",
            metadata={"apiKeyId": str(revoked.id), "prefix": revoked.prefix},
        )
        await session.commit()
    except WorkspaceAPIKeyError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
