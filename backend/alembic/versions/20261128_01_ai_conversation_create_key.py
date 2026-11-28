"""Add create_request_key to ai_conversations for new-conversation idempotency.

Revision ID: 20261128_01
Revises: 20261026_01
Create Date: 2026-11-28 18:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261128_01"
down_revision = "20261026_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_conversations",
        sa.Column("create_request_key", mysql.BINARY(16), nullable=True),
    )
    op.create_unique_constraint(
        "uq_ai_conversation_create_request",
        "ai_conversations",
        ["owner_user_id", "create_request_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ai_conversation_create_request",
        "ai_conversations",
        type_="unique",
    )
    op.drop_column("ai_conversations", "create_request_key")
