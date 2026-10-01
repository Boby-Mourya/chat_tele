from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.exc import IntegrityError

from northstar_api.dependencies import CurrentPrincipal, DBSession
from northstar_api.services.entitlements import EntitlementError
from northstar_api.services.starter_content import StarterContentError, clone_result, clone_template
from northstar_api.starter_content_contract import TemplateCloneOut, TemplateCloneRequest

router = APIRouter(prefix="/starter-content", tags=["starter-content"])


@router.get("/clone-requests/{request_id}", response_model=TemplateCloneOut)
async def get_clone_result(request_id: UUID, principal: CurrentPrincipal,
                           session: DBSession, response: Response) -> TemplateCloneOut:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await clone_result(session, principal, request_id)
    except StarterContentError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/{catalog_id}/clone", response_model=TemplateCloneOut, status_code=201)
async def copy_starter_template(catalog_id: str, payload: TemplateCloneRequest,
                               principal: CurrentPrincipal, session: DBSession,
                               response: Response) -> TemplateCloneOut:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        result = await clone_template(session, principal, catalog_id, payload)
        await session.commit()
    except (StarterContentError, EntitlementError) as exc:
        await session.rollback()
        raise HTTPException(exc.status_code, str(exc)) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "The agent name or clone request conflicts with an existing record. Check the saved request before retrying") from None
    response.status_code = 200 if result.replayed else 201
    return result
