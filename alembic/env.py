"""Alembic environment: runs migrations against the same database the API uses."""

from logging.config import fileConfig

from alembic import context

from app.persistence import models  # noqa: F401 - registers every table on Base.metadata
from app.persistence.database import Base, get_database_url, get_engine

config = context.config

# Keep loggers that already exist (pytest's, the app's) when Alembic is run from Python code.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations() -> None:
    """Run migrations on the database from ``get_database_url()``.

    Raises:
        RuntimeError: If Alembic is run in offline (``--sql``) mode, which is not supported.
    """
    if context.is_offline_mode():
        raise RuntimeError("Offline (--sql) migrations are not supported; run them online.")

    engine = get_engine(get_database_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            # SQLite cannot alter most of a table in place; batch mode recreates the table instead.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
