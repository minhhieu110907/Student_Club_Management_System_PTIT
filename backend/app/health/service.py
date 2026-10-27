from __future__ import annotations

import os

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import create_db_engine

EXPECTED_ALEMBIC_REVISION = "20261026_01"
DATABASE_TIMEOUT_SECONDS = 2


class ReadinessService:
    """Check database readiness using one reusable SQLAlchemy engine."""

    def __init__(self, engine: Engine | None) -> None:
        self.engine = engine

    def is_ready(self) -> bool:
        if self.engine is None:
            return False

        try:
            with self.engine.connect() as connection:
                if connection.scalar(text("SELECT 1")) != 1:
                    return False
                revision = (
                    connection.execute(text("SELECT version_num FROM alembic_version"))
                    .scalars()
                    .one()
                )
        except SQLAlchemyError:
            return False

        return revision == EXPECTED_ALEMBIC_REVISION

    def dispose(self) -> None:
        if self.engine is not None:
            self.engine.dispose()


def build_readiness_service() -> ReadinessService:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return ReadinessService(None)

    try:
        engine = create_db_engine(
            database_url,
            pool_pre_ping=True,
            pool_timeout=DATABASE_TIMEOUT_SECONDS,
            connect_args={
                "connect_timeout": DATABASE_TIMEOUT_SECONDS,
                "read_timeout": DATABASE_TIMEOUT_SECONDS,
                "write_timeout": DATABASE_TIMEOUT_SECONDS,
            },
        )
    except (SQLAlchemyError, ValueError):
        return ReadinessService(None)

    return ReadinessService(engine)
