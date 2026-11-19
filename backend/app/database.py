import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"


def load_application_environment(env_file: Path = ENV_FILE) -> None:
    """Load backend/.env without overriding explicitly supplied environment values."""
    load_dotenv(dotenv_path=env_file, override=False)


load_application_environment()


def normalize_database_url(url: str, base_dir: Path = BACKEND_DIR) -> str:
    """Normalize SQLite database URLs so relative paths resolve against base_dir."""
    if not url.startswith("sqlite:///"):
        return url
    raw_path = url.removeprefix("sqlite:///")
    if raw_path in {":memory:", ""}:
        return url
    path = Path(raw_path)
    if path.is_absolute():
        return url
    resolved_path = (base_dir / path).resolve()
    return f"sqlite:///{resolved_path.as_posix()}"


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./data/udaya_library.db"))

if DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.removeprefix("sqlite:///")
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
    )
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def run_migrations():
    """Ensure any newly added columns exist in existing SQLite databases."""
    if DATABASE_URL.startswith("sqlite"):
        try:
            with engine.connect() as conn:
                # Check audit_logs columns
                audit_cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(audit_logs)").fetchall()]
                if audit_cols and "actor_role" not in audit_cols:
                    conn.exec_driver_sql("ALTER TABLE audit_logs ADD COLUMN actor_role VARCHAR(50) DEFAULT 'librarian'")
                if audit_cols and "device_id" not in audit_cols:
                    conn.exec_driver_sql("ALTER TABLE audit_logs ADD COLUMN device_id VARCHAR(100)")

                # Check books columns (Phase 8: version and device_id)
                book_cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(books)").fetchall()]
                if book_cols and "version" not in book_cols:
                    conn.exec_driver_sql("ALTER TABLE books ADD COLUMN version INTEGER DEFAULT 1 NOT NULL")
                if book_cols and "device_id" not in book_cols:
                    conn.exec_driver_sql("ALTER TABLE books ADD COLUMN device_id VARCHAR(100)")
                for column, definition in [
                    ("publication_date", "VARCHAR(50)"),
                    ("publication_year", "INTEGER"),
                    ("edition", "VARCHAR(300)"),
                    ("language", "VARCHAR(100)"),
                    ("page_count", "INTEGER"),
                    ("description", "TEXT"),
                    ("isbn", "VARCHAR(13)"),
                    ("price_currency", "VARCHAR(3)"),
                ]:
                    if book_cols and column not in book_cols:
                        conn.exec_driver_sql(f"ALTER TABLE books ADD COLUMN {column} {definition}")

                conn.commit()
        except Exception as exc:
            logger.warning("Database migration failed: %r", exc)
