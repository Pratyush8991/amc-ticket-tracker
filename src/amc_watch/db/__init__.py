"""One Postgres, shared by all three services (ADR-0002).

Services coordinate exclusively through this database — no broker, no inter-service
HTTP — so anything that needs to cross a service boundary has to be a table.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base, Showtime

DEFAULT_DATABASE_URL = "postgresql+psycopg://localhost/amc_watch"


def database_url():
    """Where this process's Postgres lives."""
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_engine_from_env(url=None, **kwargs):
    return create_engine(url or database_url(), **kwargs)


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


__all__ = [
    "DEFAULT_DATABASE_URL",
    "Base",
    "Showtime",
    "create_engine_from_env",
    "database_url",
    "session_factory",
]
