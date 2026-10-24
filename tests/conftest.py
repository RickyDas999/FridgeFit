from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.main import create_app
from app.persistence.database import Base


@pytest.fixture
def session():
    """Provide a session bound to a fresh in-memory SQLite database.

    Each test gets its own empty database with all tables created, so
    tests never share state.

    Yields:
        An open SQLAlchemy Session, closed after the test finishes.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


@pytest.fixture
def app(tmp_path):
    """Build an API app bound to a fresh SQLite file in a temporary directory, with every table.

    Tables come from the models directly (fast); ``tests/test_migrations.py`` proves the
    migrations build the same schema.

    Args:
        tmp_path: pytest's per-test temporary directory.

    Returns:
        The FastAPI application.
    """
    app = create_app(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(app.state.engine)
    return app


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
