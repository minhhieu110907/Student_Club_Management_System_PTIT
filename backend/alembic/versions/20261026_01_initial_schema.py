"""Create the SCMS V1.3 initial schema.

Revision ID: 20261026_01
Revises: None
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "20261026_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_TABLE_ORDER = (
    "outbox_events", "users", "club_creation_requests", "notifications",
    "refresh_token_families", "clubs", "audit_logs", "ai_conversations",
    "membership_applications", "events", "refresh_tokens", "ai_turns",
    "club_memberships", "ai_usage_records", "event_registrations", "ai_messages",
    "event_tasks", "ai_tool_executions",
)
DOWNGRADE_TABLE_ORDER = tuple(reversed(UPGRADE_TABLE_ORDER))

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("event_type", mysql.VARCHAR(80), nullable=False),
        sa.Column("aggregate_type", mysql.VARCHAR(48), nullable=False),
        sa.Column("aggregate_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("payload", mysql.JSON(), nullable=False),
        sa.Column("status", mysql.ENUM("PENDING", "PROCESSING", "PUBLISHED", "DEAD"), server_default="PENDING", nullable=False),
        sa.Column("attempt_count", mysql.INTEGER(unsigned=False), server_default="0", nullable=False),
        sa.Column("next_attempt_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("claim_token", mysql.BINARY(16), nullable=True),
        sa.Column("claimed_until", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("published_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("last_error_code", mysql.VARCHAR(64), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("purge_after", mysql.DATETIME(fsp=6), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="ck_outbox_attempts"),
        sa.CheckConstraint("(status <> 'PROCESSING') OR (claim_token IS NOT NULL AND claimed_until IS NOT NULL)", name="ck_outbox_claim"),
        sa.CheckConstraint("(status <> 'PUBLISHED') OR published_at IS NOT NULL", name="ck_outbox_published"),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_outbox_due", "outbox_events", ["status", "next_attempt_at", "id"])
    op.create_index("ix_outbox_reclaim", "outbox_events", ["status", "claimed_until", "id"])
    op.create_index("ix_outbox_cleanup", "outbox_events", ["purge_after", "id"])
    op.create_index("ix_outbox_aggregate", "outbox_events", ["aggregate_type", "aggregate_id", "created_at"])

    op.create_table(
        "users",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("email_normalized", mysql.VARCHAR(254, collation="utf8mb4_0900_as_cs"), nullable=False),
        sa.Column("full_name", mysql.VARCHAR(160), nullable=False),
        sa.Column("password_hash", mysql.VARCHAR(255), nullable=False),
        sa.Column("global_role", mysql.ENUM("STUDENT", "ADMIN"), server_default="STUDENT", nullable=False),
        sa.Column("status", mysql.ENUM("ACTIVE", "DISABLED"), server_default="ACTIVE", nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_users_admin_state", "users", ["status", "id"])

    op.create_table(
        "club_creation_requests",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("requested_by", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("proposed_name", mysql.VARCHAR(160), nullable=False),
        sa.Column("category", mysql.VARCHAR(80), nullable=False),
        sa.Column("mission", mysql.TEXT(), nullable=False),
        sa.Column("initial_plan", mysql.TEXT(), nullable=False),
        sa.Column("status", mysql.ENUM("PENDING", "APPROVED", "REJECTED"), server_default="PENDING", nullable=False),
        sa.Column("reviewed_by", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("rejection_reason", mysql.VARCHAR(1000), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name="fk_club_creation_requests_requested_by_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_club_creation_requests_reviewed_by_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_club_creation_requests"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_club_requests_mine", "club_creation_requests", ["requested_by", "created_at", "id"])
    op.create_index("ix_club_requests_review", "club_creation_requests", ["status", "created_at", "id"])
    op.create_index("ix_club_creation_requests_reviewed_by", "club_creation_requests", ["reviewed_by"])

    op.create_table(
        "notifications",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("type", mysql.VARCHAR(64), nullable=False),
        sa.Column("resource_type", mysql.VARCHAR(48), nullable=True),
        sa.Column("resource_id", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("safe_summary", mysql.VARCHAR(500), nullable=False),
        sa.Column("read_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("purge_after", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_notifications_user_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_notifications_inbox", "notifications", ["user_id", "read_at", "created_at", "id"])
    op.create_index("ix_notifications_cleanup", "notifications", ["purge_after", "id"])

    op.create_table(
        "refresh_token_families",
        sa.Column("id", mysql.BINARY(16), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("absolute_expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("revoke_reason", mysql.VARCHAR(48), nullable=True),
        sa.Column("suspicious_reuse_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("purge_after", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("absolute_expires_at > created_at", name="ck_family_lifetime"),
        sa.CheckConstraint("purge_after >= absolute_expires_at", name="ck_family_retention"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_refresh_token_families_user_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_token_families"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_families_user_sessions", "refresh_token_families", ["user_id", "revoked_at", "id"])
    op.create_index("ix_families_cleanup", "refresh_token_families", ["purge_after", "id"])

    op.create_table(
        "clubs",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("source_request_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("name", mysql.VARCHAR(160), nullable=False),
        sa.Column("category", mysql.VARCHAR(80), nullable=False),
        sa.Column("description", mysql.TEXT(), nullable=False),
        sa.Column("status", mysql.ENUM("ACTIVE", "SUSPENDED"), server_default="ACTIVE", nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["source_request_id"], ["club_creation_requests.id"], name="fk_clubs_source_request_id_club_creation_requests", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_clubs"),
        sa.UniqueConstraint("source_request_id", name="uq_clubs_source_request_id"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_clubs_discovery", "clubs", ["status", "category", "id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("club_id", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("action", mysql.VARCHAR(80), nullable=False),
        sa.Column("resource_type", mysql.VARCHAR(48), nullable=False),
        sa.Column("resource_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("request_id", mysql.VARCHAR(64), nullable=False),
        sa.Column("safe_changes", mysql.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("purge_after", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_audit_logs_actor_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_audit_logs_club_id_clubs", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_audit_club", "audit_logs", ["club_id", "created_at", "id"])
    op.create_index("ix_audit_resource", "audit_logs", ["resource_type", "resource_id", "created_at", "id"])
    op.create_index("ix_audit_cleanup", "audit_logs", ["purge_after", "id"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])

    op.create_table(
        "ai_conversations",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("owner_user_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("title", mysql.VARCHAR(160), nullable=True),
        sa.Column("club_context_id", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("next_turn_no", mysql.INTEGER(unsigned=False), server_default="1", nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("deleted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("purge_after", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["club_context_id"], ["clubs.id"], name="fk_ai_conversations_club_context_id_clubs", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name="fk_ai_conversations_owner_user_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_conversations"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_ai_conversations_mine", "ai_conversations", ["owner_user_id", "deleted_at", "updated_at", "id"])
    op.create_index("ix_ai_conversations_cleanup", "ai_conversations", ["purge_after", "id"])
    op.create_index("ix_ai_conversations_club_context_id", "ai_conversations", ["club_context_id"])

    op.create_table(
        "membership_applications",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("club_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("motivation", mysql.VARCHAR(2000), nullable=True),
        sa.Column("status", mysql.ENUM("PENDING", "APPROVED", "REJECTED"), server_default="PENDING", nullable=False),
        sa.Column("pending_guard", mysql.TINYINT(unsigned=False), sa.Computed("CASE WHEN status = 'PENDING' THEN 1 ELSE NULL END", persisted=True), nullable=True),
        sa.Column("reviewed_by", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("rejection_reason", mysql.VARCHAR(1000), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_membership_applications_club_id_clubs", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name="fk_membership_applications_reviewed_by_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_membership_applications_user_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_membership_applications"),
        sa.UniqueConstraint("club_id", "user_id", "pending_guard", name="uq_membership_pending"),
        sa.UniqueConstraint("id", "club_id", "user_id", name="uq_membership_application_identity"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_membership_review", "membership_applications", ["club_id", "status", "created_at", "id"])
    op.create_index("ix_membership_app_mine", "membership_applications", ["user_id", "created_at", "id"])
    op.create_index("ix_membership_applications_reviewed_by", "membership_applications", ["reviewed_by"])

    op.create_table(
        "events",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("club_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("created_by", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("title", mysql.VARCHAR(200), nullable=False),
        sa.Column("description", mysql.TEXT(), nullable=False),
        sa.Column("location", mysql.VARCHAR(255), nullable=False),
        sa.Column("status", mysql.ENUM("DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED"), server_default="DRAFT", nullable=False),
        sa.Column("visibility", mysql.ENUM("PUBLIC_STUDENTS", "CLUB_MEMBERS_ONLY"), nullable=False),
        sa.Column("starts_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("ends_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("registration_opens_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("registration_closes_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("cancellation_deadline_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("capacity", mysql.INTEGER(unsigned=False), nullable=False),
        sa.Column("registration_count", mysql.INTEGER(unsigned=False), server_default="0", nullable=False),
        sa.Column("version", mysql.INTEGER(unsigned=False), server_default="0", nullable=False),
        sa.Column("published_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("cancelled_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("cancellation_reason", mysql.VARCHAR(1000), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("capacity > 0", name="ck_event_capacity"),
        sa.CheckConstraint("registration_count >= 0 AND registration_count <= capacity", name="ck_event_count_bounds"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_event_time"),
        sa.CheckConstraint("registration_closes_at > registration_opens_at", name="ck_event_registration_window"),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_events_club_id_clubs", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_events_created_by_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
        sa.UniqueConstraint("id", "club_id", name="uq_event_id_club"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_events_club", "events", ["club_id", "status", "starts_at", "id"])
    op.create_index("ix_events_discovery", "events", ["status", "visibility", "starts_at", "id"])
    op.create_index("ix_events_created_by", "events", ["created_by"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("family_id", mysql.BINARY(16), nullable=False),
        sa.Column("token_hash", mysql.BINARY(32), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("last_used_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("rotated_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("replaced_by_id", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("generation", mysql.INTEGER(unsigned=False), nullable=False),
        sa.Column("current_guard", mysql.TINYINT(unsigned=False), sa.Computed("CASE WHEN rotated_at IS NULL AND revoked_at IS NULL THEN 1 ELSE NULL END", persisted=True), nullable=True),
        sa.CheckConstraint("expires_at > created_at", name="ck_token_lifetime"),
        sa.CheckConstraint("generation >= 0", name="ck_token_generation"),
        sa.ForeignKeyConstraint(["family_id"], ["refresh_token_families.id"], name="fk_refresh_tokens_family_id_refresh_token_families", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["refresh_tokens.id"], name="fk_refresh_tokens_replaced_by_id_refresh_tokens", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("family_id", "current_guard", name="uq_token_one_current"),
        sa.UniqueConstraint("family_id", "generation", name="uq_token_family_generation"),
        sa.UniqueConstraint("replaced_by_id", name="uq_refresh_tokens_replaced_by_id"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_tokens_expiry_observation", "refresh_tokens", ["expires_at"])

    op.create_table(
        "ai_turns",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("conversation_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("client_request_key", mysql.BINARY(16), nullable=False),
        sa.Column("payload_hash", mysql.BINARY(32), nullable=False),
        sa.Column("turn_no", mysql.INTEGER(unsigned=False), nullable=False),
        sa.Column("status", mysql.ENUM("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"), server_default="PENDING", nullable=False),
        sa.Column("inflight_guard", mysql.TINYINT(unsigned=False), sa.Computed("CASE WHEN status IN ('PENDING','RUNNING') THEN 1 ELSE NULL END", persisted=True), nullable=True),
        sa.Column("lease_generation", mysql.INTEGER(unsigned=False), server_default="0", nullable=False),
        sa.Column("lease_expires_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"], name="fk_ai_turns_conversation_id_ai_conversations", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_turns"),
        sa.UniqueConstraint("conversation_id", "client_request_key", name="uq_ai_turn_request"),
        sa.UniqueConstraint("conversation_id", "inflight_guard", name="uq_ai_one_inflight_turn"),
        sa.UniqueConstraint("conversation_id", "turn_no", name="uq_ai_turn_order"),
        sa.UniqueConstraint("id", "conversation_id", name="uq_ai_turn_id_conversation"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_ai_turn_recovery", "ai_turns", ["status", "lease_expires_at", "id"])

    op.create_table(
        "club_memberships",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("club_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("source_application_id", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("role", mysql.ENUM("MEMBER", "MANAGER"), server_default="MEMBER", nullable=False),
        sa.Column("status", mysql.ENUM("ACTIVE", "LEFT", "REMOVED"), server_default="ACTIVE", nullable=False),
        sa.Column("active_guard", mysql.TINYINT(unsigned=False), sa.Computed("CASE WHEN status = 'ACTIVE' THEN 1 ELSE NULL END", persisted=True), nullable=True),
        sa.Column("joined_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("ended_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.CheckConstraint("(status = 'ACTIVE' AND ended_at IS NULL) OR (status <> 'ACTIVE' AND ended_at IS NOT NULL)", name="ck_membership_end_state"),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_club_memberships_club_id_clubs", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_application_id", "club_id", "user_id"], ["membership_applications.id", "membership_applications.club_id", "membership_applications.user_id"], name="fk_club_memberships_source_application_id_membership_applications", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_club_memberships_user_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_club_memberships"),
        sa.UniqueConstraint("club_id", "user_id", "active_guard", name="uq_membership_active"),
        sa.UniqueConstraint("id", "club_id", name="uq_membership_id_club"),
        sa.UniqueConstraint("source_application_id", name="uq_club_memberships_source_application_id"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_membership_source_identity", "club_memberships", ["source_application_id", "club_id", "user_id"])
    op.create_index("ix_membership_my_clubs", "club_memberships", ["user_id", "status", "club_id", "id"])
    op.create_index("ix_membership_manager_list", "club_memberships", ["club_id", "status", "role", "id"])

    op.create_table(
        "ai_usage_records",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("turn_id", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("attempt_no", mysql.INTEGER(unsigned=False), nullable=False),
        sa.Column("provider", mysql.VARCHAR(64), nullable=False),
        sa.Column("model", mysql.VARCHAR(120), nullable=False),
        sa.Column("provider_request_id", mysql.VARCHAR(160), nullable=True),
        sa.Column("status", mysql.ENUM("PENDING", "SUCCEEDED", "FAILED", "TIMEOUT", "UNKNOWN"), server_default="PENDING", nullable=False),
        sa.Column("usage_source", mysql.ENUM("PROVIDER", "ESTIMATED", "UNKNOWN"), server_default="UNKNOWN", nullable=False),
        sa.Column("input_tokens", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("output_tokens", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("estimated_cost", mysql.DECIMAL(18, 8), nullable=True),
        sa.Column("currency", mysql.CHAR(3), server_default="USD", nullable=False),
        sa.Column("pricing_reference", mysql.VARCHAR(160), nullable=True),
        sa.Column("duration_ms", mysql.INTEGER(unsigned=False), nullable=True),
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("purge_after", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="ck_ai_cost"),
        sa.CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_input_tokens"),
        sa.CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_output_tokens"),
        sa.ForeignKeyConstraint(["turn_id"], ["ai_turns.id"], name="fk_ai_usage_records_turn_id_ai_turns", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_usage_records"),
        sa.UniqueConstraint("turn_id", "attempt_no", name="uq_ai_usage_attempt"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_ai_usage_accounting", "ai_usage_records", ["created_at", "provider", "model"])
    op.create_index("ix_ai_usage_cleanup", "ai_usage_records", ["purge_after", "id"])

    op.create_table(
        "event_registrations",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("event_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("status", mysql.ENUM("REGISTERED", "CANCELLED"), server_default="REGISTERED", nullable=False),
        sa.Column("active_guard", mysql.TINYINT(unsigned=False), sa.Computed("CASE WHEN status = 'REGISTERED' THEN 1 ELSE NULL END", persisted=True), nullable=True),
        sa.Column("registered_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("cancelled_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("cancellation_reason", mysql.VARCHAR(100), nullable=True),
        sa.CheckConstraint("(status = 'REGISTERED' AND cancelled_at IS NULL) OR (status = 'CANCELLED' AND cancelled_at IS NOT NULL)", name="ck_registration_cancel_state"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_event_registrations_event_id_events", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_event_registrations_user_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_event_registrations"),
        sa.UniqueConstraint("event_id", "user_id", "active_guard", name="uq_registration_active"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_registration_participants", "event_registrations", ["event_id", "status", "registered_at", "id"])
    op.create_index("ix_registration_mine", "event_registrations", ["user_id", "status", "registered_at", "id"])

    op.create_table(
        "ai_messages",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("conversation_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("turn_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("role", mysql.ENUM("USER", "ASSISTANT"), nullable=False),
        sa.Column("status", mysql.ENUM("PENDING", "SUCCEEDED", "FAILED", "CANCELLED"), nullable=False),
        sa.Column("content", mysql.TEXT(), nullable=True),
        sa.Column("source_refs", mysql.JSON(), nullable=True),
        sa.Column("data_retrieved_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["turn_id", "conversation_id"], ["ai_turns.id", "ai_turns.conversation_id"], name="fk_ai_messages_turn_id_ai_turns", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_messages"),
        sa.UniqueConstraint("turn_id", "role", name="uq_ai_turn_message_role"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_ai_message_history", "ai_messages", ["conversation_id", "id"])
    op.create_index("ix_ai_message_turn_fk", "ai_messages", ["turn_id", "conversation_id"])

    op.create_table(
        "event_tasks",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("event_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("club_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("assignee_membership_id", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("created_by", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("title", mysql.VARCHAR(200), nullable=False),
        sa.Column("description", mysql.TEXT(), nullable=True),
        sa.Column("status", mysql.ENUM("TODO", "IN_PROGRESS", "DONE"), server_default="TODO", nullable=False),
        sa.Column("due_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("version", mysql.INTEGER(unsigned=False), server_default="0", nullable=False),
        sa.Column("completed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("(status = 'DONE' AND completed_at IS NOT NULL) OR (status <> 'DONE' AND completed_at IS NULL)", name="ck_task_completion"),
        sa.ForeignKeyConstraint(["assignee_membership_id", "club_id"], ["club_memberships.id", "club_memberships.club_id"], name="fk_event_tasks_assignee_membership_id_club_memberships", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_event_tasks_created_by_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_id", "club_id"], ["events.id", "events.club_id"], name="fk_event_tasks_event_id_events", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_event_tasks"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_task_event_fk", "event_tasks", ["event_id", "club_id"])
    op.create_index("ix_task_membership_fk", "event_tasks", ["assignee_membership_id", "club_id"])
    op.create_index("ix_tasks_event_board", "event_tasks", ["event_id", "status", "id"])
    op.create_index("ix_tasks_assignee", "event_tasks", ["assignee_membership_id", "status", "due_at", "id"])
    op.create_index("ix_event_tasks_created_by", "event_tasks", ["created_by"])

    op.create_table(
        "ai_tool_executions",
        sa.Column("id", mysql.BIGINT(unsigned=False), autoincrement=True, nullable=False),
        sa.Column("turn_id", mysql.BIGINT(unsigned=False), nullable=False),
        sa.Column("usage_record_id", mysql.BIGINT(unsigned=False), nullable=True),
        sa.Column("invocation_no", mysql.INTEGER(unsigned=False), nullable=False),
        sa.Column("tool_name", mysql.VARCHAR(80), nullable=False),
        sa.Column("status", mysql.ENUM("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "DENIED", "TIMEOUT"), server_default="PENDING", nullable=False),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("duration_ms", mysql.INTEGER(unsigned=False), nullable=True),
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True),
        sa.Column("safe_error_metadata", mysql.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["turn_id"], ["ai_turns.id"], name="fk_ai_tool_executions_turn_id_ai_turns", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usage_record_id"], ["ai_usage_records.id"], name="fk_ai_tool_executions_usage_record_id_ai_usage_records", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_tool_executions"),
        sa.UniqueConstraint("turn_id", "invocation_no", name="uq_ai_tool_invocation"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_ai_tool_usage_fk", "ai_tool_executions", ["usage_record_id", "id"])


def downgrade() -> None:
    for table_name in DOWNGRADE_TABLE_ORDER:
        op.drop_table(table_name)
