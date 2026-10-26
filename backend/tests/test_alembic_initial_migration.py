from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.db.model_registry import Base


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION_PATH = BACKEND_ROOT / "alembic" / "versions" / "20261026_01_initial_schema.py"


def _load_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scms_initial_revision", REVISION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationRecorder:
    def __init__(self) -> None:
        self.metadata = sa.MetaData()
        self.dropped_tables: list[str] = []

    def create_table(self, name: str, *elements: object, **options: object) -> sa.Table:
        return sa.Table(name, self.metadata, *elements, **options)

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        unique: bool = False,
        **_: object,
    ) -> None:
        table = self.metadata.tables[table_name]
        sa.Index(name, *(table.c[column] for column in columns), unique=unique)

    def drop_table(self, table_name: str) -> None:
        self.dropped_tables.append(table_name)


def _normalized(value: object) -> str:
    return " ".join(str(value).split())


def _metadata_signature(metadata: sa.MetaData) -> dict[str, object]:
    dialect = mysql.dialect()
    return {
        "tables": set(metadata.tables),
        "columns": {
            (table.name, column.name): (
                str(column.type.compile(dialect=dialect)),
                column.nullable,
                column.primary_key,
                column.autoincrement,
                None if column.server_default is None or column.computed is not None else str(column.server_default.arg),
                None if column.computed is None else (_normalized(column.computed.sqltext), column.computed.persisted),
            )
            for table in metadata.tables.values()
            for column in table.columns
        },
        "primary_keys": {
            (table.name, table.primary_key.name, tuple(column.name for column in table.primary_key.columns))
            for table in metadata.tables.values()
        },
        "foreign_keys": {
            (
                table.name,
                fk.name,
                tuple(fk.column_keys),
                tuple(item.target_fullname for item in fk.elements),
                fk.ondelete,
                fk.onupdate,
            )
            for table in metadata.tables.values()
            for fk in table.foreign_key_constraints
        },
        "unique_constraints": {
            (table.name, constraint.name, tuple(column.name for column in constraint.columns))
            for table in metadata.tables.values()
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        },
        "checks": {
            (constraint.name, _normalized(constraint.sqltext))
            for table in metadata.tables.values()
            for constraint in table.constraints
            if isinstance(constraint, sa.CheckConstraint)
        },
        "indexes": {
            (table.name, index.name, tuple(column.name for column in index.columns), index.unique)
            for table in metadata.tables.values()
            for index in table.indexes
        },
        "table_options": {
            table.name: (
                table.dialect_options["mysql"]["engine"],
                table.dialect_options["mysql"]["charset"],
                table.dialect_options["mysql"]["collate"],
            )
            for table in metadata.tables.values()
        },
    }


def test_initial_revision_operations_match_complete_model_registry() -> None:
    revision = _load_revision()
    recorder = MigrationRecorder()
    revision.op = recorder

    revision.upgrade()

    assert revision.revision == "20261026_01"
    assert revision.down_revision is None
    assert tuple(recorder.metadata.tables) == revision.UPGRADE_TABLE_ORDER
    assert _metadata_signature(recorder.metadata) == _metadata_signature(Base.metadata)


def test_downgrade_uses_dependency_safe_reverse_order() -> None:
    revision = _load_revision()
    recorder = MigrationRecorder()
    revision.op = recorder

    revision.downgrade()

    assert revision.DOWNGRADE_TABLE_ORDER == tuple(reversed(revision.UPGRADE_TABLE_ORDER))
    assert recorder.dropped_tables == list(revision.DOWNGRADE_TABLE_ORDER)
    assert set(recorder.dropped_tables) == set(Base.metadata.tables)


def test_offline_mysql_sql_generation_requires_no_database_connection() -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = "mysql+pymysql://"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head", "--sql"],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    sql = result.stdout
    created_tables = set(re.findall(r"^CREATE TABLE `?([A-Za-z0-9_]+)`? \(", sql, re.MULTILINE))
    assert "alembic_version" in created_tables
    assert created_tables - {"alembic_version"} == set(Base.metadata.tables)
    assert sql.count("FOREIGN KEY") == 29
    assert sql.count("GENERATED ALWAYS AS") == 5
    assert "FOREIGN KEY(source_application_id, club_id, user_id)" in sql
    assert "REFERENCES membership_applications (id, club_id, user_id) ON DELETE RESTRICT ON UPDATE RESTRICT" in sql
    assert "FOREIGN KEY(turn_id, conversation_id)" in sql
    assert "REFERENCES ai_turns (id, conversation_id) ON DELETE CASCADE" in sql
    assert "COLLATE utf8mb4_0900_as_cs" in sql
    for table_name in Base.metadata.tables:
        statement_match = re.search(
            rf"^CREATE TABLE `?{re.escape(table_name)}`? \(.*?;\s*$",
            sql,
            re.MULTILINE | re.DOTALL,
        )
        assert statement_match is not None, table_name
        statement = statement_match.group(0)
        assert re.search(r"\bENGINE\s*=\s*InnoDB\b", statement, re.IGNORECASE)
        assert re.search(r"\b(?:DEFAULT\s+)?CHARSET\s*=\s*utf8mb4\b", statement, re.IGNORECASE)
        assert re.search(r"\bCOLLATE(?:\s*=\s*|\s+)utf8mb4_0900_ai_ci\b", statement, re.IGNORECASE)
