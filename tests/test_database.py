from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.persistence.database import (
    LOCAL_DATABASE_URL,
    _enable_sqlite_foreign_keys,
    get_database_url,
)


def test_database_url_comes_from_the_environment(monkeypatch):
    """A set DATABASE_URL that already names its driver is used as-is."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:secret@db.example/fridgefit")

    assert get_database_url() == "postgresql+psycopg://user:secret@db.example/fridgefit"


def test_postgres_urls_without_a_driver_get_psycopg(monkeypatch):
    """Hosted-database URLs (postgres:// or postgresql://) are pointed at psycopg 3."""
    for given in ("postgres://user:secret@db.example/fridgefit",
                  "postgresql://user:secret@db.example/fridgefit"):
        monkeypatch.setenv("DATABASE_URL", given)

        assert get_database_url() == "postgresql+psycopg://user:secret@db.example/fridgefit"


def test_database_url_defaults_to_the_local_sqlite_file(monkeypatch):
    """Without DATABASE_URL, or with it empty, the local SQLite file is used."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert get_database_url() == LOCAL_DATABASE_URL

    monkeypatch.setenv("DATABASE_URL", "")
    assert get_database_url() == LOCAL_DATABASE_URL


def test_foreign_key_pragma_is_skipped_for_non_sqlite_connections():
    """The SQLite PRAGMA hook leaves connections to other databases untouched."""
    other_connection = Mock()

    _enable_sqlite_foreign_keys(other_connection, None)

    other_connection.cursor.assert_not_called()


def test_api_survives_database_connections_dropped_while_idle(app, client, empty_database_url):
    """After the server drops the API's pooled connections (as a restart does), requests work."""
    if make_url(empty_database_url).get_backend_name() != "postgresql":
        pytest.skip("needs PostgreSQL (TEST_DATABASE_URL) to terminate server-side connections")
    assert client.get("/health").status_code == 200  # leaves a connection in the pool

    killer = create_engine(empty_database_url, poolclass=NullPool)
    with killer.begin() as connection:
        connection.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        ))
    killer.dispose()

    assert client.get("/health").status_code == 200
