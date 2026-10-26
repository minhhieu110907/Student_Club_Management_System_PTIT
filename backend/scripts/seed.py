"""Deterministic, idempotent SCMS demo seed.

This module is deliberately not imported by application startup. Run it explicitly with
SCMS_ENV=development (or demo/test), SCMS_ALLOW_DEMO_SEED=1, and
SCMS_SEED_DATABASE_URL set to a MySQL database that has already been migrated.
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from app.db import model_registry as _model_registry
from app.db.base import Base


SEED_NAMESPACE = "scms-demo-v1"
ALLOWED_ENVIRONMENTS = frozenset({"development", "demo", "test"})
BASE_TIME = datetime(2026, 9, 1, 9, 0, 0)
DISABLED_PASSWORD_HASH = "!SCMS_DEMO_LOGIN_DISABLED!"

USER_MANIFEST = (
    ("admin@demo.scms.invalid", "Avery System Admin", "ADMIN", "ACTIVE"),
    ("alex@demo.scms.invalid", "Alex Nguyen", "STUDENT", "ACTIVE"),
    ("bao@demo.scms.invalid", "Bao Tran", "STUDENT", "ACTIVE"),
    ("chi@demo.scms.invalid", "Chi Le", "STUDENT", "ACTIVE"),
    ("dana@demo.scms.invalid", "Dana Pham", "STUDENT", "ACTIVE"),
    ("eli@demo.scms.invalid", "Eli Vo", "STUDENT", "ACTIVE"),
    ("farah@demo.scms.invalid", "Farah Do", "STUDENT", "ACTIVE"),
    ("gia@demo.scms.invalid", "Gia Hoang", "STUDENT", "ACTIVE"),
    ("han@demo.scms.invalid", "Han Bui", "STUDENT", "ACTIVE"),
    ("ivy@demo.scms.invalid", "Ivy Dang", "STUDENT", "ACTIVE"),
    ("jay@demo.scms.invalid", "Jay Lam", "STUDENT", "ACTIVE"),
    ("kim@demo.scms.invalid", "Kim Chau", "STUDENT", "ACTIVE"),
    ("linh@demo.scms.invalid", "Linh Truong", "STUDENT", "ACTIVE"),
    ("minh@demo.scms.invalid", "Minh Ngo", "STUDENT", "ACTIVE"),
    ("disabled@demo.scms.invalid", "Disabled Demo Account", "STUDENT", "DISABLED"),
)

CLUB_REQUEST_MANIFEST = (
    ("Robotics Collective", "Technology", "APPROVED", "alex@demo.scms.invalid"),
    ("Green Campus Society", "Community", "APPROVED", "bao@demo.scms.invalid"),
    ("Visual Storytelling Club", "Arts", "APPROVED", "chi@demo.scms.invalid"),
    ("Competitive Coding Guild", "Technology", "APPROVED", "dana@demo.scms.invalid"),
    ("Midnight Drone Racing", "Sports", "REJECTED", "eli@demo.scms.invalid"),
    ("Language Exchange Circle", "Culture", "PENDING", "farah@demo.scms.invalid"),
)

CLUB_MANIFEST = (
    ("Robotics Collective", "ACTIVE"),
    ("Green Campus Society", "ACTIVE"),
    ("Visual Storytelling Club", "ACTIVE"),
    ("Competitive Coding Guild", "SUSPENDED"),
)

EXPECTED_COUNTS = {
    "users": 15,
    "refresh_token_families": 3,
    "refresh_tokens": 5,
    "club_creation_requests": 6,
    "clubs": 4,
    "membership_applications": 23,
    "club_memberships": 25,
    "events": 10,
    "event_registrations": 35,
    "event_tasks": 15,
    "notifications": 15,
    "audit_logs": 6,
    "ai_conversations": 3,
    "ai_turns": 5,
    "ai_messages": 10,
    "ai_usage_records": 5,
    "ai_tool_executions": 4,
    "outbox_events": 6,
}


class SeedError(RuntimeError):
    """Raised when seed safety or stable-key consistency checks fail."""


def _at(days: int = 0, hours: int = 0) -> datetime:
    return BASE_TIME + timedelta(days=days, hours=hours)


def _stable_bytes(label: str, length: int) -> bytes:
    return hashlib.sha256(f"{SEED_NAMESPACE}:{label}".encode()).digest()[:length]


def _password_hash() -> str:
    value = os.getenv("SCMS_DEMO_PASSWORD_HASH")
    if value is None:
        return DISABLED_PASSWORD_HASH
    if not value.startswith(("$2a$", "$2b$", "$2y$", "$argon2")):
        raise SeedError("SCMS_DEMO_PASSWORD_HASH must contain a pre-hashed bcrypt or Argon2 value")
    return value


def _validate_environment() -> None:
    environment = os.getenv("SCMS_ENV", "").strip().lower()
    if environment not in ALLOWED_ENVIRONMENTS:
        raise SeedError(
            "Demo seed refused: SCMS_ENV must be one of development, demo, or test"
        )
    if os.getenv("SCMS_ALLOW_DEMO_SEED") != "1":
        raise SeedError("Demo seed refused: set SCMS_ALLOW_DEMO_SEED=1 explicitly")


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return value.normalize()
    if isinstance(value, Mapping):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _ensure_row(
    connection: Connection,
    table: sa.Table,
    key: Mapping[str, Any],
    values: Mapping[str, Any],
    *,
    compare: Iterable[str] | None = None,
) -> Mapping[str, Any]:
    predicates = [table.c[name] == value for name, value in key.items()]
    existing = connection.execute(sa.select(table).where(*predicates)).mappings().one_or_none()
    if existing is not None:
        names = tuple(compare) if compare is not None else tuple(values)
        mismatches = [
            name
            for name in names
            if _normalize(existing[name]) != _normalize(values[name])
        ]
        if mismatches:
            identity = ", ".join(f"{name}={value!r}" for name, value in key.items())
            raise SeedError(
                f"Seed collision in {table.name} for {identity}; conflicting fields: "
                + ", ".join(mismatches)
            )
        return existing

    result = connection.execute(sa.insert(table).values(**values))
    primary_key = tuple(result.inserted_primary_key)
    if len(primary_key) == 1 and primary_key[0] is not None:
        return connection.execute(
            sa.select(table).where(next(iter(table.primary_key.columns)) == primary_key[0])
        ).mappings().one()
    return connection.execute(sa.select(table).where(*predicates)).mappings().one()


def _maybe_fail(table_name: str) -> None:
    requested = os.getenv("SCMS_SEED_FAIL_AFTER_TABLE")
    if requested:
        if os.getenv("SCMS_ENV", "").strip().lower() != "test":
            raise SeedError("Failure injection is allowed only when SCMS_ENV=test")
        if requested == table_name:
            raise SeedError(f"Injected seed failure after {table_name}")


def _seed(connection: Connection) -> dict[str, int]:
    tables = Base.metadata.tables
    password_hash = _password_hash()
    users: dict[str, int] = {}
    for index, (email, name, role, status) in enumerate(USER_MANIFEST):
        values = {
            "email_normalized": email,
            "full_name": name,
            "password_hash": password_hash,
            "global_role": role,
            "status": status,
            "created_at": _at(hours=index),
            "updated_at": _at(hours=index),
        }
        row = _ensure_row(connection, tables["users"], {"email_normalized": email}, values)
        users[email] = row["id"]
    _maybe_fail("users")

    requests: dict[str, int] = {}
    admin_id = users["admin@demo.scms.invalid"]
    for index, (name, category, status, requester) in enumerate(CLUB_REQUEST_MANIFEST):
        reviewed = status != "PENDING"
        values = {
            "requested_by": users[requester],
            "proposed_name": name,
            "category": category,
            "mission": f"Synthetic mission for {name}.",
            "initial_plan": f"Synthetic first-semester plan for {name}.",
            "status": status,
            "reviewed_by": admin_id if reviewed else None,
            "reviewed_at": _at(2, index) if reviewed else None,
            "rejection_reason": "Scope is unsafe for the campus demo." if status == "REJECTED" else None,
            "created_at": _at(1, index),
            "updated_at": _at(2, index) if reviewed else _at(1, index),
        }
        row = _ensure_row(
            connection,
            tables["club_creation_requests"],
            {"requested_by": users[requester], "proposed_name": name},
            values,
        )
        requests[name] = row["id"]
    _maybe_fail("club_creation_requests")

    clubs: dict[str, int] = {}
    for index, (name, status) in enumerate(CLUB_MANIFEST):
        category = next(item[1] for item in CLUB_REQUEST_MANIFEST if item[0] == name)
        values = {
            "source_request_id": requests[name],
            "name": name,
            "category": category,
            "description": f"Fictional SCMS demonstration club: {name}.",
            "status": status,
            "created_at": _at(3, index),
            "updated_at": _at(3, index),
        }
        row = _ensure_row(connection, tables["clubs"], {"source_request_id": requests[name]}, values)
        clubs[name] = row["id"]
    _maybe_fail("clubs")

    student_emails = [item[0] for item in USER_MANIFEST[1:14]]
    club_names = [item[0] for item in CLUB_MANIFEST]
    application_specs: list[tuple[str, str, str]] = []
    for index in range(21):
        application_specs.append((club_names[index % 4], student_emails[(index + 4) % len(student_emails)], "APPROVED"))
    application_specs.extend(
        [
            (club_names[1], student_emails[1], "REJECTED"),
            (club_names[2], student_emails[2], "PENDING"),
        ]
    )
    applications: list[Mapping[str, Any]] = []
    for index, (club_name, email, status) in enumerate(application_specs):
        created_at = _at(4 + index, index % 5)
        reviewed = status != "PENDING"
        values = {
            "club_id": clubs[club_name],
            "user_id": users[email],
            "motivation": f"Synthetic application {index + 1} for {club_name}.",
            "status": status,
            "reviewed_by": admin_id if reviewed else None,
            "reviewed_at": created_at + timedelta(hours=3) if reviewed else None,
            "rejection_reason": "Demo capacity planning." if status == "REJECTED" else None,
            "created_at": created_at,
        }
        applications.append(
            _ensure_row(
                connection,
                tables["membership_applications"],
                {"club_id": clubs[club_name], "user_id": users[email], "created_at": created_at},
                values,
            )
        )
    _maybe_fail("membership_applications")

    memberships: list[Mapping[str, Any]] = []
    founders = [item[3] for item in CLUB_REQUEST_MANIFEST[:4]]
    for index, club_name in enumerate(club_names):
        joined_at = _at(3, index + 1)
        values = {
            "club_id": clubs[club_name],
            "user_id": users[founders[index]],
            "source_application_id": None,
            "role": "MANAGER",
            "status": "ACTIVE",
            "joined_at": joined_at,
            "ended_at": None,
        }
        memberships.append(
            _ensure_row(
                connection,
                tables["club_memberships"],
                {"club_id": clubs[club_name], "user_id": users[founders[index]], "joined_at": joined_at},
                values,
            )
        )
    for index, application in enumerate(applications[:21]):
        status = "ACTIVE" if index < 15 else ("LEFT" if index < 18 else "REMOVED")
        joined_at = application["created_at"] + timedelta(hours=4)
        values = {
            "club_id": application["club_id"],
            "user_id": application["user_id"],
            "source_application_id": application["id"],
            "role": "MANAGER" if index in {0, 7} else "MEMBER",
            "status": status,
            "joined_at": joined_at,
            "ended_at": None if status == "ACTIVE" else joined_at + timedelta(days=20),
        }
        memberships.append(
            _ensure_row(
                connection,
                tables["club_memberships"],
                {"source_application_id": application["id"]},
                values,
            )
        )
    _maybe_fail("club_memberships")

    events: list[Mapping[str, Any]] = []
    event_statuses = ("PUBLISHED", "PUBLISHED", "DRAFT", "COMPLETED", "PUBLISHED", "CANCELLED", "PUBLISHED", "DRAFT", "PUBLISHED", "COMPLETED")
    for index in range(10):
        club_name = club_names[index % 4]
        starts_at = _at(70 + index * 3)
        status = event_statuses[index]
        capacity = 4 if index == 0 else 8
        values = {
            "club_id": clubs[club_name],
            "created_by": users[founders[index % 4]],
            "title": f"SCMS Demo Event {index + 1:02d}",
            "description": f"Synthetic event scenario {index + 1}.",
            "location": f"Demo Room {index + 1}",
            "status": status,
            "visibility": "PUBLIC_STUDENTS" if index % 2 == 0 else "CLUB_MEMBERS_ONLY",
            "starts_at": starts_at,
            "ends_at": starts_at + timedelta(hours=2),
            "registration_opens_at": starts_at - timedelta(days=20),
            "registration_closes_at": starts_at - timedelta(days=1),
            "cancellation_deadline_at": starts_at - timedelta(days=2),
            "capacity": capacity,
            "registration_count": 0,
            "version": 0,
            "published_at": starts_at - timedelta(days=19) if status in {"PUBLISHED", "COMPLETED", "CANCELLED"} else None,
            "cancelled_at": starts_at - timedelta(days=3) if status == "CANCELLED" else None,
            "cancellation_reason": "Synthetic weather scenario." if status == "CANCELLED" else None,
            "created_at": starts_at - timedelta(days=25),
            "updated_at": starts_at - timedelta(days=19),
        }
        events.append(
            _ensure_row(
                connection,
                tables["events"],
                {"club_id": clubs[club_name], "title": values["title"]},
                values,
                compare=tuple(name for name in values if name != "registration_count"),
            )
        )
    _maybe_fail("events")

    memberships_by_club: dict[int, list[Mapping[str, Any]]] = {}
    for membership in memberships:
        if membership["status"] == "ACTIVE":
            memberships_by_club.setdefault(membership["club_id"], []).append(membership)
    private_event_registrants = (
        "bao@demo.scms.invalid",
        "farah@demo.scms.invalid",
        "jay@demo.scms.invalid",
        "alex@demo.scms.invalid",
    )

    registration_counts: dict[int, int] = {event["id"]: 0 for event in events}
    for index in range(35):
        event = events[index % 10]
        if event["visibility"] == "CLUB_MEMBERS_ONLY" and event["status"] == "PUBLISHED":
            registration_user_id = users[private_event_registrants[index // 10]]
        else:
            email = student_emails[(index // 10 + index) % len(student_emails)]
            registration_user_id = users[email]
        status = (
            "REGISTERED"
            if event["status"] == "PUBLISHED" and index not in {14, 18}
            else "CANCELLED"
        )
        registered_at = event["registration_opens_at"] + timedelta(hours=index + 1)
        values = {
            "event_id": event["id"],
            "user_id": registration_user_id,
            "status": status,
            "registered_at": registered_at,
            "cancelled_at": registered_at + timedelta(days=1) if status == "CANCELLED" else None,
            "cancellation_reason": "Synthetic schedule conflict." if status == "CANCELLED" else None,
        }
        registration_key = (
            {"event_id": event["id"], "user_id": registration_user_id, "status": "REGISTERED"}
            if status == "REGISTERED"
            else {"event_id": event["id"], "user_id": registration_user_id, "registered_at": registered_at}
        )
        _ensure_row(
            connection,
            tables["event_registrations"],
            registration_key,
            values,
        )
        if status == "REGISTERED":
            registration_counts[event["id"]] += 1
    for event in events:
        connection.execute(
            sa.update(tables["events"])
            .where(tables["events"].c.id == event["id"], tables["events"].c.registration_count == 0)
            .values(registration_count=registration_counts[event["id"]])
        )
        actual = connection.scalar(sa.select(tables["events"].c.registration_count).where(tables["events"].c.id == event["id"]))
        if actual != registration_counts[event["id"]]:
            raise SeedError(f"Seed collision in events registration_count for id={event['id']}")
    _maybe_fail("event_registrations")

    for index in range(15):
        event = events[index % 10]
        candidates = memberships_by_club[event["club_id"]]
        assignee = candidates[index % len(candidates)]
        status = ("TODO", "IN_PROGRESS", "DONE")[index % 3]
        created_at = event["created_at"] + timedelta(days=1, hours=index)
        values = {
            "event_id": event["id"],
            "club_id": event["club_id"],
            "assignee_membership_id": assignee["id"],
            "created_by": event["created_by"],
            "title": f"Demo task {index + 1:02d}",
            "description": "Synthetic event preparation task.",
            "status": status,
            "due_at": event["starts_at"] - timedelta(days=2),
            "version": 0,
            "completed_at": created_at + timedelta(days=2) if status == "DONE" else None,
            "created_at": created_at,
            "updated_at": created_at + timedelta(hours=1),
        }
        _ensure_row(
            connection,
            tables["event_tasks"],
            {"event_id": event["id"], "title": values["title"]},
            values,
        )
    _maybe_fail("event_tasks")

    for index in range(15):
        email = USER_MANIFEST[index][0]
        created_at = _at(45, index)
        values = {
            "user_id": users[email],
            "type": "DEMO_EVENT_REMINDER" if index % 2 == 0 else "DEMO_MEMBERSHIP_UPDATE",
            "resource_type": "event" if index % 2 == 0 else "club",
            "resource_id": events[index % 10]["id"] if index % 2 == 0 else clubs[club_names[index % 4]],
            "safe_summary": f"Synthetic notification {index + 1}; contains no personal data.",
            "read_at": created_at + timedelta(hours=1) if index % 3 == 0 else None,
            "created_at": created_at,
            "purge_after": created_at + timedelta(days=90),
        }
        _ensure_row(
            connection,
            tables["notifications"],
            {"user_id": users[email], "type": values["type"], "created_at": created_at},
            values,
        )
    _maybe_fail("notifications")

    for index in range(6):
        created_at = _at(50, index)
        values = {
            "actor_user_id": admin_id if index < 4 else users[student_emails[index]],
            "club_id": clubs[club_names[index % 4]],
            "action": "DEMO_REVIEW" if index < 4 else "DEMO_UPDATE",
            "resource_type": "club",
            "resource_id": clubs[club_names[index % 4]],
            "request_id": f"demo-request-{index + 1:02d}",
            "safe_changes": {"synthetic": True, "sequence": index + 1},
            "created_at": created_at,
            "purge_after": created_at + timedelta(days=365),
        }
        _ensure_row(connection, tables["audit_logs"], {"request_id": values["request_id"]}, values)
    _maybe_fail("audit_logs")

    conversations: list[Mapping[str, Any]] = []
    for index in range(3):
        created_at = _at(55, index)
        values = {
            "owner_user_id": users[student_emails[index]],
            "title": f"Demo assistant conversation {index + 1}",
            "club_context_id": clubs[club_names[index]] if index < 2 else None,
            "next_turn_no": 3 if index < 2 else 2,
            "created_at": created_at,
            "updated_at": created_at + timedelta(hours=2),
            "deleted_at": None,
            "purge_after": created_at + timedelta(days=90),
        }
        conversations.append(
            _ensure_row(
                connection,
                tables["ai_conversations"],
                {"owner_user_id": values["owner_user_id"], "title": values["title"]},
                values,
            )
        )
    _maybe_fail("ai_conversations")

    turns: list[Mapping[str, Any]] = []
    for index in range(5):
        conversation = conversations[0 if index < 2 else (1 if index < 4 else 2)]
        turn_no = 1 if index in {0, 2, 4} else 2
        created_at = conversation["created_at"] + timedelta(hours=turn_no)
        status = "RUNNING" if index == 4 else ("FAILED" if index == 3 else "SUCCEEDED")
        values = {
            "conversation_id": conversation["id"],
            "client_request_key": _stable_bytes(f"turn-request-{index + 1}", 16),
            "payload_hash": _stable_bytes(f"turn-payload-{index + 1}", 32),
            "turn_no": turn_no,
            "status": status,
            "lease_generation": 1 if status == "RUNNING" else 0,
            "lease_expires_at": created_at + timedelta(minutes=5) if status == "RUNNING" else None,
            "error_code": "DEMO_PROVIDER_TIMEOUT" if status == "FAILED" else None,
            "created_at": created_at,
            "finished_at": None if status == "RUNNING" else created_at + timedelta(seconds=2),
        }
        turns.append(
            _ensure_row(
                connection,
                tables["ai_turns"],
                {"conversation_id": conversation["id"], "client_request_key": values["client_request_key"]},
                values,
            )
        )
    _maybe_fail("ai_turns")

    for index, turn in enumerate(turns):
        for role in ("USER", "ASSISTANT"):
            status = "PENDING" if turn["status"] == "RUNNING" and role == "ASSISTANT" else ("FAILED" if turn["status"] == "FAILED" and role == "ASSISTANT" else "SUCCEEDED")
            values = {
                "conversation_id": turn["conversation_id"],
                "turn_id": turn["id"],
                "role": role,
                "status": status,
                "content": f"Synthetic {role.lower()} message for turn {index + 1}." if status != "PENDING" else None,
                "source_refs": {"synthetic": True} if role == "ASSISTANT" and status == "SUCCEEDED" else None,
                "data_retrieved_at": turn["created_at"] if role == "ASSISTANT" and status == "SUCCEEDED" else None,
                "created_at": turn["created_at"] + timedelta(milliseconds=100 if role == "USER" else 500),
                "updated_at": turn["created_at"] + timedelta(milliseconds=100 if role == "USER" else 500),
            }
            _ensure_row(connection, tables["ai_messages"], {"turn_id": turn["id"], "role": role}, values)
    _maybe_fail("ai_messages")

    usages: list[Mapping[str, Any]] = []
    for index, turn in enumerate(turns):
        succeeded = turn["status"] == "SUCCEEDED"
        values = {
            "turn_id": turn["id"],
            "attempt_no": 1,
            "provider": "mock",
            "model": "scms-demo-model-v1",
            "provider_request_id": f"synthetic-provider-request-{index + 1}",
            "status": "SUCCEEDED" if succeeded else ("PENDING" if turn["status"] == "RUNNING" else "TIMEOUT"),
            "usage_source": "ESTIMATED" if succeeded else "UNKNOWN",
            "input_tokens": 40 + index if succeeded else None,
            "output_tokens": 20 + index if succeeded else None,
            "estimated_cost": Decimal("0.00010000") * (index + 1) if succeeded else None,
            "currency": "USD",
            "pricing_reference": "synthetic-demo-pricing",
            "duration_ms": 500 + index * 25 if turn["status"] != "RUNNING" else None,
            "error_code": "DEMO_TIMEOUT" if turn["status"] == "FAILED" else None,
            "created_at": turn["created_at"],
            "finished_at": turn["finished_at"],
            "purge_after": turn["created_at"] + timedelta(days=90),
        }
        usages.append(_ensure_row(connection, tables["ai_usage_records"], {"turn_id": turn["id"], "attempt_no": 1}, values))
    _maybe_fail("ai_usage_records")

    for index in range(4):
        turn = turns[index]
        values = {
            "turn_id": turn["id"],
            "usage_record_id": usages[index]["id"],
            "invocation_no": 1,
            "tool_name": ("list_upcoming_events", "get_my_registrations", "get_my_tasks", "get_event_progress")[index],
            "status": "FAILED" if turn["status"] == "FAILED" else "SUCCEEDED",
            "started_at": turn["created_at"] + timedelta(milliseconds=200),
            "finished_at": turn["created_at"] + timedelta(milliseconds=400),
            "duration_ms": 200,
            "error_code": "DEMO_TOOL_TIMEOUT" if turn["status"] == "FAILED" else None,
            "safe_error_metadata": {"synthetic": True} if turn["status"] == "FAILED" else None,
        }
        _ensure_row(connection, tables["ai_tool_executions"], {"turn_id": turn["id"], "invocation_no": 1}, values)
    _maybe_fail("ai_tool_executions")

    for index in range(6):
        created_at = _at(60, index)
        status = ("PENDING", "PUBLISHED", "PUBLISHED", "DEAD", "PENDING", "PUBLISHED")[index]
        values = {
            "event_type": f"demo.event.{index + 1}",
            "aggregate_type": "event",
            "aggregate_id": events[index]["id"],
            "payload": {"synthetic": True, "event_number": index + 1},
            "status": status,
            "attempt_count": 0 if status == "PENDING" else 1,
            "next_attempt_at": created_at,
            "claim_token": None,
            "claimed_until": None,
            "published_at": created_at + timedelta(seconds=1) if status == "PUBLISHED" else None,
            "last_error_code": "DEMO_DELIVERY_EXHAUSTED" if status == "DEAD" else None,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=1),
            "purge_after": created_at + timedelta(days=30) if status in {"PUBLISHED", "DEAD"} else None,
        }
        _ensure_row(
            connection,
            tables["outbox_events"],
            {"event_type": values["event_type"], "aggregate_type": "event", "aggregate_id": events[index]["id"]},
            values,
        )
    _maybe_fail("outbox_events")

    family_specs = (
        ("family-revoked-single", student_emails[0], _at(34), "DEMO_NON_REUSABLE"),
        ("family-rotated", student_emails[1], _at(35), "ROTATED_DEMO"),
        ("family-revoked", student_emails[2], _at(36), "USER_SIGN_OUT_DEMO"),
    )
    families: list[Mapping[str, Any]] = []
    for index, (label, email, revoked_at, reason) in enumerate(family_specs):
        family_id = uuid.UUID(bytes=_stable_bytes(label, 16)).bytes
        values = {
            "id": family_id,
            "user_id": users[email],
            "created_at": _at(30, index),
            "absolute_expires_at": _at(120, index),
            "revoked_at": revoked_at,
            "revoke_reason": reason,
            "suspicious_reuse_at": None,
            "purge_after": _at(150, index),
        }
        families.append(_ensure_row(connection, tables["refresh_token_families"], {"id": family_id}, values))
    _maybe_fail("refresh_token_families")

    token_specs = ((0, 0, False), (1, 0, True), (1, 1, False), (2, 0, True), (2, 1, False))
    token_rows: dict[tuple[int, int], tuple[Mapping[str, Any], bool]] = {}
    for index, (family_index, generation, rotated) in enumerate(token_specs):
        created_at = _at(31 + index)
        values = {
            "family_id": families[family_index]["id"],
            "token_hash": _stable_bytes(f"non-reusable-refresh-token-{index + 1}", 32),
            "created_at": created_at,
            "expires_at": created_at + timedelta(days=30),
            "revoked_at": _at(40 + index),
            "last_used_at": created_at + timedelta(hours=1),
            "rotated_at": created_at + timedelta(days=1) if rotated else None,
            "replaced_by_id": None,
            "generation": generation,
        }
        existing_id = connection.scalar(
            sa.select(tables["refresh_tokens"].c.id).where(
                tables["refresh_tokens"].c.token_hash == values["token_hash"]
            )
        )
        row = _ensure_row(
            connection,
            tables["refresh_tokens"],
            {"token_hash": values["token_hash"]},
            values,
            compare=tuple(name for name in values if name != "replaced_by_id"),
        )
        token_rows[(family_index, generation)] = (row, existing_id is None)

    generations_by_family: dict[int, list[int]] = {}
    for family_index, generation, _ in token_specs:
        generations_by_family.setdefault(family_index, []).append(generation)
    for family_index, generations in generations_by_family.items():
        ordered_generations = sorted(generations)
        for position, generation in enumerate(ordered_generations):
            row, inserted_now = token_rows[(family_index, generation)]
            expected_successor_id = (
                token_rows[(family_index, ordered_generations[position + 1])][0]["id"]
                if position + 1 < len(ordered_generations)
                else None
            )
            actual_successor_id = row["replaced_by_id"]
            if inserted_now and expected_successor_id is not None:
                connection.execute(
                    sa.update(tables["refresh_tokens"])
                    .where(tables["refresh_tokens"].c.id == row["id"])
                    .values(replaced_by_id=expected_successor_id)
                )
                actual_successor_id = expected_successor_id
            if actual_successor_id != expected_successor_id:
                raise SeedError(
                    "Seed collision in refresh_tokens replacement chain for "
                    f"family_index={family_index}, generation={generation}: "
                    f"expected replaced_by_id={expected_successor_id!r}, "
                    f"found {actual_successor_id!r}"
                )
    _maybe_fail("refresh_tokens")

    return {name: connection.scalar(sa.select(sa.func.count()).select_from(tables[name])) for name in EXPECTED_COUNTS}


def seed_database(engine: Engine) -> dict[str, int]:
    """Seed one migrated database in a single transaction."""
    _validate_environment()
    if engine.dialect.name != "mysql":
        raise SeedError("Demo seed supports only MySQL")
    with engine.begin() as connection:
        database_name = connection.scalar(sa.text("SELECT DATABASE()"))
        if not database_name:
            raise SeedError("Demo seed refused: connection has no selected database")
        counts = _seed(connection)
    return counts


def main() -> int:
    try:
        _validate_environment()
        database_url = os.getenv("SCMS_SEED_DATABASE_URL")
        if not database_url:
            raise SeedError("SCMS_SEED_DATABASE_URL is required")
        engine = sa.create_engine(database_url, pool_pre_ping=True)
        try:
            counts = seed_database(engine)
        finally:
            engine.dispose()
        print("SCMS deterministic demo seed completed")
        for table_name in sorted(counts):
            print(f"{table_name}: {counts[table_name]}")
        return 0
    except (SeedError, sa.exc.SQLAlchemyError) as exc:
        print(f"SCMS demo seed failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
