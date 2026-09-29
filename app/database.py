from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = "sqlite:///fridgefit.db"


class Base(DeclarativeBase):
    pass


def get_engine(database_url: str = DATABASE_URL):
    return create_engine(database_url)


def get_session_factory(engine):
    return sessionmaker(bind=engine)
