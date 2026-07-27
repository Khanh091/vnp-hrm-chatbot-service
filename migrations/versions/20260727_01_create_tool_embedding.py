"""create pgvector tool embedding table

Revision ID: 20260727_01
Revises:
Create Date: 2026-07-27
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.common.constants import DEFAULT_EMBEDDING_DIMENSION

revision = "20260727_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "tool_embedding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("tool_version", sa.String(length=32), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("route_type", sa.String(length=32), nullable=False),
        sa.Column("capability", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("embedding_text", sa.Text(), nullable=False),
        sa.Column(
            "embedding",
            Vector(DEFAULT_EMBEDDING_DIMENSION),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
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
            "tool_name",
            "tool_version",
            name="uq_tool_embedding_name_version",
        ),
    )
    op.create_index(
        "ix_tool_embedding_metadata",
        "tool_embedding",
        ["domain", "route_type", "enabled"],
    )
    op.create_index(
        "ix_tool_embedding_embedding_hnsw",
        "tool_embedding",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_embedding_embedding_hnsw",
        table_name="tool_embedding",
    )
    op.drop_index("ix_tool_embedding_metadata", table_name="tool_embedding")
    op.drop_table("tool_embedding")
