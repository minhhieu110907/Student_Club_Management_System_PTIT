"""Prepare isolated MySQL schemas for GitHub Actions integration tests."""

from __future__ import annotations

import argparse
import os
import time

import pymysql

DATABASE_NAMES = (
    "scms_schema_verify",
    "scms_seed_verify",
    "scms_seed_rollback",
    "scms_seed_conflict",
    "scms_readiness_ready",
    "scms_readiness_empty",
    "scms_readiness_wrong",
)


def _connection(database: str | None = None) -> pymysql.Connection:
    _assert_ci_target()
    return pymysql.connect(
        host=os.environ["CI_MYSQL_HOST"],
        port=int(os.environ.get("CI_MYSQL_PORT", "3306")),
        user=os.environ["CI_MYSQL_USER"],
        password=os.environ["CI_MYSQL_PASSWORD"],
        database=database,
        connect_timeout=2,
        read_timeout=2,
        write_timeout=2,
        autocommit=True,
    )


def _assert_ci_target() -> None:
    if os.getenv("CI", "").lower() != "true":
        raise RuntimeError("CI database preparation is refused outside CI=true")
    if os.getenv("CI_MYSQL_HOST") not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("CI database preparation requires a loopback MySQL host")


def prepare() -> None:
    deadline = time.monotonic() + 120
    while True:
        try:
            with _connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT @@version, @@hostname")
                cursor.fetchone()
            break
        except pymysql.MySQLError:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "CI MySQL did not complete initialization within 120 seconds"
                ) from None
            time.sleep(2)

    with _connection() as connection, connection.cursor() as cursor:
        placeholders = ", ".join(["%s"] * len(DATABASE_NAMES))
        cursor.execute(
            f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
            f"WHERE SCHEMA_NAME IN ({placeholders})",
            DATABASE_NAMES,
        )
        collisions = sorted(row[0] for row in cursor.fetchall())
        if collisions:
            raise RuntimeError("Refusing to reuse CI schemas: " + ", ".join(collisions))
        for database in DATABASE_NAMES:
            cursor.execute(
                f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )


def set_wrong_revision() -> None:
    with _connection("scms_readiness_wrong") as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE alembic_version SET version_num = %s", ("incorrect_revision",))
        if cursor.rowcount != 1:
            raise RuntimeError("Expected exactly one Alembic revision row to modify")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "set-wrong-revision"))
    arguments = parser.parse_args()
    if arguments.command == "prepare":
        prepare()
    else:
        set_wrong_revision()


if __name__ == "__main__":
    main()
