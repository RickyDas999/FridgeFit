import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, select

from app.persistence.database import Base, get_engine, get_session_factory
from app.persistence.models import Ingredient, MealLog, Recipe
from scripts.seed_demo import ALEMBIC_INI, INGREDIENTS, main


def count(database_url, model):
    """Count the rows of one model in a database.

    Args:
        database_url: The database to inspect.
        model: The model class whose rows to count.

    Returns:
        The number of rows.
    """
    engine = get_engine(database_url)
    with get_session_factory(engine)() as session:
        total = session.scalar(select(func.count()).select_from(model))
    engine.dispose()
    return total


@pytest.fixture
def migrated_database_url(monkeypatch, empty_database_url):
    """Point DATABASE_URL at an empty database that is at the latest migration.

    Args:
        monkeypatch: pytest's fixture for setting environment variables.
        empty_database_url: An empty database for this test (PostgreSQL when configured).

    Returns:
        The database URL.
    """
    monkeypatch.setenv("DATABASE_URL", empty_database_url)
    command.upgrade(Config(ALEMBIC_INI), "head")
    return empty_database_url


def test_reset_refuses_a_non_sqlite_database(monkeypatch):
    """The destructive default will not run against a configured PostgreSQL database."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.example/fridgefit")

    with pytest.raises(SystemExit, match="non-SQLite"):
        main([])


def test_reset_fills_the_configured_sqlite_database(monkeypatch, tmp_path):
    """With a SQLite DATABASE_URL, the default reset fills that database with the demo dataset."""
    database_url = f"sqlite:///{tmp_path / 'demo.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    main([])

    assert count(database_url, Recipe) > 0


def test_reset_migrates_a_database_built_before_alembic(monkeypatch, tmp_path):
    """A pre-Alembic database (tables, no version) is rebuilt and left at the latest migration."""
    database_url = f"sqlite:///{tmp_path / 'old.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)

    main([])

    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() is not None
    engine.dispose()
    assert count(database_url, Recipe) > 0


def test_insert_only_fills_a_migrated_empty_database(migrated_database_url):
    """--insert-only adds the dataset to an empty database at the latest migration."""
    main(["--insert-only"])

    assert count(migrated_database_url, Ingredient) == len(INGREDIENTS)
    assert count(migrated_database_url, MealLog) > 0


def test_insert_only_refuses_a_database_that_has_data(migrated_database_url):
    """A second --insert-only run, or one on real data, refuses and writes nothing."""
    main(["--insert-only"])
    meals_before = count(migrated_database_url, MealLog)

    with pytest.raises(SystemExit, match="not empty"):
        main(["--insert-only"])

    assert count(migrated_database_url, Ingredient) == len(INGREDIENTS)
    assert count(migrated_database_url, MealLog) == meals_before


def test_insert_only_refuses_an_unmigrated_database(monkeypatch, empty_database_url):
    """--insert-only refuses a database that is not at the latest migration."""
    monkeypatch.setenv("DATABASE_URL", empty_database_url)

    with pytest.raises(SystemExit, match="alembic upgrade head"):
        main(["--insert-only"])


def test_unknown_arguments_are_rejected_before_anything_runs(monkeypatch, tmp_path):
    """A mistyped flag fails instead of falling through to the destructive reset."""
    database_url = f"sqlite:///{tmp_path / 'untouched.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    with pytest.raises(SystemExit):
        main(["--insert-onyl"])

    assert not (tmp_path / "untouched.db").exists()
