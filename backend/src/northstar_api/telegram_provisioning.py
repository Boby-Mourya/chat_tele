"""Control-plane sessions, separate from the tenant-scoped student event pipeline."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class TelegramProvisioning(Base):
    __tablename__ = "telegram_provisioning"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channel_connections.id", ondelete="SET NULL"), unique=True
    )
    nonce_hash: Mapped[str] = mapped_column(String(64), unique=True)
    nonce_encrypted: Mapped[bytes] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    telegram_user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    request_id: Mapped[int] = mapped_column(Integer)
    bot_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    error: Mapped[str | None] = mapped_column(String(250))


class TelegramManagerUpdate(Base):
    __tablename__ = "telegram_manager_updates"
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
