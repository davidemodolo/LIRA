"""Database session management for L.I.R.A.

Provides SQLAlchemy session handling with proper lifecycle management.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lira.db.models import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_database_url() -> str:
    """Get database URL from environment or default.

    Returns:
        Database URL string
    """
    import os

    return os.getenv("DATABASE_URL", "sqlite:///./data/lira.db")


def init_database(url: str | None = None, echo: bool = False) -> Engine:
    """Initialize database engine and session factory.

    Args:
        url: Database URL (defaults to env var or sqlite)
        echo: Whether to log SQL statements

    Returns:
        SQLAlchemy Engine instance
    """
    global _engine, _SessionLocal

    if _engine is not None:
        return _engine

    db_url = url or get_database_url()

    logger.info("Initializing database: %s", db_url)

    if db_url.startswith("sqlite"):
        _engine = create_sqlite_engine(db_url, echo)
    else:
        _engine = create_engine(db_url, echo=echo, pool_pre_ping=True)

    _SessionLocal = sessionmaker(
        bind=_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    create_tables()

    return _engine


def create_sqlite_engine(url: str, echo: bool) -> Engine:
    """Create SQLite engine with optimizations.

    Args:
        url: SQLite URL
        echo: Whether to log SQL

    Returns:
        Configured SQLAlchemy Engine
    """
    connect_args: dict[str, Any] = {"check_same_thread": False}

    if ":memory:" not in url:
        db_path = url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        url,
        echo=echo,
        connect_args=connect_args,
        poolclass=StaticPool if ":memory:" in url else None,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:
        """Enable SQLite optimizations for better performance."""
        if "sqlite" in type(dbapi_conn).__module__:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def create_tables() -> None:
    """Create all database tables.

    Should only be called during initial setup.
    For migrations, use Alembic.
    """
    if _engine is None:
        msg = "Database not initialized. Call init_database() first."
        raise RuntimeError(msg)

    Base.metadata.create_all(bind=_engine)
    logger.info("Database tables created")


def drop_tables() -> None:
    """Drop all database tables.

    WARNING: This will delete all data!
    """
    if _engine is None:
        msg = "Database not initialized. Call init_database() first."
        raise RuntimeError(msg)

    Base.metadata.drop_all(bind=_engine)
    logger.warning("All database tables dropped")


def get_session_factory() -> sessionmaker[Session]:
    """Get the session factory.

    Returns:
        SQLAlchemy sessionmaker

    Raises:
        RuntimeError: If database not initialized
    """
    if _SessionLocal is None:
        msg = "Database not initialized. Call init_database() first."
        raise RuntimeError(msg)

    return _SessionLocal


@contextmanager
def DatabaseSession() -> Generator[Session, None, None]:
    """Context manager for database sessions.

    Yields:
        SQLAlchemy Session

    Example:
        with DatabaseSession() as session:
            accounts = session.query(Account).all()
    """
    if _SessionLocal is None:
        msg = "Database not initialized. Call init_database() first."
        raise RuntimeError(msg)

    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@asynccontextmanager
async def AsyncDatabaseSession() -> AsyncGenerator[Session, None]:
    """Async context manager for database sessions.

    Yields:
        SQLAlchemy Session

    Note:
        This is a sync session in an async context.
        For true async, use async_sessionmaker with AsyncSession.
    """
    with DatabaseSession() as session:
        yield session


def get_session() -> Generator[Session, None, None]:
    """Dependency for FastAPI to get database session.

    Yields:
        SQLAlchemy Session

    Example:
        @app.get("/accounts")
        def get_accounts(db: Session = Depends(get_session)):
            return db.query(Account).all()
    """
    if _SessionLocal is None:
        msg = "Database not initialized. Call init_database() first."
        raise RuntimeError(msg)

    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def close_database() -> None:
    """Close database connections and cleanup."""
    global _engine, _SessionLocal

    if _engine:
        _engine.dispose()
        _engine = None
        _SessionLocal = None
        logger.info("Database connections closed")


from collections.abc import AsyncGenerator
