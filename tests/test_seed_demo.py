import pytest
from sqlalchemy import func, select

from app.persistence.database import get_engine, get_session_factory
from app.persistence.models import Recipe
from scripts.seed_demo import seed


def test_seed_refuses_a_non_sqlite_database(monkeypatch):
    """The destructive demo reset will not run against a configured PostgreSQL database."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.example/fridgefit")

    with pytest.raises(SystemExit, match="non-SQLite"):
        seed()


def test_seed_resets_the_configured_sqlite_database(monkeypatch, tmp_path):
    """With a SQLite DATABASE_URL, the seed fills that database with the demo dataset."""
    database_url = f"sqlite:///{tmp_path / 'demo.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    seed()

    with get_session_factory(get_engine(database_url))() as session:
        assert session.scalar(select(func.count()).select_from(Recipe)) > 0
