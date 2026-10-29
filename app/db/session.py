from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///mailwise.db"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# Columns added after the first release: (table, column, SQL type). create_all never adds these
# to an existing table, so ensure_schema does.
_ADDED_COLUMNS = [
    ("emails", "links", "TEXT"),
]

def ensure_schema(bind=None):
    """Adds any missing column from _ADDED_COLUMNS. Safe to run repeatedly; skips tables that don't exist yet."""
    bind = bind or engine
    with bind.begin() as conn:
        for table, column, sql_type in _ADDED_COLUMNS:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if existing and column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))

def init_db():
    Base.metadata.create_all(bind=engine)
    ensure_schema()
