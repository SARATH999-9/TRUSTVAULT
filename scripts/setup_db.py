"""Applies schema.sql on a fresh PostgreSQL database (tables + audit_log immutability triggers).
On SQLite (local/dev) the app creates tables itself at startup, and the triggers do not exist there."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from sqlalchemy import inspect  # noqa: E402

from app.db import engine  # noqa: E402


def main():
    if engine.dialect.name != "postgresql":
        print("SQLite: tables are created at app startup (no audit triggers on SQLite).")
        return
    if inspect(engine).has_table("users"):
        print("Schema already present.")
        return
    sql = (pathlib.Path(__file__).resolve().parent.parent / "schema.sql").read_text()
    raw = engine.raw_connection()
    try:
        raw.cursor().execute(sql)
        raw.commit()
    finally:
        raw.close()
    print("schema.sql applied.")


if __name__ == "__main__":
    main()
