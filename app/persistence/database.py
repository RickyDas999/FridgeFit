import os
import sqlite3

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

LOCAL_DATABASE_URL = "sqlite:///fridgefit.db"

# Predictable names for constraints the models leave unnamed, so a migration can later find and
# alter them (SQLite has no other way to refer to them). Check constraints are already named
# explicitly in the models, so they get no pattern.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}


class Base(DeclarativeBase):
    """Declarative base class that all FridgeFit ORM models inherit from."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """Turn on SQLite foreign-key enforcement for every new connection.

    SQLite leaves FOREIGN KEY constraints unenforced per-connection by
    default, so without this hook every ForeignKey in the schema would be
    documentation only, silently allowing orphaned rows. The listener fires for every engine,
    so connections to other databases (which enforce foreign keys themselves) are skipped.

    Args:
        dbapi_connection: The raw DBAPI connection SQLAlchemy just opened.
        _connection_record: SQLAlchemy's pool bookkeeping object for the
            connection; unused here but required by the event signature.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_database_url() -> str:
    """Return the database URL for this environment.

    Read when called, not at import, so the environment in effect at startup decides.

    Returns:
        The ``DATABASE_URL`` environment variable, or the local SQLite file when it is unset or
        empty. A PostgreSQL URL without a driver is pointed at psycopg 3.
    """
    url = os.environ.get("DATABASE_URL") or LOCAL_DATABASE_URL
    # Hosts such as Render hand out postgres:// or postgresql:// URLs. SQLAlchemy rejects the
    # first and maps the second to a driver that depends on its version, so name psycopg 3.
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url.removeprefix(scheme)
    return url


def get_engine(database_url: str):
    """Create a new SQLAlchemy engine bound to the given database URL.

    Args:
        database_url: SQLAlchemy connection string.

    Returns:
        A configured SQLAlchemy Engine instance.
    """
    return create_engine(database_url)


def get_session_factory(engine):
    """Build a session factory bound to the given engine.

    Args:
        engine: The SQLAlchemy Engine sessions produced by this factory
            should use.

    Returns:
        A sessionmaker callable; calling it produces a new Session.
    """
    return sessionmaker(bind=engine)
