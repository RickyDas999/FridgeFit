from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.api.main import create_app
from app.errors import InvalidInputError
from app.persistence.database import Base


def test_health_reports_ok(app):
    """GET /health returns 200 with status ok when the database is reachable."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_uses_database_url_from_the_environment(monkeypatch, tmp_path):
    """Without an explicit URL, create_app connects to the DATABASE_URL environment variable."""
    database_url = f"sqlite:///{tmp_path / 'from-env.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    app = create_app()

    assert app.state.engine.url.render_as_string() == database_url


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


def test_cors_preflight_allows_a_post_with_an_idempotency_key(client):
    """The local frontend may POST JSON with an Idempotency-Key header (the preflight passes)."""
    response = client.options("/recipes/1/confirm", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,idempotency-key",
    })

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "idempotency-key" in allowed and "content-type" in allowed
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in response.headers


def test_cors_allows_the_local_frontend_to_read_responses(client):
    """A simple GET from the Vite dev origin gets its origin echoed back."""
    response = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_cors_rejects_other_origins(client):
    """Origins other than the local frontend get no CORS permission."""
    preflight = client.options("/health", headers={
        "Origin": "https://example.com",
        "Access-Control-Request-Method": "GET",
    })
    simple = client.get("/health", headers={"Origin": "https://example.com"})

    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in simple.headers
