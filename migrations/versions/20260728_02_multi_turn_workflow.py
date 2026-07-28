"""add durable conversation and pending action state

Revision ID: 20260728_02
Revises: 20260727_01
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260728_02"
down_revision = "20260727_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("conversation_id", sa.String(128), nullable=False),
        sa.Column("odoo_user_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger()),
        sa.Column("company_id", sa.BigInteger()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("active_workflow", sa.String(64)),
        sa.Column("pending_tool_name", sa.String(128)),
        sa.Column(
            "collected_arguments",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "missing_arguments",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "ambiguous_arguments",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "workflow_data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "conversation_id", name="uq_conversation_conversation_id"
        ),
    )
    op.create_index("ix_conversation_owner", "conversation", ["odoo_user_id"])
    op.create_index("ix_conversation_status", "conversation", ["status"])
    op.create_index(
        "ix_conversation_expires_at", "conversation", ["expires_at"]
    )

    op.create_table(
        "conversation_message",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(128),
            sa.ForeignKey("conversation.conversation_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("message_type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column(
            "structured_data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_conversation_message_conversation",
        "conversation_message",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_message_request",
        "conversation_message",
        ["request_id"],
    )

    op.create_table(
        "pending_action",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("action_id", sa.String(64), nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(128),
            sa.ForeignKey("conversation.conversation_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("odoo_user_id", sa.BigInteger(), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("tool_version", sa.String(32), nullable=False),
        sa.Column(
            "validated_arguments", postgresql.JSONB(), nullable=False
        ),
        sa.Column("display_summary", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("executing_at", sa.DateTime(timezone=True)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("result_summary", postgresql.JSONB()),
        sa.UniqueConstraint("action_id", name="uq_pending_action_action_id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_pending_action_idempotency_key"
        ),
    )
    op.create_index(
        "ix_pending_action_conversation",
        "pending_action",
        ["conversation_id"],
    )
    op.create_index(
        "ix_pending_action_owner", "pending_action", ["odoo_user_id"]
    )
    op.create_index(
        "ix_pending_action_status", "pending_action", ["status"]
    )
    op.create_index(
        "ix_pending_action_expires_at", "pending_action", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_pending_action_expires_at", table_name="pending_action")
    op.drop_index("ix_pending_action_status", table_name="pending_action")
    op.drop_index("ix_pending_action_owner", table_name="pending_action")
    op.drop_index("ix_pending_action_conversation", table_name="pending_action")
    op.drop_table("pending_action")
    op.drop_index(
        "ix_conversation_message_request", table_name="conversation_message"
    )
    op.drop_index(
        "ix_conversation_message_conversation",
        table_name="conversation_message",
    )
    op.drop_table("conversation_message")
    op.drop_index("ix_conversation_expires_at", table_name="conversation")
    op.drop_index("ix_conversation_status", table_name="conversation")
    op.drop_index("ix_conversation_owner", table_name="conversation")
    op.drop_table("conversation")
