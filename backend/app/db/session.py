import os
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured before database access")
    return database_url


def create_db_engine(database_url: str | None = None, **engine_options: object) -> Engine:
    return create_engine(database_url or get_database_url(), **engine_options)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@dataclass(frozen=True, slots=True)
class DatabaseResources:
    engine: Engine
    session_factory: sessionmaker[Session]

    def dispose(self) -> None:
        self.engine.dispose()


def build_database_resources() -> DatabaseResources | None:
    """Build shared business-database resources when DATABASE_URL is configured."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None
    engine = create_db_engine(database_url, pool_pre_ping=True)
    return DatabaseResources(engine=engine, session_factory=create_session_factory(engine))


def get_db_session(request: Request) -> Iterator[Session]:
    """Yield one request-scoped session without owning business commits."""
    resources: DatabaseResources | None = request.app.state.database_resources
    if resources is None:
        raise RuntimeError("Database resources are not configured")
    session = resources.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
