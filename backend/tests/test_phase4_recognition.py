import io
import pytest
from PIL import Image, ImageDraw
import zxingcpp
from fastapi.testclient import TestClient
from app.auth.security import create_access_token
from app.models import UserRole

from app.main import app
from app.metadata.providers import clean_isbn, normalize_candidate, search_metadata
from app.recognition.service import (
    extract_barcodes_from_image,
    extract_text_from_image,
    clean_ocr_lines,
    process_recognition_image,
)


async def fake_metadata_search(**kwargs):
    return [
        {
            "title": "Ikigai",
            "author": "Héctor García",
            "publisher": "Penguin",
            "price": None,
            "price_source": None,
            "source": "Mock provider",
        }
    ]


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


def create_test_barcode_image(code: str = "9780143424123") -> bytes:
    """Helper to generate an in-memory PNG with an EAN-13 barcode."""
    barcode = zxingcpp.create_barcode(code, zxingcpp.BarcodeFormat.EAN13)
    img_array = barcode.to_image()
    pil_img = Image.fromarray(img_array)
    # Add border/margins like a real book cover back
    canvas = Image.new("RGB", (300, 200), color=(255, 255, 255))
    canvas.paste(pil_img, (50, 60))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def test_clean_isbn():
    assert clean_isbn("978-0-14-342412-3") == "9780143424123"
    assert clean_isbn("0-19-852663-6") == "0198526636"
    assert clean_isbn("  9780143424123  ") == "9780143424123"


def test_normalize_candidate():
    c = normalize_candidate(
        title="Wings of Fire",
        author="A.P.J. Abdul Kalam",
        publisher="Universities Press",
        price=295.0,
        price_source="Google Books (INR)",
        source="Google Books",
    )
    assert c["title"] == "Wings of Fire"
    assert c["author"] == "A.P.J. Abdul Kalam"
    assert c["publisher"] == "Universities Press"
    assert c["price"] == 295.0
    assert c["price_source"] == "Google Books (INR)"
    assert "isbn" not in c  # Persistent fields only!


def test_clean_ocr_lines():
    raw = """
    #$@%
    Wings of Fire
    An Autobiography
    A.P.J. Abdul Kalam
    x
    """
    cleaned = clean_ocr_lines(raw)
    assert "Wings of Fire" in cleaned
    assert "An Autobiography" in cleaned
    assert "A.P.J. Abdul Kalam" in cleaned
    assert "#$@%" not in cleaned
    assert "x" not in cleaned


def test_barcode_extraction_clean_and_rotated():
    img_bytes = create_test_barcode_image("9780143424123")
    pil_img = Image.open(io.BytesIO(img_bytes))

    # Standard upright orientation
    barcodes = extract_barcodes_from_image(pil_img)
    assert "9780143424123" in barcodes

    # Angled 90 degrees (common phone photo rotation)
    rotated = pil_img.rotate(90, expand=True)
    rotated_barcodes = extract_barcodes_from_image(rotated)
    assert "9780143424123" in rotated_barcodes


@pytest.mark.asyncio
async def test_process_recognition_image_with_barcode(monkeypatch):
    monkeypatch.setattr("app.recognition.service.search_metadata", fake_metadata_search)
    img_bytes = create_test_barcode_image("9780143424123")
    res = await process_recognition_image(img_bytes)

    assert res["success"] is True
    assert res["barcode"] == "9780143424123"
    # Should attempt online metadata search and return candidate results
    assert isinstance(res["candidates"], list)


def test_api_recognition_barcode_endpoint(monkeypatch):
    monkeypatch.setattr("app.routers.recognition.search_metadata", fake_metadata_search)
    res = client.post("/api/recognition/barcode", json={"barcode": "9780143424123"})
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    if data:
        first = data[0]
        assert "title" in first
        assert "author" in first
        assert "isbn" not in first  # ISBN not persisted in candidate


def test_api_recognition_scan_endpoint(monkeypatch):
    monkeypatch.setattr("app.recognition.service.search_metadata", fake_metadata_search)
    img_bytes = create_test_barcode_image("9780143424123")
    files = {"file": ("test_cover.png", img_bytes, "image/png")}
    res = client.post("/api/recognition/scan", files=files)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["barcode"] == "9780143424123"
    assert isinstance(body["candidates"], list)


def test_api_recognition_lookup_endpoint(monkeypatch):
    monkeypatch.setattr("app.routers.recognition.search_metadata", fake_metadata_search)
    res = client.get("/api/recognition/lookup?title=Wings+of+Fire")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    for cand in data:
        assert "title" in cand
        assert "source" in cand


def test_api_recognition_lookup_empty_params_rejected():
    res = client.get("/api/recognition/lookup")
    assert res.status_code == 400
    assert "Provide at least one search parameter" in res.json()["detail"]


def test_api_recognition_scan_corrupted_image():
    # Pass random non-image bytes
    files = {"file": ("corrupt.jpg", b"not-a-valid-image-data-at-all", "image/jpeg")}
    res = client.post("/api/recognition/scan", files=files)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is False
    assert "Invalid or unreadable image" in body["message"]


def test_api_recognition_scan_blank_image():
    # Blank white image has no barcode and no text
    blank = Image.new("RGB", (200, 200), color=(255, 255, 255))
    buf = io.BytesIO()
    blank.save(buf, format="PNG")
    files = {"file": ("blank.png", buf.getvalue(), "image/png")}
    res = client.post("/api/recognition/scan", files=files)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["barcode"] is None
    assert body["candidates"] == []
    assert "No barcode or readable cover text" in body["message"]


def test_api_recognition_scan_non_image_type_rejected():
    files = {"file": ("document.pdf", b"%PDF-1.4", "application/pdf")}
    res = client.post("/api/recognition/scan", files=files)
    assert res.status_code == 400
    assert "Uploaded file must be an image" in res.json()["detail"]

