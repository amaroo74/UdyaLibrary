import os
import uuid
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_admin_login_and_invalid_credentials():
    # 1. Login with correct default admin credentials
    res = client.post(
        "/api/auth/login",
        json={"email": "admin@udayalibrary.org", "password": os.environ["INITIAL_ADMIN_PASSWORD"]},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["role"] == "administrator"
    assert data["user"]["email"] == "admin@udayalibrary.org"

    # 2. Login with wrong password -> 401 Unauthorized
    bad_pw_res = client.post(
        "/api/auth/login",
        json={"email": "admin@udayalibrary.org", "password": "WrongPassword!"},
    )
    assert bad_pw_res.status_code == 401

    # 3. Login with nonexistent email -> 401 Unauthorized
    bad_email_res = client.post(
        "/api/auth/login",
        json={"email": "nonexistent@udayalibrary.org", "password": os.environ["INITIAL_ADMIN_PASSWORD"]},
    )
    assert bad_email_res.status_code == 401


def test_rbac_user_creation_and_audit_log_protection():
    # 1. Log in as admin
    admin_auth = client.post(
        "/api/auth/login",
        json={"email": "admin@udayalibrary.org", "password": os.environ["INITIAL_ADMIN_PASSWORD"]},
    ).json()
    admin_token = admin_auth["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    uid = uuid.uuid4().hex[:6]
    lib_email = f"librarian_{uid}@udayalibrary.org"
    restr_email = f"restricted_{uid}@udayalibrary.org"

    # 2. Admin creates a standard librarian account
    res_lib = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "email": lib_email,
            "name": "Standard Librarian",
            "password": "LibPassword123!",
            "role": "librarian",
        },
    )
    assert res_lib.status_code == 201

    # 3. Admin creates a restricted librarian account
    res_restr = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "email": restr_email,
            "name": "Restricted Librarian",
            "password": "RestrPassword123!",
            "role": "restricted_librarian",
        },
    )
    assert res_restr.status_code == 201

    # 4. Standard librarian logs in
    lib_auth = client.post(
        "/api/auth/login",
        json={"email": lib_email, "password": "LibPassword123!"},
    ).json()
    lib_token = lib_auth["access_token"]
    lib_headers = {"Authorization": f"Bearer {lib_token}"}

    # 5. Standard librarian CANNOT view audit history -> 403 Forbidden
    res_audit_forbidden = client.get("/api/auth/audit-logs", headers=lib_headers)
    assert res_audit_forbidden.status_code == 403
    assert "Permission denied" in res_audit_forbidden.json()["detail"]

    # 6. Admin CAN view audit history -> 200 OK
    res_audit_ok = client.get("/api/auth/audit-logs", headers=admin_headers)
    assert res_audit_ok.status_code == 200
    logs = res_audit_ok.json()
    assert isinstance(logs, list)
    assert len(logs) > 0
    # Audit log contains actor details
    assert any(log["actor"] == "admin@udayalibrary.org" for log in logs)


def test_restricted_librarian_permissions_and_trusted_pin():
    # 1. Log in as admin and create a restricted librarian
    admin_auth = client.post(
        "/api/auth/login",
        json={"email": "admin@udayalibrary.org", "password": os.environ["INITIAL_ADMIN_PASSWORD"]},
    ).json()
    admin_headers = {"Authorization": f"Bearer {admin_auth['access_token']}"}

    uid = uuid.uuid4().hex[:6]
    restr_email = f"restricted_guard_{uid}@udayalibrary.org"
    client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "email": restr_email,
            "name": "Restricted User",
            "password": "Password123!",
            "role": "restricted_librarian",
        },
    )

    # 2. Restricted librarian logs in
    auth_restr = client.post(
        "/api/auth/login",
        json={"email": restr_email, "password": "Password123!", "device_id": "desk-pc-01"},
    ).json()
    restr_headers = {"Authorization": f"Bearer {auth_restr['access_token']}"}

    # 3. Restricted librarian can create a book
    stock_num = f"RESTR-{uid}"
    create_res = client.post(
        "/api/books",
        headers=restr_headers,
        json={"stock_number": stock_num, "title": f"Book By Restricted {uid}"},
    )
    assert create_res.status_code == 201
    book_id = create_res.json()["id"]

    # 4. Restricted librarian CANNOT delete book -> 403 Forbidden
    del_res = client.delete(f"/api/books/{book_id}", headers=restr_headers)
    assert del_res.status_code == 403
    assert "Restricted librarians cannot delete books" in del_res.json()["detail"]

    # 5. Set up trusted-device PIN for fast login
    pin_res = client.post(
        "/api/auth/set-pin",
        headers=restr_headers,
        json={"pin": "2468", "device_id": "desk-pc-01"},
    )
    assert pin_res.status_code == 200
    assert pin_res.json()["has_trusted_pin"] is True

    # 6. Login using trusted-device PIN
    pin_login_res = client.post(
        "/api/auth/pin-login",
        json={"email": restr_email, "device_id": "desk-pc-01", "pin": "2468"},
    )
    assert pin_login_res.status_code == 200
    assert "access_token" in pin_login_res.json()

    # 7. Untrusted device ID with correct PIN -> 401 Unauthorized
    untrusted_dev_res = client.post(
        "/api/auth/pin-login",
        json={"email": restr_email, "device_id": "unknown-device-99", "pin": "2468"},
    )
    assert untrusted_dev_res.status_code == 401

    # 8. Wrong PIN on trusted device -> 401 Unauthorized
    wrong_pin_res = client.post(
        "/api/auth/pin-login",
        json={"email": restr_email, "device_id": "desk-pc-01", "pin": "0000"},
    )
    assert wrong_pin_res.status_code == 401

    # Cleanup book using admin
    client.delete(f"/api/books/{book_id}", headers=admin_headers)
