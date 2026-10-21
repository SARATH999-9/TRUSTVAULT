from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_schema(eng=None) -> None:
    """Fail early, with a clear message, if the database was created by an older version of TrustVault
    (which had no account approval). create_all() never alters existing tables."""
    insp = inspect(eng or engine)
    if insp.has_table("users") and "status" not in {c["name"] for c in insp.get_columns("users")}:
        raise RuntimeError(
            "This database was created by an older version of TrustVault and is missing newer columns. "
            "For a local SQLite database, stop the server, delete the file (trustvault.db) and start again. "
            "For PostgreSQL, apply schema.sql to a fresh database.")
