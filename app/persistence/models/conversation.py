from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.database import Base


class Conversation(Base):
    __tablename__ = "conversation"
    __table_args__ = (
        Index("ix_conversation_owner", "odoo_user_id"),
        Index("ix_conversation_status", "status"),
        Index("ix_conversation_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    odoo_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    employee_id: Mapped[int | None] = mapped_column(BigInteger)
    company_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    active_workflow: Mapped[str | None] = mapped_column(String(64))
    pending_tool_name: Mapped[str | None] = mapped_column(String(128))
    collected_arguments: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    missing_arguments: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    ambiguous_arguments: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    workflow_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    entity_memory: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
