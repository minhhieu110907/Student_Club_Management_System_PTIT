from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.db.model_registry import Base


EXPECTED_TABLES = {
    "users", "refresh_token_families", "refresh_tokens", "club_creation_requests",
    "clubs", "membership_applications", "club_memberships", "events",
    "event_registrations", "event_tasks", "notifications", "outbox_events",
    "audit_logs", "ai_conversations", "ai_turns", "ai_messages",
    "ai_usage_records", "ai_tool_executions",
}
EXPECTED_CHECKS = {
    "ck_family_lifetime", "ck_family_retention", "ck_token_lifetime", "ck_token_generation",
    "ck_membership_end_state", "ck_event_capacity", "ck_event_count_bounds", "ck_event_time",
    "ck_event_registration_window", "ck_registration_cancel_state", "ck_task_completion",
    "ck_outbox_attempts", "ck_outbox_claim", "ck_outbox_published", "ck_ai_input_tokens",
    "ck_ai_output_tokens", "ck_ai_cost",
}
EXPECTED_FK_SUPPORTING_INDEXES = {
    "ix_club_creation_requests_reviewed_by", "ix_membership_applications_reviewed_by",
    "ix_events_created_by", "ix_event_tasks_created_by", "ix_audit_logs_actor_user_id",
    "ix_ai_conversations_club_context_id",
}
EXPECTED_FOREIGN_KEYS = {
    ("refresh_token_families", ("user_id",), ("users.id",), "RESTRICT", None),
    ("refresh_tokens", ("family_id",), ("refresh_token_families.id",), "CASCADE", None),
    ("refresh_tokens", ("replaced_by_id",), ("refresh_tokens.id",), "SET NULL", None),
    ("club_creation_requests", ("requested_by",), ("users.id",), "RESTRICT", None),
    ("club_creation_requests", ("reviewed_by",), ("users.id",), "RESTRICT", None),
    ("clubs", ("source_request_id",), ("club_creation_requests.id",), "RESTRICT", None),
    ("membership_applications", ("club_id",), ("clubs.id",), "RESTRICT", None),
    ("membership_applications", ("user_id",), ("users.id",), "RESTRICT", None),
    ("membership_applications", ("reviewed_by",), ("users.id",), "RESTRICT", None),
    ("club_memberships", ("club_id",), ("clubs.id",), "RESTRICT", None),
    ("club_memberships", ("user_id",), ("users.id",), "RESTRICT", None),
    ("club_memberships", ("source_application_id", "club_id", "user_id"), ("membership_applications.id", "membership_applications.club_id", "membership_applications.user_id"), "RESTRICT", "RESTRICT"),
    ("events", ("club_id",), ("clubs.id",), "RESTRICT", None),
    ("events", ("created_by",), ("users.id",), "RESTRICT", None),
    ("event_registrations", ("event_id",), ("events.id",), "RESTRICT", None),
    ("event_registrations", ("user_id",), ("users.id",), "RESTRICT", None),
    ("event_tasks", ("event_id", "club_id"), ("events.id", "events.club_id"), "RESTRICT", None),
    ("event_tasks", ("assignee_membership_id", "club_id"), ("club_memberships.id", "club_memberships.club_id"), "RESTRICT", None),
    ("event_tasks", ("created_by",), ("users.id",), "RESTRICT", None),
    ("notifications", ("user_id",), ("users.id",), "RESTRICT", None),
    ("audit_logs", ("actor_user_id",), ("users.id",), "SET NULL", None),
    ("audit_logs", ("club_id",), ("clubs.id",), "SET NULL", None),
    ("ai_conversations", ("owner_user_id",), ("users.id",), "RESTRICT", None),
    ("ai_conversations", ("club_context_id",), ("clubs.id",), "SET NULL", None),
    ("ai_turns", ("conversation_id",), ("ai_conversations.id",), "CASCADE", None),
    ("ai_messages", ("turn_id", "conversation_id"), ("ai_turns.id", "ai_turns.conversation_id"), "CASCADE", None),
    ("ai_usage_records", ("turn_id",), ("ai_turns.id",), "SET NULL", None),
    ("ai_tool_executions", ("turn_id",), ("ai_turns.id",), "CASCADE", None),
    ("ai_tool_executions", ("usage_record_id",), ("ai_usage_records.id",), "SET NULL", None),
}
EXPECTED_UNIQUE_COLUMNS = {
    ("users", ("email_normalized",)), ("refresh_tokens", ("token_hash",)),
    ("refresh_tokens", ("replaced_by_id",)), ("refresh_tokens", ("family_id", "generation")),
    ("refresh_tokens", ("family_id", "current_guard")), ("clubs", ("source_request_id",)),
    ("membership_applications", ("id", "club_id", "user_id")),
    ("membership_applications", ("club_id", "user_id", "pending_guard")),
    ("club_memberships", ("source_application_id",)), ("club_memberships", ("club_id", "user_id", "active_guard")),
    ("club_memberships", ("id", "club_id")), ("events", ("id", "club_id")),
    ("event_registrations", ("event_id", "user_id", "active_guard")),
    ("ai_turns", ("id", "conversation_id")), ("ai_turns", ("conversation_id", "client_request_key")),
    ("ai_turns", ("conversation_id", "turn_no")), ("ai_turns", ("conversation_id", "inflight_guard")),
    ("ai_messages", ("turn_id", "role")), ("ai_usage_records", ("turn_id", "attempt_no")),
    ("ai_tool_executions", ("turn_id", "invocation_no")),
}
EXPECTED_CHECK_EXPRESSIONS = {
    "ck_family_lifetime": "absolute_expires_at > created_at",
    "ck_family_retention": "purge_after >= absolute_expires_at",
    "ck_token_lifetime": "expires_at > created_at",
    "ck_token_generation": "generation >= 0",
    "ck_membership_end_state": "(status = 'ACTIVE' AND ended_at IS NULL) OR (status <> 'ACTIVE' AND ended_at IS NOT NULL)",
    "ck_event_capacity": "capacity > 0",
    "ck_event_count_bounds": "registration_count >= 0 AND registration_count <= capacity",
    "ck_event_time": "ends_at > starts_at",
    "ck_event_registration_window": "registration_closes_at > registration_opens_at",
    "ck_registration_cancel_state": "(status = 'REGISTERED' AND cancelled_at IS NULL) OR (status = 'CANCELLED' AND cancelled_at IS NOT NULL)",
    "ck_task_completion": "(status = 'DONE' AND completed_at IS NOT NULL) OR (status <> 'DONE' AND completed_at IS NULL)",
    "ck_outbox_attempts": "attempt_count >= 0",
    "ck_outbox_claim": "(status <> 'PROCESSING') OR (claim_token IS NOT NULL AND claimed_until IS NOT NULL)",
    "ck_outbox_published": "(status <> 'PUBLISHED') OR published_at IS NOT NULL",
    "ck_ai_input_tokens": "input_tokens IS NULL OR input_tokens >= 0",
    "ck_ai_output_tokens": "output_tokens IS NULL OR output_tokens >= 0",
    "ck_ai_cost": "estimated_cost IS NULL OR estimated_cost >= 0",
}
EXPECTED_COMPUTED_COLUMNS = {
    ("refresh_tokens", "current_guard"): "CASE WHEN rotated_at IS NULL AND revoked_at IS NULL THEN 1 ELSE NULL END",
    ("membership_applications", "pending_guard"): "CASE WHEN status = 'PENDING' THEN 1 ELSE NULL END",
    ("club_memberships", "active_guard"): "CASE WHEN status = 'ACTIVE' THEN 1 ELSE NULL END",
    ("event_registrations", "active_guard"): "CASE WHEN status = 'REGISTERED' THEN 1 ELSE NULL END",
    ("ai_turns", "inflight_guard"): "CASE WHEN status IN ('PENDING','RUNNING') THEN 1 ELSE NULL END",
}
EXPECTED_DEFAULTS = {
    ("users", "global_role"): "STUDENT", ("users", "status"): "ACTIVE",
    ("club_creation_requests", "status"): "PENDING", ("clubs", "status"): "ACTIVE",
    ("membership_applications", "status"): "PENDING", ("club_memberships", "role"): "MEMBER",
    ("club_memberships", "status"): "ACTIVE", ("events", "status"): "DRAFT",
    ("events", "registration_count"): "0", ("events", "version"): "0",
    ("event_registrations", "status"): "REGISTERED", ("event_tasks", "status"): "TODO",
    ("event_tasks", "version"): "0", ("outbox_events", "status"): "PENDING",
    ("outbox_events", "attempt_count"): "0", ("ai_conversations", "next_turn_no"): "1",
    ("ai_turns", "status"): "PENDING", ("ai_turns", "lease_generation"): "0",
    ("ai_usage_records", "status"): "PENDING", ("ai_usage_records", "usage_source"): "UNKNOWN",
    ("ai_usage_records", "currency"): "USD", ("ai_tool_executions", "status"): "PENDING",
}
EXPECTED_ENUMS = {
    ("users", "global_role"): ("STUDENT", "ADMIN"), ("users", "status"): ("ACTIVE", "DISABLED"),
    ("club_creation_requests", "status"): ("PENDING", "APPROVED", "REJECTED"),
    ("clubs", "status"): ("ACTIVE", "SUSPENDED"),
    ("membership_applications", "status"): ("PENDING", "APPROVED", "REJECTED"),
    ("club_memberships", "role"): ("MEMBER", "MANAGER"),
    ("club_memberships", "status"): ("ACTIVE", "LEFT", "REMOVED"),
    ("events", "status"): ("DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED"),
    ("events", "visibility"): ("PUBLIC_STUDENTS", "CLUB_MEMBERS_ONLY"),
    ("event_registrations", "status"): ("REGISTERED", "CANCELLED"),
    ("event_tasks", "status"): ("TODO", "IN_PROGRESS", "DONE"),
    ("outbox_events", "status"): ("PENDING", "PROCESSING", "PUBLISHED", "DEAD"),
    ("ai_turns", "status"): ("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"),
    ("ai_messages", "role"): ("USER", "ASSISTANT"),
    ("ai_messages", "status"): ("PENDING", "SUCCEEDED", "FAILED", "CANCELLED"),
    ("ai_usage_records", "status"): ("PENDING", "SUCCEEDED", "FAILED", "TIMEOUT", "UNKNOWN"),
    ("ai_usage_records", "usage_source"): ("PROVIDER", "ESTIMATED", "UNKNOWN"),
    ("ai_tool_executions", "status"): ("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "DENIED", "TIMEOUT"),
}
EXPECTED_INDEXES = {
    "ix_users_admin_state": ("users", ("status", "id")),
    "ix_families_user_sessions": ("refresh_token_families", ("user_id", "revoked_at", "id")),
    "ix_families_cleanup": ("refresh_token_families", ("purge_after", "id")),
    "ix_tokens_expiry_observation": ("refresh_tokens", ("expires_at",)),
    "ix_club_requests_mine": ("club_creation_requests", ("requested_by", "created_at", "id")),
    "ix_club_requests_review": ("club_creation_requests", ("status", "created_at", "id")),
    "ix_clubs_discovery": ("clubs", ("status", "category", "id")),
    "ix_membership_review": ("membership_applications", ("club_id", "status", "created_at", "id")),
    "ix_membership_app_mine": ("membership_applications", ("user_id", "created_at", "id")),
    "ix_membership_source_identity": ("club_memberships", ("source_application_id", "club_id", "user_id")),
    "ix_membership_my_clubs": ("club_memberships", ("user_id", "status", "club_id", "id")),
    "ix_membership_manager_list": ("club_memberships", ("club_id", "status", "role", "id")),
    "ix_events_club": ("events", ("club_id", "status", "starts_at", "id")),
    "ix_events_discovery": ("events", ("status", "visibility", "starts_at", "id")),
    "ix_registration_participants": ("event_registrations", ("event_id", "status", "registered_at", "id")),
    "ix_registration_mine": ("event_registrations", ("user_id", "status", "registered_at", "id")),
    "ix_task_event_fk": ("event_tasks", ("event_id", "club_id")),
    "ix_task_membership_fk": ("event_tasks", ("assignee_membership_id", "club_id")),
    "ix_tasks_event_board": ("event_tasks", ("event_id", "status", "id")),
    "ix_tasks_assignee": ("event_tasks", ("assignee_membership_id", "status", "due_at", "id")),
    "ix_notifications_inbox": ("notifications", ("user_id", "read_at", "created_at", "id")),
    "ix_notifications_cleanup": ("notifications", ("purge_after", "id")),
    "ix_outbox_due": ("outbox_events", ("status", "next_attempt_at", "id")),
    "ix_outbox_reclaim": ("outbox_events", ("status", "claimed_until", "id")),
    "ix_outbox_cleanup": ("outbox_events", ("purge_after", "id")),
    "ix_outbox_aggregate": ("outbox_events", ("aggregate_type", "aggregate_id", "created_at")),
    "ix_audit_club": ("audit_logs", ("club_id", "created_at", "id")),
    "ix_audit_resource": ("audit_logs", ("resource_type", "resource_id", "created_at", "id")),
    "ix_audit_cleanup": ("audit_logs", ("purge_after", "id")),
    "ix_ai_conversations_mine": ("ai_conversations", ("owner_user_id", "deleted_at", "updated_at", "id")),
    "ix_ai_conversations_cleanup": ("ai_conversations", ("purge_after", "id")),
    "ix_ai_turn_recovery": ("ai_turns", ("status", "lease_expires_at", "id")),
    "ix_ai_message_history": ("ai_messages", ("conversation_id", "id")),
    "ix_ai_message_turn_fk": ("ai_messages", ("turn_id", "conversation_id")),
    "ix_ai_usage_accounting": ("ai_usage_records", ("created_at", "provider", "model")),
    "ix_ai_usage_cleanup": ("ai_usage_records", ("purge_after", "id")),
    "ix_ai_tool_usage_fk": ("ai_tool_executions", ("usage_record_id", "id")),
    "ix_club_creation_requests_reviewed_by": ("club_creation_requests", ("reviewed_by",)),
    "ix_membership_applications_reviewed_by": ("membership_applications", ("reviewed_by",)),
    "ix_events_created_by": ("events", ("created_by",)),
    "ix_event_tasks_created_by": ("event_tasks", ("created_by",)),
    "ix_audit_logs_actor_user_id": ("audit_logs", ("actor_user_id",)),
    "ix_ai_conversations_club_context_id": ("ai_conversations", ("club_context_id",)),
}
EXPECTED_NULLABLE_COLUMNS = {
    ("refresh_token_families", "revoked_at"), ("refresh_token_families", "revoke_reason"),
    ("refresh_token_families", "suspicious_reuse_at"), ("refresh_tokens", "revoked_at"),
    ("refresh_tokens", "last_used_at"), ("refresh_tokens", "rotated_at"),
    ("refresh_tokens", "replaced_by_id"), ("refresh_tokens", "current_guard"),
    ("club_creation_requests", "reviewed_by"), ("club_creation_requests", "reviewed_at"),
    ("club_creation_requests", "rejection_reason"), ("membership_applications", "motivation"),
    ("membership_applications", "pending_guard"), ("membership_applications", "reviewed_by"),
    ("membership_applications", "reviewed_at"), ("membership_applications", "rejection_reason"),
    ("club_memberships", "source_application_id"), ("club_memberships", "active_guard"),
    ("club_memberships", "ended_at"), ("events", "cancellation_deadline_at"),
    ("events", "published_at"), ("events", "cancelled_at"), ("events", "cancellation_reason"),
    ("event_registrations", "active_guard"), ("event_registrations", "cancelled_at"),
    ("event_registrations", "cancellation_reason"), ("event_tasks", "assignee_membership_id"),
    ("event_tasks", "description"), ("event_tasks", "due_at"), ("event_tasks", "completed_at"),
    ("notifications", "resource_type"), ("notifications", "resource_id"), ("notifications", "read_at"),
    ("outbox_events", "claim_token"), ("outbox_events", "claimed_until"),
    ("outbox_events", "published_at"), ("outbox_events", "last_error_code"),
    ("outbox_events", "purge_after"), ("audit_logs", "actor_user_id"), ("audit_logs", "club_id"),
    ("audit_logs", "safe_changes"), ("ai_conversations", "title"),
    ("ai_conversations", "club_context_id"), ("ai_conversations", "deleted_at"),
    ("ai_turns", "inflight_guard"), ("ai_turns", "lease_expires_at"), ("ai_turns", "error_code"),
    ("ai_turns", "finished_at"), ("ai_messages", "content"), ("ai_messages", "source_refs"),
    ("ai_messages", "data_retrieved_at"), ("ai_usage_records", "turn_id"),
    ("ai_usage_records", "provider_request_id"), ("ai_usage_records", "input_tokens"),
    ("ai_usage_records", "output_tokens"), ("ai_usage_records", "estimated_cost"),
    ("ai_usage_records", "pricing_reference"), ("ai_usage_records", "duration_ms"),
    ("ai_usage_records", "error_code"), ("ai_usage_records", "finished_at"),
    ("ai_tool_executions", "usage_record_id"), ("ai_tool_executions", "started_at"),
    ("ai_tool_executions", "finished_at"), ("ai_tool_executions", "duration_ms"),
    ("ai_tool_executions", "error_code"), ("ai_tool_executions", "safe_error_metadata"),
}


def _foreign_keys() -> set[tuple[str, tuple[str, ...], tuple[str, ...], str | None, str | None]]:
    return {
        (table.name, tuple(fk.column_keys), tuple(item.target_fullname for item in fk.elements), fk.ondelete, fk.onupdate)
        for table in Base.metadata.tables.values()
        for fk in table.constraints
        if isinstance(fk, ForeignKeyConstraint)
    }


def test_tables_primary_keys_and_constraint_counts_match_dbml() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert len(Base.metadata.tables) == 18
    assert all(tuple(column.name for column in table.primary_key) == ("id",) for table in Base.metadata.tables.values())
    assert sum(isinstance(item, ForeignKeyConstraint) for table in Base.metadata.tables.values() for item in table.constraints) == 29
    unique_columns = {
        (table.name, tuple(column.name for column in item.columns))
        for table in Base.metadata.tables.values()
        for item in table.constraints
        if isinstance(item, UniqueConstraint)
    }
    assert unique_columns == EXPECTED_UNIQUE_COLUMNS
    assert len(unique_columns) == 20
    checks = {item.name for table in Base.metadata.tables.values() for item in table.constraints if isinstance(item, CheckConstraint)}
    assert checks == EXPECTED_CHECKS
    assert len(checks) == 17


def test_foreign_keys_include_dbml_composite_relationships_and_actions() -> None:
    foreign_keys = _foreign_keys()
    assert foreign_keys == EXPECTED_FOREIGN_KEYS


def test_generated_columns_mysql_types_collations_and_ddl() -> None:
    generated = {(table.name, column.name) for table in Base.metadata.tables.values() for column in table.columns if column.computed and column.computed.persisted}
    assert generated == {
        ("refresh_tokens", "current_guard"), ("membership_applications", "pending_guard"),
        ("club_memberships", "active_guard"), ("event_registrations", "active_guard"),
        ("ai_turns", "inflight_guard"),
    }
    assert Base.metadata.tables["users"].c.email_normalized.type.collation == "utf8mb4_0900_as_cs"
    assert Base.metadata.tables["ai_usage_records"].c.estimated_cost.type.precision == 18
    assert Base.metadata.tables["ai_usage_records"].c.estimated_cost.type.scale == 8
    ddl = {table.name: str(CreateTable(table).compile(dialect=mysql.dialect())) for table in Base.metadata.sorted_tables}
    assert len(ddl) == 18
    assert "COLLATE utf8mb4_0900_as_cs" in ddl["users"]
    assert "GENERATED ALWAYS AS" in ddl["ai_turns"]
    assert "CONSTRAINT ck_ai_cost CHECK" in ddl["ai_usage_records"]
    for table in Base.metadata.tables.values():
        assert table.dialect_options["mysql"]["engine"] == "InnoDB"
        assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
        assert table.dialect_options["mysql"]["collate"] == "utf8mb4_0900_ai_ci"


def test_exactly_six_explicit_fk_supporting_indexes_are_registered() -> None:
    index_names = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert EXPECTED_FK_SUPPORTING_INDEXES <= index_names
    assert len(EXPECTED_FK_SUPPORTING_INDEXES) == 6


def test_checks_computed_columns_and_defaults_match_dbml_contract() -> None:
    actual_checks = {
        constraint.name: " ".join(str(constraint.sqltext).split())
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert actual_checks == EXPECTED_CHECK_EXPRESSIONS
    actual_computed = {
        (table.name, column.name): (" ".join(str(column.computed.sqltext).split()), column.computed.persisted, column.nullable, type(column.type))
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.computed is not None
    }
    assert {key: value[0] for key, value in actual_computed.items()} == EXPECTED_COMPUTED_COLUMNS
    assert all(persisted and nullable and column_type is mysql.TINYINT for _, persisted, nullable, column_type in actual_computed.values())
    actual_defaults = {
        (table.name, column.name): str(column.server_default.arg)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.server_default is not None and column.computed is None
    }
    assert actual_defaults == EXPECTED_DEFAULTS


def test_native_mysql_types_enums_and_primary_key_generation_match_dbml() -> None:
    actual_enums = {
        (table.name, column.name): tuple(column.type.enums)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, mysql.ENUM)
    }
    assert actual_enums == EXPECTED_ENUMS
    primary_keys = [table.c.id for table in Base.metadata.tables.values()]
    assert all(column.primary_key and not column.nullable for column in primary_keys)
    assert all(column.autoincrement is True for column in primary_keys if column.table.name != "refresh_token_families")
    family_id = Base.metadata.tables["refresh_token_families"].c.id
    assert isinstance(family_id.type, mysql.BINARY) and family_id.type.length == 16
    assert family_id.autoincrement is not True
    binary_columns = {
        ("refresh_tokens", "family_id"): 16, ("refresh_tokens", "token_hash"): 32,
        ("outbox_events", "claim_token"): 16, ("ai_turns", "client_request_key"): 16,
        ("ai_turns", "payload_hash"): 32,
    }
    for (table_name, column_name), length in binary_columns.items():
        column = Base.metadata.tables[table_name].c[column_name]
        assert isinstance(column.type, mysql.BINARY) and column.type.length == length
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, mysql.BIGINT):
                assert column.type.unsigned is False
            if isinstance(column.type, mysql.DATETIME):
                assert column.type.fsp == 6
    cost = Base.metadata.tables["ai_usage_records"].c.estimated_cost.type
    assert isinstance(cost, mysql.DECIMAL) and (cost.precision, cost.scale) == (18, 8)
    actual_nullable = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.nullable
    }
    assert actual_nullable == EXPECTED_NULLABLE_COLUMNS


def test_all_declared_dbml_and_fk_supporting_indexes_match_exactly() -> None:
    actual_indexes = {
        index.name: (table.name, tuple(column.name for column in index.columns), index.unique)
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }
    assert actual_indexes == {name: (*definition, False) for name, definition in EXPECTED_INDEXES.items()}
    assert not set(EXPECTED_FK_SUPPORTING_INDEXES) - set(actual_indexes)
