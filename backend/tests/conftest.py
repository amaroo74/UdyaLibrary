import atexit
import os
import secrets
import shutil
import tempfile
from pathlib import Path

import pytest

TEST_DATABASE_DIR = Path(tempfile.mkdtemp(prefix="udaya-library-tests-"))
TEST_DATABASE_PATH = TEST_DATABASE_DIR / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE_PATH.as_posix()}"
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(32)
os.environ["INITIAL_ADMIN_EMAIL"] = "admin@udayalibrary.org"
os.environ["INITIAL_ADMIN_NAME"] = "Test Administrator"
os.environ["INITIAL_ADMIN_PASSWORD"] = secrets.token_urlsafe(24)


def _remove_test_database() -> None:
    shutil.rmtree(TEST_DATABASE_DIR, ignore_errors=True)


atexit.register(_remove_test_database)


PROTECTED_DATABASES = {
    (Path(__file__).resolve().parents[1] / "data" / "udaya_library.db").resolve(),
    (Path(__file__).resolve().parents[1] / "data" / "udaya_library_preview.db").resolve(),
}


def _sqlite_path(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    raw_path = database_url.removeprefix("sqlite:///")
    if raw_path in {":memory:", ""}:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path.resolve()


def assert_test_database_isolated() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    database_path = _sqlite_path(database_url)
    if database_path in PROTECTED_DATABASES:
        raise RuntimeError(
            "Test database isolation failure: pytest is configured to use a protected "
            f"application database ({database_path})."
        )
    if database_path != TEST_DATABASE_PATH.resolve():
        raise RuntimeError(
            "Test database isolation failure: pytest must use its temporary SQLite "
            f"database, not {database_url!r}."
        )


def pytest_sessionstart(session: pytest.Session) -> None:
    """Fail before test collection if the process is pointed at an app database."""
    assert_test_database_isolated()


@pytest.fixture(autouse=True)
def verify_test_database_isolation() -> None:
    """Prevent tests from changing the configured database to a protected path."""
    assert_test_database_isolated()
    yield
    assert_test_database_isolated()
