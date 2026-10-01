"""Recover queued/lost index stages without sharing tutoring worker capacity.

Run with the existing privileged worker database identity, like job_dispatcher.
No student content leaves this process; broker messages contain scoped IDs only.
"""
from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.course_knowledge_dispatch import CourseIndexDispatch
from northstar_api.course_knowledge_models import CourseMaterialAssignment
from northstar_api.database import build_engine
from northstar_api.workers.course_knowledge_tasks import prepare_course_assignment

logger = structlog.get_logger(__name__)
MAX_ATTEMPTS = 8
# Longer than the existing Celery 1500-second hard limit, so a killed worker's
# durable stage is eventually retried without repeatedly dispatching live work.
LEASE_SECONDS = 1800


async def dispatch_once(factory: async_sessionmaker) -> int:
    now = datetime.now(UTC)
    sent = 0
    async with factory() as session:
        rows = (await session.scalars(select(CourseMaterialAssignment).outerjoin(CourseIndexDispatch, and_(
            CourseIndexDispatch.assignment_id == CourseMaterialAssignment.id,
            CourseIndexDispatch.revision == CourseMaterialAssignment.revision,
        )).where(
            CourseMaterialAssignment.status == "approved",
            CourseMaterialAssignment.index_status.in_(("queued", "preparing")),
            or_(CourseIndexDispatch.assignment_id.is_(None), CourseIndexDispatch.next_dispatch_at.is_(None),
                CourseIndexDispatch.next_dispatch_at <= now),
        ).order_by(CourseMaterialAssignment.created_at).with_for_update(skip_locked=True, of=CourseMaterialAssignment).limit(100))).all()
        for assignment in rows:
            key = (assignment.id, assignment.revision)
            delivery = await session.get(CourseIndexDispatch, key)
            if delivery is None:
                delivery = CourseIndexDispatch(tenant_id=assignment.tenant_id, workspace_id=assignment.workspace_id, agent_id=assignment.agent_id, assignment_id=assignment.id, revision=assignment.revision, attempts=0)
                session.add(delivery)
            next_at = delivery.next_dispatch_at
            if next_at and next_at.tzinfo is None:
                next_at = next_at.replace(tzinfo=UTC)
            if next_at and next_at > now:
                continue
            if delivery.attempts >= MAX_ATTEMPTS:
                assignment.index_status = "failed"
                assignment.index_error = "Index dispatch exhausted; use Prepare index to retry this approved revision"
                continue
            delivery.attempts += 1
            try:
                await asyncio.to_thread(prepare_course_assignment.apply_async,
                    args=[str(assignment.tenant_id), str(assignment.workspace_id), str(assignment.agent_id), str(assignment.id), assignment.revision],
                    queue="ingest.source", routing_key="ingest.source",
                    task_id=f"course-index-{assignment.id}-{assignment.revision}-{delivery.attempts}")
            except Exception as exc:
                delivery.last_error = type(exc).__name__
                delivery.next_dispatch_at = now + timedelta(seconds=min(300, 2 ** delivery.attempts))
                assignment.index_error = "Broker unavailable; the durable dispatcher will retry"
            else:
                delivery.last_error = None
                delivery.next_dispatch_at = now + timedelta(seconds=LEASE_SECONDS)
                sent += 1
        # A crash after broker acceptance but before this commit may duplicate a
        # delivery; the task rechecks the unique assignment/revision stage.
        await session.commit()
    return sent


async def run() -> None:
    engine = build_engine(get_settings())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    try:
        while not stop.is_set():
            try:
                await dispatch_once(factory)
            except Exception as exc:
                logger.error("course_index_dispatch_failed", error=type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
