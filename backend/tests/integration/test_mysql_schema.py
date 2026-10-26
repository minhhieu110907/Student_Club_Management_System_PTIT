from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import re
import threading
from typing import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError

from app.db.model_registry import Base


DATABASE_URL = os.getenv("SCMS_MYSQL_INTEGRATION_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="SCMS_MYSQL_INTEGRATION_URL is required for disposable MySQL verification",
)


def _normalized(value: object) -> str:
    text = str(value).lower().replace("`", "").replace("'", "")
    text = re.sub(r"\b_reutf8mb4\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text


def _normalized_mysql_type(value: object) -> str:
    value = str(value).lower()
    value = re.sub(r"^int(?=$|\s)", "integer", value)
    return re.sub(r"(?<=\d)\s*,\s*(?=\d)", ",", value)


def _expected_fk_action(action: str | None) -> str:
    if action is None:
        return "NO ACTION"
    normalized = action.upper()
    assert normalized in {"RESTRICT", "CASCADE", "SET NULL"}
    return normalized


def _sql_expression_ast(value: object, *, generated_case: bool = False) -> tuple[object, ...]:
    text = str(value).replace("`", "").replace("\\'", "'")
    text = re.sub(r"(?i)_utf8mb4(?=')", "", text)
    token_pattern = re.compile(
        r"\s*(?:('(?:''|[^'])*')|(<>|>=|<=|>|<)|([=(),])|([A-Za-z_][A-Za-z0-9_]*)|(\d+))"
    )
    tokens: list[tuple[str, str]] = []
    position = 0
    while position < len(text):
        match = token_pattern.match(text, position)
        assert match is not None, f"Unsupported SQL expression syntax at {text[position:]!r}"
        string, operator, punctuation, word, number = match.groups()
        if string is not None:
            tokens.append(("literal", string[1:-1].replace("''", "'")))
        elif operator is not None or punctuation is not None:
            tokens.append(("symbol", operator or punctuation))
        elif word is not None:
            tokens.append(("word", word.lower()))
        else:
            tokens.append(("number", str(number)))
        position = match.end()

    while tokens and tokens[0][1] == "(":
        depth = 0
        matching_close = None
        for index, token in enumerate(tokens):
            if token[1] == "(":
                depth += 1
            elif token[1] == ")":
                depth -= 1
                if depth == 0:
                    matching_close = index
                    break
        if matching_close != len(tokens) - 1:
            break
        tokens = tokens[1:-1]

    cursor = 0

    def accept(value: str) -> bool:
        nonlocal cursor
        if cursor < len(tokens) and tokens[cursor][1] == value:
            cursor += 1
            return True
        return False

    def require(value: str) -> None:
        assert accept(value), f"Expected {value!r} at token {cursor}: {tokens}"

    def parse_or() -> tuple[object, ...]:
        node = parse_and()
        while accept("or"):
            node = ("or", node, parse_and())
        return node

    def parse_and() -> tuple[object, ...]:
        node = parse_atom()
        while accept("and"):
            node = ("and", node, parse_atom())
        return node

    def parse_atom() -> tuple[object, ...]:
        nonlocal cursor
        if accept("not"):
            return ("not", parse_atom())
        if accept("("):
            node = parse_or()
            require(")")
            return node
        assert cursor < len(tokens) and tokens[cursor][0] == "word", tokens
        identifier = tokens[cursor][1]
        cursor += 1
        if accept("is"):
            negated = accept("not")
            require("null")
            return ("is_not_null" if negated else "is_null", ("identifier", identifier))
        if accept("in"):
            require("(")
            values: list[tuple[str, str]] = []
            while True:
                assert cursor < len(tokens) and tokens[cursor][0] in {"literal", "number"}, tokens
                values.append(tokens[cursor])
                cursor += 1
                if not accept(","):
                    break
            require(")")
            return ("in", ("identifier", identifier), tuple(values))
        assert cursor < len(tokens) and tokens[cursor][1] in {"=", "<>", ">", ">=", "<", "<="}, tokens
        operator = tokens[cursor][1]
        cursor += 1
        assert cursor < len(tokens) and tokens[cursor][0] in {"literal", "number", "word"}, tokens
        value = tokens[cursor]
        cursor += 1
        return (operator, ("identifier", identifier), value)

    if generated_case:
        require("case")
        require("when")
        condition = parse_or()
        require("then")
        require("1")
        require("else")
        require("null")
        require("end")
        result = ("case", condition, 1, None)
    else:
        result = parse_or()
    assert cursor == len(tokens), f"Unparsed SQL expression tokens: {tokens[cursor:]}"
    return result


def _generated_expression_ast(value: object) -> tuple[object, ...]:
    return _sql_expression_ast(value, generated_case=True)


def _check_expression_ast(value: object) -> tuple[object, ...]:
    return _sql_expression_ast(value)


@pytest.fixture(scope="module")
def engine() -> Iterator[sa.Engine]:
    assert DATABASE_URL is not None
    value = sa.create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        yield value
    finally:
        value.dispose()


def _rows(connection: sa.Connection, sql: str) -> list[dict[str, object]]:
    return list(connection.execute(sa.text(sql)).mappings())


def test_live_schema_matches_metadata_contract(engine: sa.Engine) -> None:
    dialect = mysql.dialect()
    with engine.connect() as connection:
        tables = {
            row["TABLE_NAME"]
            for row in _rows(
                connection,
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE()",
            )
        }
        assert tables == set(Base.metadata.tables) | {"alembic_version"}
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "20261026_01"

        table_rows = _rows(
            connection,
            "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME <> 'alembic_version'",
        )
        assert {
            (row["TABLE_NAME"], row["ENGINE"], row["TABLE_COLLATION"])
            for row in table_rows
        } == {
            (name, "InnoDB", "utf8mb4_0900_ai_ci") for name in Base.metadata.tables
        }

        column_rows = _rows(
            connection,
            "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, "
            "CHARACTER_SET_NAME, COLLATION_NAME, EXTRA, GENERATION_EXPRESSION "
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME <> 'alembic_version'",
        )
        actual_columns = {(row["TABLE_NAME"], row["COLUMN_NAME"]): row for row in column_rows}
        expected_column_keys = {
            (table.name, column.name)
            for table in Base.metadata.tables.values()
            for column in table.columns
        }
        assert set(actual_columns) == expected_column_keys
        generated_count = 0
        for table in Base.metadata.tables.values():
            for column in table.columns:
                row = actual_columns[(table.name, column.name)]
                expected_type = column.type.compile(dialect=dialect)
                collation_match = re.search(r"\s+collate\s+([A-Za-z0-9_]+)$", expected_type, re.IGNORECASE)
                if collation_match is not None:
                    expected_collation = collation_match.group(1)
                    expected_type = expected_type[: collation_match.start()]
                elif isinstance(column.type, sa.String):
                    expected_collation = table.dialect_options["mysql"]["collate"]
                else:
                    expected_collation = None
                assert _normalized_mysql_type(row["COLUMN_TYPE"]) == _normalized_mysql_type(expected_type)
                assert row["COLLATION_NAME"] == expected_collation
                assert (row["IS_NULLABLE"] == "YES") == column.nullable
                if column.server_default is None or column.computed is not None:
                    assert row["COLUMN_DEFAULT"] is None
                else:
                    assert str(row["COLUMN_DEFAULT"]) == str(column.server_default.arg)
                if column.computed is not None:
                    generated_count += 1
                    assert "STORED GENERATED" in str(row["EXTRA"]).upper()
                    assert _generated_expression_ast(row["GENERATION_EXPRESSION"]) == _generated_expression_ast(
                        column.computed.sqltext
                    )
        assert generated_count == 5

        fk_rows = _rows(
            connection,
            "SELECT k.CONSTRAINT_NAME, k.TABLE_NAME, k.COLUMN_NAME, k.ORDINAL_POSITION, "
            "k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME, r.UPDATE_RULE, r.DELETE_RULE "
            "FROM information_schema.KEY_COLUMN_USAGE k "
            "JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
            "ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
            "WHERE k.CONSTRAINT_SCHEMA = DATABASE() AND k.REFERENCED_TABLE_NAME IS NOT NULL "
            "ORDER BY k.TABLE_NAME, k.CONSTRAINT_NAME, k.ORDINAL_POSITION",
        )
        actual_fks: dict[tuple[str, str], dict[str, object]] = {}
        for row in fk_rows:
            key = (str(row["TABLE_NAME"]), str(row["CONSTRAINT_NAME"]))
            item = actual_fks.setdefault(
                key,
                {"columns": [], "targets": [], "onupdate": row["UPDATE_RULE"], "ondelete": row["DELETE_RULE"]},
            )
            item["columns"].append(row["COLUMN_NAME"])
            item["targets"].append(f"{row['REFERENCED_TABLE_NAME']}.{row['REFERENCED_COLUMN_NAME']}")
        expected_fks = {
            (table.name, fk.name): {
                "columns": list(fk.column_keys),
                "targets": [element.target_fullname for element in fk.elements],
                "onupdate": _expected_fk_action(fk.onupdate),
                "ondelete": _expected_fk_action(fk.ondelete),
            }
            for table in Base.metadata.tables.values()
            for fk in table.foreign_key_constraints
        }
        assert actual_fks == expected_fks
        assert len(actual_fks) == 29
        assert sum(len(value["columns"]) > 1 for value in actual_fks.values()) == 4

        constraint_rows = _rows(
            connection,
            "SELECT TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE "
            "FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() "
            "AND TABLE_NAME <> 'alembic_version'",
        )
        actual_unique_names = {
            (row["TABLE_NAME"], row["CONSTRAINT_NAME"])
            for row in constraint_rows
            if row["CONSTRAINT_TYPE"] == "UNIQUE"
        }
        expected_unique_names = {
            (table.name, constraint.name)
            for table in Base.metadata.tables.values()
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        }
        assert actual_unique_names == expected_unique_names

        check_rows = _rows(
            connection,
            "SELECT tc.TABLE_NAME, tc.CONSTRAINT_NAME, cc.CHECK_CLAUSE "
            "FROM information_schema.TABLE_CONSTRAINTS tc "
            "JOIN information_schema.CHECK_CONSTRAINTS cc "
            "ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
            "WHERE tc.CONSTRAINT_SCHEMA = DATABASE() AND tc.CONSTRAINT_TYPE = 'CHECK'",
        )
        actual_checks = {
            (row["TABLE_NAME"], row["CONSTRAINT_NAME"]): _check_expression_ast(row["CHECK_CLAUSE"])
            for row in check_rows
        }
        expected_checks = {
            (table.name, constraint.name): _check_expression_ast(constraint.sqltext)
            for table in Base.metadata.tables.values()
            for constraint in table.constraints
            if isinstance(constraint, sa.CheckConstraint)
        }
        assert actual_checks == expected_checks

        index_rows = _rows(
            connection,
            "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, COLUMN_NAME, SEQ_IN_INDEX "
            "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME <> 'alembic_version' ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
        )
        actual_indexes: dict[tuple[str, str], tuple[bool, list[str]]] = {}
        for row in index_rows:
            key = (str(row["TABLE_NAME"]), str(row["INDEX_NAME"]))
            unique, columns = actual_indexes.setdefault(key, (row["NON_UNIQUE"] == 0, []))
            columns.append(str(row["COLUMN_NAME"]))
        expected_indexes: dict[tuple[str, str], tuple[bool, list[str]]] = {}
        for table in Base.metadata.tables.values():
            expected_indexes[(table.name, "PRIMARY")] = (True, [column.name for column in table.primary_key.columns])
            for constraint in table.constraints:
                if isinstance(constraint, sa.UniqueConstraint):
                    expected_indexes[(table.name, str(constraint.name))] = (
                        True,
                        [column.name for column in constraint.columns],
                    )
            for index in table.indexes:
                expected_indexes[(table.name, str(index.name))] = (
                    index.unique,
                    [column.name for column in index.columns],
                )
        assert actual_indexes == expected_indexes


def _expect_rejected(
    connection: sa.Connection,
    statement: str,
    expected_codes: set[int],
    **parameters: object,
) -> None:
    with pytest.raises(sa.exc.DBAPIError) as captured:
        with connection.begin_nested():
            connection.execute(sa.text(statement), parameters)
    driver_args = getattr(captured.value.orig, "args", ())
    assert driver_args and driver_args[0] in expected_codes


def _seed_users_and_clubs(connection: sa.Connection, offset: int) -> dict[str, int]:
    ids = {
        "user1": offset + 1,
        "user2": offset + 2,
        "user3": offset + 3,
        "request1": offset + 101,
        "request2": offset + 102,
        "club1": offset + 201,
        "club2": offset + 202,
    }
    now = "2026-10-26 10:00:00.000000"
    for key in ("user1", "user2", "user3"):
        connection.execute(
            sa.text(
                "INSERT INTO users (id, email_normalized, full_name, password_hash, created_at, updated_at) "
                "VALUES (:id, :email, :name, 'hash', :now, :now)"
            ),
            {"id": ids[key], "email": f"{key}-{offset}@example.test", "name": key, "now": now},
        )
    for request_key, club_key, requester in (
        ("request1", "club1", "user1"),
        ("request2", "club2", "user2"),
    ):
        connection.execute(
            sa.text(
                "INSERT INTO club_creation_requests "
                "(id, requested_by, proposed_name, category, mission, initial_plan, status, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, 'ACADEMIC', 'mission', 'plan', 'APPROVED', :now, :now)"
            ),
            {"id": ids[request_key], "user_id": ids[requester], "name": club_key, "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO clubs (id, source_request_id, name, category, description, created_at, updated_at) "
                "VALUES (:id, :request_id, :name, 'ACADEMIC', 'description', :now, :now)"
            ),
            {"id": ids[club_key], "request_id": ids[request_key], "name": club_key, "now": now},
        )
    return ids


def test_unique_and_check_constraint_behaviors(engine: sa.Engine) -> None:
    with engine.connect() as connection, connection.begin():
        ids = _seed_users_and_clubs(connection, 10000)
        now = "2026-10-26 10:00:00.000000"

        _expect_rejected(
            connection,
            "INSERT INTO users (id, email_normalized, full_name, password_hash, created_at, updated_at) "
            "VALUES (:id, :email, 'duplicate', 'hash', :now, :now)",
            id=10999,
            email="user1-10000@example.test",
            now=now,
            expected_codes={1062},
        )

        connection.execute(
            sa.text(
                "INSERT INTO club_memberships (id, club_id, user_id, role, status, joined_at) "
                "VALUES (10501, :club, :user, 'MEMBER', 'ACTIVE', :now)"
            ),
            {"club": ids["club1"], "user": ids["user2"], "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO club_memberships (id, club_id, user_id, role, status, joined_at, ended_at) "
                "VALUES (10502, :club, :user, 'MEMBER', 'LEFT', :now, :now)"
            ),
            {"club": ids["club1"], "user": ids["user2"], "now": now},
        )
        _expect_rejected(
            connection,
            "INSERT INTO club_memberships (id, club_id, user_id, role, status, joined_at) "
            "VALUES (10503, :club, :user, 'MEMBER', 'ACTIVE', :now)",
            club=ids["club1"],
            user=ids["user2"],
            now=now,
            expected_codes={1062},
        )

        connection.execute(
            sa.text(
                "INSERT INTO events (id, club_id, created_by, title, description, location, visibility, "
                "starts_at, ends_at, registration_opens_at, registration_closes_at, capacity, created_at, updated_at) "
                "VALUES (10601, :club, :creator, 'event', 'description', 'room', 'PUBLIC_STUDENTS', "
                "'2026-11-02', '2026-11-03', '2026-10-27', '2026-11-01', 1, :now, :now)"
            ),
            {"club": ids["club1"], "creator": ids["user1"], "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO event_registrations (id, event_id, user_id, status, registered_at) "
                "VALUES (10701, 10601, :user, 'REGISTERED', :now)"
            ),
            {"user": ids["user2"], "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO event_registrations "
                "(id, event_id, user_id, status, registered_at, cancelled_at) "
                "VALUES (10702, 10601, :user, 'CANCELLED', :now, :now)"
            ),
            {"user": ids["user2"], "now": now},
        )
        _expect_rejected(
            connection,
            "INSERT INTO event_registrations (id, event_id, user_id, status, registered_at) "
            "VALUES (10703, 10601, :user, 'REGISTERED', :now)",
            user=ids["user2"],
            now=now,
            expected_codes={1062},
        )
        _expect_rejected(
            connection,
            "UPDATE events SET registration_count = 2 WHERE id = 10601",
            expected_codes={3819},
        )

        family = bytes.fromhex("10" * 16)
        connection.execute(
            sa.text(
                "INSERT INTO refresh_token_families "
                "(id, user_id, created_at, absolute_expires_at, purge_after) "
                "VALUES (:family, :user, :now, '2026-12-01', '2027-01-01')"
            ),
            {"family": family, "user": ids["user1"], "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO refresh_tokens "
                "(id, family_id, token_hash, created_at, expires_at, generation) "
                "VALUES (10801, :family, :hash, :now, '2026-11-30', 0)"
            ),
            {"family": family, "hash": bytes.fromhex("11" * 32), "now": now},
        )
        _expect_rejected(
            connection,
            "INSERT INTO refresh_tokens "
            "(id, family_id, token_hash, created_at, expires_at, generation) "
            "VALUES (10802, :family, :hash, :now, '2026-11-30', 1)",
            family=family,
            hash=bytes.fromhex("12" * 32),
            now=now,
            expected_codes={1062},
        )

        _expect_rejected(
            connection,
            "INSERT INTO outbox_events "
            "(id, event_type, aggregate_type, aggregate_id, payload, status, next_attempt_at, created_at, updated_at) "
            "VALUES (10901, 'test', 'event', 10601, JSON_OBJECT(), 'PROCESSING', :now, :now, :now)",
            now=now,
            expected_codes={3819},
        )


def test_all_composite_foreign_keys_reject_mismatched_identity(engine: sa.Engine) -> None:
    with engine.connect() as connection, connection.begin():
        ids = _seed_users_and_clubs(connection, 20000)
        now = "2026-10-26 10:00:00.000000"
        connection.execute(
            sa.text(
                "INSERT INTO membership_applications "
                "(id, club_id, user_id, status, created_at) VALUES (20401, :club, :user, 'APPROVED', :now)"
            ),
            {"club": ids["club1"], "user": ids["user3"], "now": now},
        )
        _expect_rejected(
            connection,
            "INSERT INTO club_memberships "
            "(id, club_id, user_id, source_application_id, role, status, joined_at) "
            "VALUES (20501, :wrong_club, :user, 20401, 'MEMBER', 'ACTIVE', :now)",
            wrong_club=ids["club2"],
            user=ids["user3"],
            now=now,
            expected_codes={1452},
        )
        connection.execute(
            sa.text(
                "INSERT INTO club_memberships (id, club_id, user_id, role, status, joined_at) "
                "VALUES (20502, :club, :user, 'MEMBER', 'ACTIVE', :now)"
            ),
            {"club": ids["club1"], "user": ids["user3"], "now": now},
        )
        for event_id, club_key in ((20601, "club1"), (20602, "club2")):
            connection.execute(
                sa.text(
                    "INSERT INTO events (id, club_id, created_by, title, description, location, visibility, "
                    "starts_at, ends_at, registration_opens_at, registration_closes_at, capacity, created_at, updated_at) "
                    "VALUES (:id, :club, :creator, 'event', 'description', 'room', 'PUBLIC_STUDENTS', "
                    "'2026-11-02', '2026-11-03', '2026-10-27', '2026-11-01', 5, :now, :now)"
                ),
                {"id": event_id, "club": ids[club_key], "creator": ids["user1"], "now": now},
            )
        _expect_rejected(
            connection,
            "INSERT INTO event_tasks "
            "(id, event_id, club_id, created_by, title, created_at, updated_at) "
            "VALUES (20701, 20601, :wrong_club, :creator, 'task', :now, :now)",
            wrong_club=ids["club2"],
            creator=ids["user1"],
            now=now,
            expected_codes={1452},
        )
        _expect_rejected(
            connection,
            "INSERT INTO event_tasks "
            "(id, event_id, club_id, assignee_membership_id, created_by, title, created_at, updated_at) "
            "VALUES (20702, 20602, :club, 20502, :creator, 'task', :now, :now)",
            club=ids["club2"],
            creator=ids["user1"],
            now=now,
            expected_codes={1452},
        )
        for conversation_id, owner in ((20801, "user1"), (20802, "user2")):
            connection.execute(
                sa.text(
                    "INSERT INTO ai_conversations "
                    "(id, owner_user_id, created_at, updated_at, purge_after) "
                    "VALUES (:id, :owner, :now, :now, '2027-01-01')"
                ),
                {"id": conversation_id, "owner": ids[owner], "now": now},
            )
        connection.execute(
            sa.text(
                "INSERT INTO ai_turns "
                "(id, conversation_id, client_request_key, payload_hash, turn_no, created_at) "
                "VALUES (20901, 20801, :request_key, :payload_hash, 1, :now)"
            ),
            {"request_key": bytes.fromhex("21" * 16), "payload_hash": bytes.fromhex("22" * 32), "now": now},
        )
        _expect_rejected(
            connection,
            "INSERT INTO ai_messages "
            "(id, conversation_id, turn_id, role, status, created_at, updated_at) "
            "VALUES (20902, 20802, 20901, 'USER', 'SUCCEEDED', :now, :now)",
            now=now,
            expected_codes={1452},
        )


def test_concurrent_inflight_ai_turns_are_serialized_by_unique_guard(engine: sa.Engine) -> None:
    now = "2026-10-26 10:00:00.000000"
    with engine.begin() as connection:
        ids = _seed_users_and_clubs(connection, 30000)
        connection.execute(
            sa.text(
                "INSERT INTO ai_conversations "
                "(id, owner_user_id, created_at, updated_at, purge_after) "
                "VALUES (30801, :owner, :now, :now, '2027-01-01')"
            ),
            {"owner": ids["user1"], "now": now},
        )

    barrier = threading.Barrier(2)

    def insert_turn(turn_id: int, marker: int) -> str:
        try:
            with engine.begin() as connection:
                barrier.wait(timeout=10)
                connection.execute(
                    sa.text(
                        "INSERT INTO ai_turns "
                        "(id, conversation_id, client_request_key, payload_hash, turn_no, created_at) "
                        "VALUES (:id, 30801, :request_key, :payload_hash, :turn_no, :now)"
                    ),
                    {
                        "id": turn_id,
                        "request_key": bytes([marker]) * 16,
                        "payload_hash": bytes([marker]) * 32,
                        "turn_no": marker,
                        "now": now,
                    },
                )
            return "committed"
        except IntegrityError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda args: insert_turn(*args), ((30901, 31), (30902, 32))))
    assert sorted(outcomes) == ["committed", "rejected"]


def test_all_generated_guards_compute_active_and_inactive_states(engine: sa.Engine) -> None:
    now = "2026-10-26 10:00:00.000000"
    with engine.connect() as connection, connection.begin():
        ids = _seed_users_and_clubs(connection, 40000)
        connection.execute(
            sa.text(
                "INSERT INTO membership_applications (id, club_id, user_id, status, created_at) VALUES "
                "(40401, :club, :user2, 'PENDING', :now), "
                "(40402, :club, :user3, 'APPROVED', :now)"
            ),
            {"club": ids["club1"], "user2": ids["user2"], "user3": ids["user3"], "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO club_memberships (id, club_id, user_id, status, joined_at, ended_at) VALUES "
                "(40501, :club, :user2, 'ACTIVE', :now, NULL), "
                "(40502, :club, :user3, 'LEFT', :now, :now)"
            ),
            {"club": ids["club1"], "user2": ids["user2"], "user3": ids["user3"], "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO events (id, club_id, created_by, title, description, location, visibility, "
                "starts_at, ends_at, registration_opens_at, registration_closes_at, capacity, created_at, updated_at) "
                "VALUES (40601, :club, :creator, 'event', 'description', 'room', 'PUBLIC_STUDENTS', "
                "'2026-11-02', '2026-11-03', '2026-10-27', '2026-11-01', 5, :now, :now)"
            ),
            {"club": ids["club1"], "creator": ids["user1"], "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO event_registrations "
                "(id, event_id, user_id, status, registered_at, cancelled_at) VALUES "
                "(40701, 40601, :user2, 'REGISTERED', :now, NULL), "
                "(40702, 40601, :user3, 'CANCELLED', :now, :now)"
            ),
            {"user2": ids["user2"], "user3": ids["user3"], "now": now},
        )
        family = bytes.fromhex("40" * 16)
        connection.execute(
            sa.text(
                "INSERT INTO refresh_token_families "
                "(id, user_id, created_at, absolute_expires_at, purge_after) "
                "VALUES (:family, :user, :now, '2026-12-01', '2027-01-01')"
            ),
            {"family": family, "user": ids["user1"], "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO refresh_tokens "
                "(id, family_id, token_hash, created_at, expires_at, rotated_at, generation) VALUES "
                "(40801, :family, :hash1, :now, '2026-11-30', NULL, 0), "
                "(40802, :family, :hash2, :now, '2026-11-30', :now, 1)"
            ),
            {
                "family": family,
                "hash1": bytes.fromhex("41" * 32),
                "hash2": bytes.fromhex("42" * 32),
                "now": now,
            },
        )
        for conversation_id, owner in ((40901, "user1"), (40902, "user2")):
            connection.execute(
                sa.text(
                    "INSERT INTO ai_conversations "
                    "(id, owner_user_id, created_at, updated_at, purge_after) "
                    "VALUES (:id, :owner, :now, :now, '2027-01-01')"
                ),
                {"id": conversation_id, "owner": ids[owner], "now": now},
            )
        connection.execute(
            sa.text(
                "INSERT INTO ai_turns "
                "(id, conversation_id, client_request_key, payload_hash, turn_no, status, created_at, finished_at) VALUES "
                "(40911, 40901, :key1, :hash1, 1, 'PENDING', :now, NULL), "
                "(40912, 40902, :key2, :hash2, 1, 'SUCCEEDED', :now, :now)"
            ),
            {
                "key1": bytes.fromhex("43" * 16),
                "hash1": bytes.fromhex("44" * 32),
                "key2": bytes.fromhex("45" * 16),
                "hash2": bytes.fromhex("46" * 32),
                "now": now,
            },
        )

        assert connection.execute(
            sa.text("SELECT id, pending_guard FROM membership_applications WHERE id IN (40401, 40402) ORDER BY id")
        ).all() == [(40401, 1), (40402, None)]
        assert connection.execute(
            sa.text("SELECT id, active_guard FROM club_memberships WHERE id IN (40501, 40502) ORDER BY id")
        ).all() == [(40501, 1), (40502, None)]
        assert connection.execute(
            sa.text("SELECT id, active_guard FROM event_registrations WHERE id IN (40701, 40702) ORDER BY id")
        ).all() == [(40701, 1), (40702, None)]
        assert connection.execute(
            sa.text("SELECT id, current_guard FROM refresh_tokens WHERE id IN (40801, 40802) ORDER BY id")
        ).all() == [(40801, 1), (40802, None)]
        assert connection.execute(
            sa.text("SELECT id, inflight_guard FROM ai_turns WHERE id IN (40911, 40912) ORDER BY id")
        ).all() == [(40911, 1), (40912, None)]

