import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
    """Build an API app bound to a fresh SQLite file in a temporary directory.

    Args:
        tmp_path: pytest's per-test temporary directory.

    Returns:
        The FastAPI application.
    """
    return create_app(f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def client(app):
    """Provide an HTTP client for the app, with startup (table creation) already run.

    Args:
        app: The FastAPI application under test.

    Yields:
        A TestClient that sends requests to the app in-process.
    """
    with TestClient(app) as client:
        yield client
