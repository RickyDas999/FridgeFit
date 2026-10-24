import os
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.api.main import create_app
from app.persistence.database import Base

# Set (e.g. postgresql+psycopg://user:pass@localhost/fridgefit_test) to run the database tests
# against that PostgreSQL database instead of SQLite. Its contents are wiped before every test.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def empty_database_url(tmp_path):
    """Provide the URL of an empty database for one test.

    A new SQLite file by default; with ``TEST_DATABASE_URL`` set, that PostgreSQL database with
    its schema dropped and recreated, which also removes enum types and Alembic's version table.

    Args:
        tmp_path: pytest's per-test temporary directory.

    Returns:
        The database URL.
    """
    if TEST_DATABASE_URL is None:
        return f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    return TEST_DATABASE_URL


@pytest.fixture
def session(empty_database_url):
    """Provide a session bound to a fresh database with all tables created.

    Each test gets its own empty database, so tests never share state.

    Args:
        empty_database_url: An empty database for this test.

    Yields:
        An open SQLAlchemy Session, closed after the test finishes.
    """
    engine = create_engine(empty_database_url)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    # Close pooled connections, so PostgreSQL can drop the schema for the next test.
    engine.dispose()


@pytest.fixture
def app(empty_database_url):
    """Build an API app bound to a fresh database, with every table.

    Tables come from the models directly (fast); ``tests/test_migrations.py`` proves the
    migrations build the same schema.

    Args:
        empty_database_url: An empty database for this test.

    Yields:
        The FastAPI application.
    """
    app = create_app(empty_database_url)
    Base.metadata.create_all(app.state.engine)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app):
    """Provide an HTTP client for the app, with startup already run.

    Args:
        app: The FastAPI application under test.

    Yields:
        A TestClient that sends requests to the app in-process.
    """
    with TestClient(app) as client:
        yield client


@pytest.fixture
def count_queries(app):
    """Count the SQL statements the app's engine runs inside a ``with`` block.

    Used to prove a list endpoint runs a fixed number of queries however much data exists, so
    an N+1 pattern (one extra query per row) shows up as a failing test.

    Args:
        app: The FastAPI application under test.

    Returns:
        A context manager yielding a one-item list whose value is the running count.
    """
    @contextmanager
    def counting():
        """Yield the live count while listening to the engine's executed statements.

        Yields:
            A one-item list holding the number of statements run so far.
        """
        count = [0]

        def on_execute(*_args):
            """Increment the count once per executed statement.

            Args:
                *_args: The event's arguments; unused.
            """
            count[0] += 1

        event.listen(app.state.engine, "before_cursor_execute", on_execute)
        try:
            yield count
        finally:
            event.remove(app.state.engine, "before_cursor_execute", on_execute)

    return counting
