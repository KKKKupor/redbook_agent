"""SQLAlchemy base and shared utilities."""

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os


class Base(DeclarativeBase):
    pass


def get_engine():
    url = os.getenv("DATABASE_URL", "sqlite:///./data/local.db")
    return create_engine(url, echo=False)


def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()
