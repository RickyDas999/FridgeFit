import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.api.main import create_app
from app.errors import InvalidInputError
from app.persistence.database import Base


@pytest.fixture
def app(tmp_path):
    """Build an API app bound to a fresh SQLite file in a temporary directory.

    Args:
        tmp_path: pytest's per-test temporary directory.

    Returns:
        The FastAPI application.
    """
    return create_app(f"sqlite:///{tmp_path / 'test.db'}")


def test_health_reports_ok(app):
    """GET /health returns 200 with status ok when the database is reachable."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_creates_every_table(app):
    """Starting the app creates the full schema in a fresh database."""
    with TestClient(app):
        tables = set(inspect(app.state.engine).get_table_names())

    assert tables == set(Base.metadata.tables)


def test_invalid_input_error_becomes_422(app):
    """An InvalidInputError raised while handling a request returns 422 with its message."""

    def reject():
        """Raise the domain validation error the handler should translate."""
        raise InvalidInputError("servings must be positive")

    app.get("/reject")(reject)

    with TestClient(app) as client:
        response = client.get("/reject")

    assert response.status_code == 422
    assert response.json() == {"detail": "servings must be positive"}


def test_unknown_path_returns_404(app):
    """A path outside the API surface returns 404."""
    with TestClient(app) as client:
        response = client.get("/does-not-exist")

    assert response.status_code == 404
