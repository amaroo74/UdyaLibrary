import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"


def load_application_environment(env_file: Path = ENV_FILE) -> None:
    """Load backend/.env without overriding explicitly supplied environment values."""
    load_dotenv(dotenv_path=env_file, override=False)


load_application_environment()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/udaya_library.db")

if DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.replace("sqlite:///", "", 1)
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

                conn.commit()
        except Exception:
            pass
