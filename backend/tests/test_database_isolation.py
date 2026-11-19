import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import database
from app.database import BACKEND_DIR, normalize_database_url
from conftest import PROTECTED_DATABASES, TEST_DATABASE_PATH, _sqlite_path


def test_tests_use_a_private_temporary_database():
    configured_path = _sqlite_path(database.DATABASE_URL)
    engine_path = _sqlite_path(str(database.engine.url))

    assert configured_path == TEST_DATABASE_PATH.resolve()
    assert engine_path == TEST_DATABASE_PATH.resolve()
    assert configured_path not in PROTECTED_DATABASES
    assert engine_path not in PROTECTED_DATABASES
    assert Path(configured_path).parent.name.startswith("udaya-library-tests-")


def test_normalize_database_url_resolves_relative_sqlite_paths(tmp_path: Path):
    # Relative path with ./ prefix
    url_dot = "sqlite:///./data/udaya_library.db"
    normalized_dot = normalize_database_url(url_dot, base_dir=tmp_path)
    expected_dot = f"sqlite:///{(tmp_path / 'data' / 'udaya_library.db').resolve().as_posix()}"
    assert normalized_dot == expected_dot

    # Relative path without ./ prefix
    url_rel = "sqlite:///data/udaya_library.db"
    normalized_rel = normalize_database_url(url_rel, base_dir=tmp_path)
    expected_rel = f"sqlite:///{(tmp_path / 'data' / 'udaya_library.db').resolve().as_posix()}"
    assert normalized_rel == expected_rel

    # Default backend resolution against BACKEND_DIR
    default_normalized = normalize_database_url("sqlite:///./data/udaya_library.db")
    expected_backend = f"sqlite:///{(BACKEND_DIR / 'data' / 'udaya_library.db').resolve().as_posix()}"
    assert default_normalized == expected_backend


def test_normalize_database_url_preserves_absolute_paths(tmp_path: Path):
    abs_path = (tmp_path / "custom_library.db").resolve()
    abs_url = f"sqlite:///{abs_path.as_posix()}"
    normalized = normalize_database_url(abs_url, base_dir=BACKEND_DIR)
    assert normalized == abs_url


def test_normalize_database_url_preserves_in_memory_and_non_sqlite():
    # In-memory URLs
    assert normalize_database_url("sqlite:///:memory:") == "sqlite:///:memory:"
    assert normalize_database_url("sqlite:///") == "sqlite:///"

    # Non-SQLite URLs
    pg_url = "postgresql://user:pass@localhost:5432/udaya_db"
    assert normalize_database_url(pg_url) == pg_url


def test_importing_or_reloading_app_main_does_not_execute_database_operations(monkeypatch: pytest.MonkeyPatch):
    """Verify that importing or reloading app.main executes zero database write/setup operations."""
    import app.category_seed
    import app.database
    import app.main
    import app.routers.auth

    mock_create_all = MagicMock()
    mock_migrations = MagicMock()
    mock_admin = MagicMock()
    mock_seed = MagicMock()

    monkeypatch.setattr(app.database.Base.metadata, "create_all", mock_create_all)
    monkeypatch.setattr(app.database, "run_migrations", mock_migrations)
    monkeypatch.setattr(app.routers.auth, "provision_initial_admin", mock_admin)
    monkeypatch.setattr(app.category_seed, "seed_default_categories", mock_seed)

    # Reload app.main to test module-import execution
    importlib.reload(app.main)

    # Zero database operations must have executed on import/reload
    assert mock_create_all.call_count == 0
    assert mock_migrations.call_count == 0
    assert mock_admin.call_count == 0
    assert mock_seed.call_count == 0

    # Explicit initialize_database() should call each helper in order
    app.main.initialize_database()

    assert mock_create_all.call_count == 1
    assert mock_migrations.call_count == 1
    assert mock_admin.call_count == 1
    assert mock_seed.call_count == 1
