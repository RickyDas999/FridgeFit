from unittest.mock import Mock

from app.persistence.database import (
    LOCAL_DATABASE_URL,
    _enable_sqlite_foreign_keys,
    get_database_url,
)


def test_database_url_comes_from_the_environment(monkeypatch):
    """A set DATABASE_URL is used as-is."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.example/fridgefit")

    assert get_database_url() == "postgresql://user:secret@db.example/fridgefit"


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
