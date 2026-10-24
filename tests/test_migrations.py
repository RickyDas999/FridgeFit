from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.persistence.database import Base, get_engine

ALEMBIC_INI = str(Path(__file__).resolve().parent.parent / "alembic.ini")


@pytest.fixture
def database_url(monkeypatch, tmp_path):
    """Point DATABASE_URL, which Alembic's env.py reads, at a fresh SQLite file.

    Args:
        monkeypatch: pytest's fixture for setting environment variables.
        tmp_path: pytest's per-test temporary directory.

    Returns:
        The database URL.
    """
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def test_upgrade_head_builds_exactly_the_models_schema(database_url):
    """Migrating a fresh database gives the schema the models describe, with nothing missing."""
    command.upgrade(Config(ALEMBIC_INI), "head")

    engine = get_engine(database_url)
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        current = MigrationContext.configure(connection).get_current_revision()
    engine.dispose()

    assert differences == []
    assert current == ScriptDirectory.from_config(Config(ALEMBIC_INI)).get_current_head()


def test_downgrade_base_removes_every_table(database_url):
    """Downgrading to base undoes the baseline, leaving only Alembic's version table."""
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    engine = get_engine(database_url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
