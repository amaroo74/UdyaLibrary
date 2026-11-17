import os
import subprocess
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth.security import SECRET_KEY
from app.database import Base, ENV_FILE, SessionLocal, load_application_environment
from app.main import app
from app.models import User
from app.routers.auth import provision_initial_admin


client = TestClient(app)


def _import_security_with_environment(**changes: str | None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("JWT_SECRET_KEY", None)
    for key, value in changes.items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    return subprocess.run(
        [sys.executable, "-c", "import app.auth.security"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_jwt_secret_is_required_and_rejects_insecure_values():
    missing = _import_security_with_environment()
    assert missing.returncode != 0
    assert "JWT_SECRET_KEY must be set" in missing.stderr

    invalid = _import_security_with_environment(JWT_SECRET_KEY="too-short")
    assert invalid.returncode != 0
    assert "JWT_SECRET_KEY is insecure" in invalid.stderr

    placeholder = _import_security_with_environment(
        JWT_SECRET_KEY="replace-with-at-least-43-character-value-from-32-random-bytes"
    )
    assert placeholder.returncode != 0
    assert "JWT_SECRET_KEY is insecure" in placeholder.stderr


def test_backend_env_file_loading_is_explicit_and_does_not_override_process_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TEST_ENV_FILE_SECRET=file-secret\nTEST_ENV_PROCESS_SECRET=file-value\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TEST_ENV_FILE_SECRET", raising=False)
    monkeypatch.setenv("TEST_ENV_PROCESS_SECRET", "process-secret")
    loaded = load_application_environment(env_file)
    assert loaded is None
    assert ENV_FILE.name == ".env"
    assert os.environ["TEST_ENV_FILE_SECRET"] == "file-secret"
    assert os.environ["TEST_ENV_PROCESS_SECRET"] == "process-secret"


def test_initial_admin_placeholder_password_is_rejected(monkeypatch):
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "replace-with-a-strong-one-time-password")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    with TestSession() as db:
        try:
            provision_initial_admin(db)
        except RuntimeError as error:
            assert "INITIAL_ADMIN_PASSWORD" in str(error)
        else:
            raise AssertionError("placeholder initial password was accepted")
    engine.dispose()


def test_generated_test_secret_is_loaded_without_exposing_it():
    assert len(SECRET_KEY) >= 43
    assert SECRET_KEY not in client.get("/api/health").text


def test_fresh_install_provisions_one_admin_and_existing_admin_is_preserved(monkeypatch):
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == os.environ["INITIAL_ADMIN_EMAIL"]))
        assert admin is not None
        original_id = admin.id
        original_hash = admin.password_hash
        assert provision_initial_admin(db) is None

    with SessionLocal() as db:
        preserved = db.get(User, original_id)
        assert preserved is not None
        assert preserved.password_hash == original_hash

    response = client.post(
        "/api/auth/login",
        json={
            "email": os.environ["INITIAL_ADMIN_EMAIL"],
            "password": os.environ["INITIAL_ADMIN_PASSWORD"],
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()

    monkeypatch.delenv("INITIAL_ADMIN_EMAIL")
    monkeypatch.delenv("INITIAL_ADMIN_NAME")
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD")
    with SessionLocal() as db:
        assert provision_initial_admin(db) is None


def test_login_rejects_invalid_password():
    response = client.post(
        "/api/auth/login",
        json={
            "email": os.environ["INITIAL_ADMIN_EMAIL"],
            "password": "definitely-not-the-password",
        },
    )
    assert response.status_code == 401
