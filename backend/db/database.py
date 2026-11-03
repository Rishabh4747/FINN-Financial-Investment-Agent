"""
SQLAlchemy engine, session factory, and Base for all ORM models.
"""
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # required for SQLite
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def run_migrations(target_engine):
    """
    Safely runs database migrations and ensures virtual tables (FTS5) are initialized.
    Preserves all existing data across tables.
    """
    inspector = inspect(target_engine)
    if "announcements" in inspector.get_table_names():
        existing_cols = {col["name"] for col in inspector.get_columns("announcements")}
        new_cols = [
            ("description", "TEXT"),
            ("classification_rationale", "TEXT"),
            ("classification_confidence", "VARCHAR(20)"),
            ("materiality_score", "FLOAT"),
            ("materiality_rationale", "TEXT"),
            ("filing_datetime", "DATETIME"),
            ("dedup_key", "VARCHAR(128)"),
        ]
        with target_engine.connect() as conn:
            for col_name, col_type in new_cols:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE announcements ADD COLUMN {col_name} {col_type}"))
            conn.commit()

    # Initialize FTS5 virtual table for high-speed passage retrieval if SQLite supports it
    with target_engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
                    chunk_id UNINDEXED,
                    document_id UNINDEXED,
                    ticker UNINDEXED,
                    page_number UNINDEXED,
                    content,
                    tokenize = 'porter unicode61'
                )
            """))
            conn.commit()
        except Exception:
            # Fallback if FTS5 is not compiled into a particular SQLite binary
            pass


def get_db():
    """FastAPI dependency — yields a DB session and closes it on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
