import os
import io
import uuid
import openpyxl
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.auth.security import create_access_token
from app.models import UserRole

client = TestClient(
    app,
    headers={
        "Authorization": "Bearer " + create_access_token(
            user_id=1,
            email="admin@udayalibrary.org",
            role=UserRole.ADMINISTRATOR.value,
            name="Test Administrator",
            device_id="test-admin-device",
        )
    },
)


def get_admin_headers():
    res = client.post(
        "/api/auth/login",
        json={"email": "admin@udayalibrary.org", "password": os.environ["INITIAL_ADMIN_PASSWORD"]},
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_export_csv_xlsx_and_pdf():
    # 1. Export CSV
    res_csv = client.get("/api/bulk/export/csv")
    assert res_csv.status_code == 200
    assert res_csv.headers["content-type"].startswith("text/csv")
    assert "attachment;" in res_csv.headers["content-disposition"]
    assert len(res_csv.content) > 50

    # 2. Export XLSX
    res_xlsx = client.get("/api/bulk/export/xlsx")
    assert res_xlsx.status_code == 200
    assert "spreadsheetml" in res_xlsx.headers["content-type"]
    assert len(res_xlsx.content) > 1000
    # Validate XLSX can be parsed by openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(res_xlsx.content))
    assert "Catalogue" in wb.sheetnames

    # 3. Export PDF
    res_pdf = client.get("/api/bulk/export/pdf")
    assert res_pdf.status_code == 200
    assert res_pdf.headers["content-type"] == "application/pdf"
    assert res_pdf.content.startswith(b"%PDF")
    assert len(res_pdf.content) > 1000


def test_import_csv_and_xlsx_validation():
    uid = uuid.uuid4().hex[:6]
    st1 = f"IMP-{uid}-1"
    st2 = f"IMP-{uid}-2"

    csv_data = f"""Stock Number,Book Title,Author,Publisher,Category,Subcategory,Price
{st1},Cosmos,Carl Sagan,Ballantine,Science,Astronomy,499.00
{st2},Brief Answers,Stephen Hawking,Bantam,Science,Physics,350.50
"""
    files = {"file": ("catalogue.csv", csv_data.encode("utf-8"), "text/csv")}
    res_import = client.post("/api/bulk/import", files=files)
    assert res_import.status_code == 200
    data = res_import.json()
    assert data["success"] is True
    assert data["imported_count"] == 2
    assert data["error_count"] == 0

    # 2. Verify books appear in catalogue
    b1_res = client.get(f"/api/books?q={st1}")
    assert b1_res.json()["total"] == 1
    assert b1_res.json()["items"][0]["title"] == "Cosmos"

    # 3. Re-importing same file -> reports stock number duplication errors
    res_dupe = client.post("/api/bulk/import", files=files)
    assert res_dupe.status_code == 200
    dupe_data = res_dupe.json()
    assert dupe_data["imported_count"] == 0
    assert dupe_data["error_count"] == 2
    assert "already registered" in dupe_data["errors"][0]["error"]


def test_batch_registration_endpoint():
    uid = uuid.uuid4().hex[:6]
    payload = [
        {"stock_number": f"BATCH-{uid}-1", "title": f"Batch Title 1 {uid}", "author": "Author One"},
        {"stock_number": f"BATCH-{uid}-2", "title": f"Batch Title 2 {uid}", "author": "Author Two"},
    ]
    res = client.post("/api/bulk/batch-register", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["created_count"] == 2
    assert data["error_count"] == 0
    assert len(data["created_items"]) == 2


def test_backup_and_recovery():
    admin_headers = get_admin_headers()

    # 1. Non-admin denied backup download
    res_unauth = TestClient(app).get("/api/bulk/backup/download")
    assert res_unauth.status_code == 401

    # 2. Admin downloads valid verified backup
    res_backup = client.get("/api/bulk/backup/download", headers=admin_headers)
    assert res_backup.status_code == 200
    raw_backup_bytes = res_backup.content
    assert raw_backup_bytes.startswith(b"SQLite format 3\x00")

    # 3. Restore malformed database rejected with 400
    bad_files = {"file": ("bad.db", b"Not a database", "application/octet-stream")}
    res_bad_restore = client.post(
        "/api/bulk/backup/restore",
        headers=admin_headers,
        files=bad_files,
    )
    assert res_bad_restore.status_code == 400
    assert "not a valid SQLite database" in res_bad_restore.json()["detail"]

    # 4. Restore valid backup succeeds
    good_files = {"file": ("valid_backup.db", raw_backup_bytes, "application/octet-stream")}
    res_good_restore = client.post(
        "/api/bulk/backup/restore",
        headers=admin_headers,
        files=good_files,
    )
    assert res_good_restore.status_code == 200
    restore_data = res_good_restore.json()
    assert restore_data["success"] is True
    assert "Database successfully restored" in restore_data["message"]
