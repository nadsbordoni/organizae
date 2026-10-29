"""Persist assistant conversations and messages scoped to user and business."""

import sqlalchemy as sa

from alembic import op

revision: str = "e6f8a2c93104"
down_revision: str = "c2e74a9b8106"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "id", "user_id", "business_id", name="uq_assistant_conversation_owner"
        ),
        sa.CheckConstraint(
            "message_count >= 0", name="ck_assistant_conversation_count"
        ),
    )
    op.create_index(
        "ix_assistant_conversations_owner_updated",
        "assistant_conversations",
        ["user_id", "business_id", "updated_at", "id"],
    )
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("pending_actions", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "user_id", "business_id"],
            [
                "assistant_conversations.id",
                "assistant_conversations.user_id",
                "assistant_conversations.business_id",
            ],
            name="fk_assistant_message_conversation_owner",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "conversation_id", "position", name="uq_assistant_message_position"
        ),
        sa.CheckConstraint("position > 0", name="ck_assistant_message_position"),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_assistant_message_role"
        ),
    )


def downgrade() -> None:
    op.drop_table("assistant_messages")
    op.drop_index(
        "ix_assistant_conversations_owner_updated", table_name="assistant_conversations"
    )
    op.drop_table("assistant_conversations")
