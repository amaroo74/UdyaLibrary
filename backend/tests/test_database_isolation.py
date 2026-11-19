from pathlib import Path

from app import database
from conftest import PROTECTED_DATABASES, TEST_DATABASE_PATH, _sqlite_path


def test_tests_use_a_private_temporary_database():
    configured_path = _sqlite_path(database.DATABASE_URL)
    engine_path = _sqlite_path(str(database.engine.url))

    assert configured_path == TEST_DATABASE_PATH.resolve()
    assert engine_path == TEST_DATABASE_PATH.resolve()
    assert configured_path not in PROTECTED_DATABASES
    assert engine_path not in PROTECTED_DATABASES
    assert Path(configured_path).parent.name.startswith("udaya-library-tests-")
