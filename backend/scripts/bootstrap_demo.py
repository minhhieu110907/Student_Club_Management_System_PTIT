"""One-shot database migration and optional demo seed bootstrap for Docker Compose."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from app.core.security.password import hash_password
from scripts.seed import ALLOWED_ENVIRONMENTS, SeedError, _seed, _validate_environment

DEFAULT_WAIT_SECONDS = 60


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set before running bootstrap")
    return database_url


def _wait_for_mysql(engine: sa.Engine, timeout_seconds: int = DEFAULT_WAIT_SECONDS) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with engine.connect() as connection:
                if connection.scalar(sa.text("SELECT 1")) == 1:
                    return
        except SQLAlchemyError as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"MySQL did not become ready within {timeout_seconds}s: {last_error}")


def _run_migrations() -> None:
    print("Running Alembic migrations (upgrade head)...", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Alembic migration failed with exit code {result.returncode}")


def _maybe_seed_demo(engine: sa.Engine) -> None:
    if os.getenv("SCMS_ALLOW_DEMO_SEED", "").strip() != "1":
        print("SCMS_ALLOW_DEMO_SEED is not 1; skipping demo seed.", flush=True)
        return

    environment = os.getenv("SCMS_ENV", "").strip().lower()
    if environment not in ALLOWED_ENVIRONMENTS:
        raise SeedError("Demo seed refused: SCMS_ENV must be one of development, demo, or test")

    _validate_environment()
    if engine.dialect.name != "mysql":
        raise SeedError("Demo seed supports only MySQL")

    with engine.connect() as connection:
        has_users = connection.scalar(sa.text("SELECT 1 FROM users LIMIT 1"))
        has_clubs = connection.scalar(sa.text("SELECT 1 FROM clubs LIMIT 1"))
    if has_users is not None or has_clubs is not None:
        print(
            "Database already contains existing data; skipping demo seed without modifying rows.",
            flush=True,
        )
        return

    if not os.getenv("SCMS_DEMO_PASSWORD_HASH"):
        demo_password = os.getenv("SCMS_DEMO_PASSWORD", "").strip()
        if not demo_password:
            raise SeedError(
                "Set SCMS_DEMO_PASSWORD_HASH or SCMS_DEMO_PASSWORD when SCMS_ALLOW_DEMO_SEED=1"
            )
        os.environ["SCMS_DEMO_PASSWORD_HASH"] = hash_password(demo_password)

    with engine.begin() as connection:
        database_name = connection.scalar(sa.text("SELECT DATABASE()"))
        if not database_name:
            raise SeedError("Demo seed refused: connection has no selected database")
        counts = _seed(connection)
        _ensure_login_demo_accounts(connection)

    print("SCMS demo seed completed:", flush=True)
    for table_name in sorted(counts):
        print(f"  {table_name}: {counts[table_name]}", flush=True)


def _ensure_login_demo_accounts(connection: sa.Connection) -> None:
    """Ensure demo accounts use RFC-valid example.com emails accepted by LoginRequest."""
    password_hash = os.environ["SCMS_DEMO_PASSWORD_HASH"]
    utc_now = datetime.now(UTC).replace(tzinfo=None)
    demo_accounts = (
        ("admin@scms.example.com", "Demo System Admin", "ADMIN"),
        ("alex@scms.example.com", "Alex Demo Manager", "STUDENT"),
        ("student@scms.example.com", "Demo Student", "STUDENT"),
    )
    user_ids: dict[str, int] = {}
    for email, full_name, role in demo_accounts:
        existing_id = connection.scalar(
            sa.text("SELECT id FROM users WHERE email_normalized = :email LIMIT 1"),
            {"email": email},
        )
        if existing_id is None:
            result = connection.execute(
                sa.text(
                    "INSERT INTO users (email_normalized, full_name, password_hash, "
                    "global_role, status, created_at, updated_at) "
                    "VALUES (:email, :full_name, :password_hash, :role, 'ACTIVE', :now, :now)"
                ),
                {
                    "email": email,
                    "full_name": full_name,
                    "password_hash": password_hash,
                    "role": role,
                    "now": utc_now,
                },
            )
            existing_id = int(result.lastrowid)
        user_ids[email] = int(existing_id)

    robotics_id = connection.scalar(
        sa.text("SELECT id FROM clubs WHERE name = 'Robotics Collective' LIMIT 1")
    )
    if robotics_id is not None:
        alex_id = user_ids["alex@scms.example.com"]
        has_membership = connection.scalar(
            sa.text(
                "SELECT id FROM club_memberships "
                "WHERE club_id = :club_id AND user_id = :user_id AND status = 'ACTIVE' LIMIT 1"
            ),
            {"club_id": robotics_id, "user_id": alex_id},
        )
        if has_membership is None:
            connection.execute(
                sa.text(
                    "INSERT INTO club_memberships "
                    "(club_id, user_id, source_application_id, role, status, joined_at, ended_at) "
                    "VALUES (:club_id, :user_id, NULL, 'MANAGER', 'ACTIVE', :joined_at, NULL)"
                ),
                {"club_id": robotics_id, "user_id": alex_id, "joined_at": utc_now},
            )


def main() -> int:
    try:
        database_url = _database_url()
        engine = sa.create_engine(database_url, pool_pre_ping=True)
        try:
            _wait_for_mysql(engine)
            _run_migrations()
            _maybe_seed_demo(engine)
        finally:
            engine.dispose()
        print("SCMS bootstrap completed successfully.", flush=True)
        return 0
    except (RuntimeError, SeedError, SQLAlchemyError) as exc:
        print(f"SCMS bootstrap failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
