import atexit
import os
import secrets
import shutil
import tempfile
from pathlib import Path


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
