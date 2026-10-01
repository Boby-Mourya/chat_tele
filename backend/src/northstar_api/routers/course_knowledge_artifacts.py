"""Reload exact draft fingerprints before approving generated learning material."""
from uuid import UUID

from northstar_api.course_knowledge_models import CourseDerivedArtifact
from northstar_api.routers.course_knowledge import DB, PREFIX, View, PolicyRoute, boundary_for, record_out
from northstar_api.services.course_knowledge import artifact_digest, scoped_row
from fastapi import APIRouter

router = APIRouter(tags=["course-knowledge"], route_class=PolicyRoute)


@router.get(PREFIX + "/artifacts/{artifact_id}")
async def read_artifact(agent_id: UUID, artifact_id: UUID, principal: View, session: DB):
    boundary = await boundary_for(session, principal, agent_id)
    artifact = await scoped_row(session, CourseDerivedArtifact, artifact_id, boundary)
    return {**record_out(artifact), "fingerprint": artifact_digest(artifact)}
