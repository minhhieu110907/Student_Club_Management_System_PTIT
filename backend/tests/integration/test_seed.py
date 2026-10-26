from __future__ import annotations

import os

import pytest
import sqlalchemy as sa

from app.db.base import Base
from app.db import model_registry as _model_registry
from scripts.seed import EXPECTED_COUNTS, SeedError, seed_database


MAIN_URL = os.getenv("SCMS_SEED_INTEGRATION_URL")
ROLLBACK_URL = os.getenv("SCMS_SEED_ROLLBACK_URL")
CONFLICT_URL = os.getenv("SCMS_SEED_CONFLICT_URL")

pytestmark = pytest.mark.skipif(
    not all((MAIN_URL, ROLLBACK_URL, CONFLICT_URL)),
    reason="isolated seed integration database URLs are not configured",
)


@pytest.fixture(autouse=True)
def seed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCMS_ENV", "test")
    monkeypatch.setenv("SCMS_ALLOW_DEMO_SEED", "1")
    monkeypatch.delenv("SCMS_DEMO_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("SCMS_SEED_FAIL_AFTER_TABLE", raising=False)


def _engine(url: str | None) -> sa.Engine:
    assert url is not None
    return sa.create_engine(url, pool_pre_ping=True)


def _counts(connection: sa.Connection) -> dict[str, int]:
    return {
        name: connection.scalar(sa.select(sa.func.count()).select_from(Base.metadata.tables[name]))
        for name in EXPECTED_COUNTS
    }


def _identity_snapshot(connection: sa.Connection) -> dict[str, tuple[tuple[object, ...], ...]]:
    snapshot: dict[str, tuple[tuple[object, ...], ...]] = {}
    for name in sorted(EXPECTED_COUNTS):
        table = Base.metadata.tables[name]
        primary_keys = tuple(table.primary_key.columns)
        rows = connection.execute(sa.select(*primary_keys).order_by(*primary_keys)).all()
        snapshot[name] = tuple(tuple(row) for row in rows)
    return snapshot


def test_seed_is_idempotent_and_preserves_business_invariants() -> None:
    engine = _engine(MAIN_URL)
    try:
        first_counts = seed_database(engine)
        with engine.connect() as connection:
            first_snapshot = _identity_snapshot(connection)
        second_counts = seed_database(engine)
        with engine.connect() as connection:
            second_snapshot = _identity_snapshot(connection)

            assert first_counts == EXPECTED_COUNTS
            assert second_counts == EXPECTED_COUNTS
            assert second_snapshot == first_snapshot

            duplicate_active_memberships = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM (
                    SELECT club_id, user_id FROM club_memberships
                    WHERE status = 'ACTIVE' GROUP BY club_id, user_id HAVING COUNT(*) > 1
                ) AS duplicates
            """))
            assert duplicate_active_memberships == 0
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM club_memberships WHERE status IN ('LEFT','REMOVED')")) > 0

            duplicate_pending_applications = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM (
                    SELECT club_id, user_id FROM membership_applications
                    WHERE status = 'PENDING' GROUP BY club_id, user_id HAVING COUNT(*) > 1
                ) AS duplicates
            """))
            assert duplicate_pending_applications == 0

            event_count_mismatches = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM events AS e
                WHERE e.registration_count <> (
                    SELECT COUNT(*) FROM event_registrations AS r
                    WHERE r.event_id = e.id AND r.status = 'REGISTERED'
                )
            """))
            assert event_count_mismatches == 0

            duplicate_registrations = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM (
                    SELECT event_id, user_id FROM event_registrations
                    WHERE status = 'REGISTERED' GROUP BY event_id, user_id HAVING COUNT(*) > 1
                ) AS duplicates
            """))
            assert duplicate_registrations == 0

            invalid_active_event_registrations = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM event_registrations AS r
                JOIN events AS e ON e.id = r.event_id
                WHERE r.status = 'REGISTERED'
                  AND (
                    e.status <> 'PUBLISHED'
                    OR r.registered_at < e.registration_opens_at
                    OR r.registered_at > e.registration_closes_at
                  )
            """))
            assert invalid_active_event_registrations == 0

            nonmember_private_registrations = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM event_registrations AS r
                JOIN events AS e ON e.id = r.event_id
                WHERE r.status = 'REGISTERED'
                  AND e.visibility = 'CLUB_MEMBERS_ONLY'
                  AND NOT EXISTS (
                    SELECT 1 FROM club_memberships AS m
                    WHERE m.club_id = e.club_id
                      AND m.user_id = r.user_id
                      AND m.status = 'ACTIVE'
                  )
            """))
            assert nonmember_private_registrations == 0

            full_published_events = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM events
                WHERE status = 'PUBLISHED'
                  AND registration_count = capacity
                  AND capacity > 0
            """))
            assert full_published_events >= 1
            assert connection.scalar(sa.text("""
                SELECT COUNT(*) FROM event_registrations AS r
                JOIN events AS e ON e.id = r.event_id
                WHERE r.status = 'CANCELLED' AND e.status <> 'PUBLISHED'
            """)) > 0

            invalid_task_relationships = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM event_tasks AS t
                JOIN events AS e ON e.id = t.event_id
                LEFT JOIN club_memberships AS m ON m.id = t.assignee_membership_id
                WHERE t.club_id <> e.club_id
                   OR m.id IS NULL OR m.club_id <> t.club_id OR m.status <> 'ACTIVE'
            """))
            assert invalid_task_relationships == 0

            invalid_ai_messages = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM ai_messages AS m
                LEFT JOIN ai_turns AS t
                  ON t.id = m.turn_id AND t.conversation_id = m.conversation_id
                WHERE t.id IS NULL
            """))
            assert invalid_ai_messages == 0

            duplicate_inflight_turns = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM (
                    SELECT conversation_id FROM ai_turns
                    WHERE status IN ('PENDING','RUNNING')
                    GROUP BY conversation_id HAVING COUNT(*) > 1
                ) AS duplicates
            """))
            assert duplicate_inflight_turns == 0

            assert connection.scalar(sa.text("SELECT COUNT(*) FROM users WHERE password_hash = '!SCMS_DEMO_LOGIN_DISABLED!'")) == EXPECTED_COUNTS["users"]
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM refresh_tokens WHERE OCTET_LENGTH(token_hash) = 32")) == EXPECTED_COUNTS["refresh_tokens"]
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM refresh_token_families WHERE revoked_at IS NULL")) == 0
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM refresh_tokens WHERE current_guard IS NOT NULL")) == 0
            invalid_replacement_links = connection.scalar(sa.text("""
                SELECT COUNT(*) FROM refresh_tokens AS token
                LEFT JOIN refresh_tokens AS successor
                  ON successor.family_id = token.family_id
                 AND successor.generation = token.generation + 1
                WHERE (
                    successor.id IS NOT NULL
                    AND (token.replaced_by_id IS NULL OR token.replaced_by_id <> successor.id)
                ) OR (
                    successor.id IS NULL AND token.replaced_by_id IS NOT NULL
                )
            """))
            assert invalid_replacement_links == 0
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM audit_logs WHERE JSON_EXTRACT(safe_changes, '$.synthetic') = TRUE")) == EXPECTED_COUNTS["audit_logs"]
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM outbox_events WHERE JSON_EXTRACT(payload, '$.synthetic') = TRUE")) == EXPECTED_COUNTS["outbox_events"]
    finally:
        engine.dispose()


def test_seed_rolls_back_entire_transaction_on_injected_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCMS_SEED_FAIL_AFTER_TABLE", "users")
    engine = _engine(ROLLBACK_URL)
    try:
        with pytest.raises(SeedError, match="Injected seed failure after users"):
            seed_database(engine)
        with engine.connect() as connection:
            assert _counts(connection) == {name: 0 for name in EXPECTED_COUNTS}
    finally:
        engine.dispose()


def test_seed_rejects_stable_key_collision_without_partial_writes() -> None:
    engine = _engine(CONFLICT_URL)
    users = Base.metadata.tables["users"]
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.insert(users).values(
                    email_normalized="admin@demo.scms.invalid",
                    full_name="Conflicting Existing Account",
                    password_hash="!EXISTING_ACCOUNT!",
                    global_role="STUDENT",
                    status="ACTIVE",
                    created_at="2026-01-01 00:00:00.000000",
                    updated_at="2026-01-01 00:00:00.000000",
                )
            )
        with pytest.raises(SeedError, match="Seed collision in users"):
            seed_database(engine)
        with engine.connect() as connection:
            counts = _counts(connection)
            assert counts["users"] == 1
            assert all(count == 0 for table, count in counts.items() if table != "users")
    finally:
        engine.dispose()


def test_seed_refuses_production_before_database_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCMS_ENV", "production")
    with pytest.raises(SeedError, match="Demo seed refused"):
        seed_database(object())  # type: ignore[arg-type]
