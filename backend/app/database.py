"""SQLite engine / session plumbing for Cloud HoneyVault."""
import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "honeyvault.db")
DATABASE_URL = os.environ.get("HONEYVAULT_DB_URL", f"sqlite:///{DB_PATH}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the first release. `create_all` only creates missing
# *tables*, so an existing honeyvault.db would otherwise keep the old shape and
# fail on the first query. SQLite takes plain ADD COLUMN for nullable columns
# and for NOT NULL columns with a literal default, which is all of these.
ADDITIVE_COLUMNS = [
    ("files", "target_role", "VARCHAR(32)"),
    ("files", "decoy_generated_at", "DATETIME"),
    ("sessions", "decoy_mode", "BOOLEAN NOT NULL DEFAULT 0"),
]


def _apply_additive_columns():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in ADDITIVE_COLUMNS:
            if table not in tables:
                continue  # create_all just made it with the column already
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column in existing:
                continue
            conn.execute(
                text("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, ddl))
            )
            print("db: added %s.%s" % (table, column))


def init_db():
    """Create tables for every model, then backfill any added columns."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_additive_columns()
