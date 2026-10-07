import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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
