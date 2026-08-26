"""Database plumbing.

Two things here are load-bearing rather than boilerplate.

`UTCDateTime` - SQLite has no native timestamp type, so a `DateTime(timezone=True)`
column silently round-trips as a *naive* datetime. That bit me twice already: the
audit chain broke on restart because a freshly-written row and the same row read
back hashed differently, and the compliance gates were comparing naive to aware.
I was patching it at nine separate call sites. Fixing it at the type boundary
instead means everything above this file can assume aware-UTC, always, and a
naive value going in is an error rather than a surprise later.

Engine construction is lazy and keyed by URL. Building it at import time meant
tests, the seeder and the app all shared one engine bound to whatever
DATABASE_URL happened to be set when the first module got imported.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from reversa.config import get_settings


class UTCDateTime(TypeDecorator):
    """Timestamps are always tz-aware UTC on the way in and on the way out."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime reached the database. Timestamps must be "
                "timezone-aware - use datetime.now(timezone.utc), not utcnow()."
            )
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        # sqlite hands back naive; postgres hands back aware. normalise both.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


_engines: dict[str, Engine] = {}
_sessionmakers: dict[str, sessionmaker] = {}


def get_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    if url not in _engines:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        eng = create_engine(url, connect_args=connect_args, future=True, pool_pre_ping=True)
        if url.startswith("sqlite"):
            event.listen(eng, "connect", _sqlite_pragmas)
        _engines[url] = eng
    return _engines[url]


def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver glue
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def get_sessionmaker(url: str | None = None) -> sessionmaker:
    url = url or get_settings().database_url
    if url not in _sessionmakers:
        _sessionmakers[url] = sessionmaker(
            bind=get_engine(url), autoflush=False, expire_on_commit=False
        )
    return _sessionmakers[url]


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    session = get_sessionmaker(url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def init_db(url: str | None = None) -> None:
    from reversa import models  # noqa: F401  registers mappers

    Base.metadata.create_all(get_engine(url))


def reset_db(url: str | None = None) -> None:
    """Drop and recreate. Seeder only - never call this against a real database."""
    from reversa import models  # noqa: F401

    eng = get_engine(url)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)


# kept for the handful of call sites that still import it directly
engine = get_engine()
SessionLocal = get_sessionmaker()
