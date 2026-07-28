from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.database import Base


class PendingAction(Base):
    __tablename__ = "pending_action"
    __table_args__ = (
        Index("ix_pending_action_conversation", "conversation_id"),
        Index("ix_pending_action_owner", "odoo_user_id"),
        Index("ix_pending_action_status", "status"),
        Index("ix_pending_action_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    action_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("conversation.conversation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    odoo_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(32), nullable=False)
    validated_arguments: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )
    display_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
