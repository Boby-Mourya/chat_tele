from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.security import generate_api_key, token_fingerprint
from northstar_api.workspace_api_keys import WorkspaceAPIKey


class WorkspaceAPIKeyError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class IssuedWorkspaceAPIKey:
    record: WorkspaceAPIKey
    secret: str


async def list_workspace_api_keys(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
) -> list[WorkspaceAPIKey]:
    return list(
        await session.scalars(
            select(WorkspaceAPIKey)
            .where(
                WorkspaceAPIKey.tenant_id == tenant_id,
                WorkspaceAPIKey.workspace_id == workspace_id,
                WorkspaceAPIKey.revoked_at.is_(None),
            )
            .order_by(WorkspaceAPIKey.created_at.desc(), WorkspaceAPIKey.id.desc())
        )
    )


async def issue_workspace_api_key(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    created_by_user_id: UUID,
    name: str,
    scopes: list[str],
) -> IssuedWorkspaceAPIKey:
    secret, prefix, secret_hash = generate_api_key()
    record = WorkspaceAPIKey(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by_user_id=created_by_user_id,
        name=" ".join(name.split()),
        prefix=prefix,
        secret_hash=secret_hash,
        scopes=list(dict.fromkeys(scopes)),
    )
    session.add(record)
    await session.flush()
    return IssuedWorkspaceAPIKey(record=record, secret=secret)


async def revoke_workspace_api_key(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    api_key_id: UUID,
) -> WorkspaceAPIKey:
    record = await session.scalar(
        select(WorkspaceAPIKey).where(
            WorkspaceAPIKey.id == api_key_id,
            WorkspaceAPIKey.tenant_id == tenant_id,
            WorkspaceAPIKey.workspace_id == workspace_id,
            WorkspaceAPIKey.revoked_at.is_(None),
        )
    )
    if record is None:
        raise WorkspaceAPIKeyError("API key not found", status_code=404)
    record.revoked_at = datetime.now(UTC)
    await session.flush()
    return record


async def find_active_workspace_api_key(
    session: AsyncSession,
    secret: str,
) -> WorkspaceAPIKey | None:
    if not secret.startswith("nsk_live_"):
        return None
    return await session.scalar(
        select(WorkspaceAPIKey).where(
            WorkspaceAPIKey.secret_hash == token_fingerprint(secret),
            WorkspaceAPIKey.revoked_at.is_(None),
        )
    )
