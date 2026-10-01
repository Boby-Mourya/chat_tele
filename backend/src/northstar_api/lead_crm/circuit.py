from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base
from northstar_api.lead_crm.models import CRMConnection
from northstar_api.lead_crm.verification import as_utc


class CircuitState(str, enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CRMCircuitBreaker(Base):
    __tablename__ = "crm_circuit_breakers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connection_id", name="uq_crm_circuit_connection"),
        Index("ix_crm_circuit_scope", "tenant_id", "state", "open_until"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(String(24), default=CircuitState.CLOSED.value)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


async def get_or_create_circuit(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    connection_id: UUID,
) -> CRMCircuitBreaker:
    connection = await session.scalar(
        select(CRMConnection.id)
        .where(CRMConnection.id == connection_id, CRMConnection.tenant_id == tenant_id)
        .with_for_update()
    )
    if connection is None:
        raise ValueError("CRM circuit connection does not exist in tenant scope")
    circuit = await session.scalar(
        select(CRMCircuitBreaker).where(
            CRMCircuitBreaker.tenant_id == tenant_id,
            CRMCircuitBreaker.connection_id == connection_id,
        )
    )
    if circuit is None:
        circuit = CRMCircuitBreaker(tenant_id=tenant_id, connection_id=connection_id)
        session.add(circuit)
        await session.flush()
    return circuit


async def allow_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    connection_id: UUID,
) -> bool:
    circuit = await get_or_create_circuit(session, tenant_id=tenant_id, connection_id=connection_id)
    now = datetime.now(UTC)
    if circuit.state == CircuitState.CLOSED.value:
        return True
    if circuit.open_until is None or as_utc(circuit.open_until) > now:
        return False
    # Persist a lease so another worker cannot probe the same half-open circuit.
    circuit.state = CircuitState.HALF_OPEN.value
    circuit.open_until = now + timedelta(seconds=120)
    return True


async def record_success(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    connection_id: UUID,
) -> None:
    circuit = await get_or_create_circuit(session, tenant_id=tenant_id, connection_id=connection_id)
    circuit.state = CircuitState.CLOSED.value
    circuit.consecutive_failures = 0
    circuit.opened_at = None
    circuit.open_until = None
    circuit.last_success_at = datetime.now(UTC)


async def record_failure(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    connection_id: UUID,
    threshold: int,
    cooldown_seconds: int,
) -> CRMCircuitBreaker:
    circuit = await get_or_create_circuit(session, tenant_id=tenant_id, connection_id=connection_id)
    now = datetime.now(UTC)
    circuit.consecutive_failures += 1
    circuit.last_failure_at = now
    if circuit.state == CircuitState.HALF_OPEN.value or circuit.consecutive_failures >= threshold:
        circuit.state = CircuitState.OPEN.value
        circuit.opened_at = now
        circuit.open_until = now + timedelta(seconds=max(1, cooldown_seconds))
    return circuit
