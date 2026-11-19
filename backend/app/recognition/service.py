"""
Recognition service for barcode scanning and front-cover OCR text extraction.
All images are processed strictly in-memory and immediately discarded.
Cover photos are never stored in the database or filesystem.
"""

import io
import logging
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from typing import Any
from PIL import Image, ImageEnhance, ImageOps
import zxingcpp

from ..metadata.providers import search_metadata, clean_isbn

logger = logging.getLogger(__name__)
MetadataLookup = Callable[..., Awaitable[list[dict[str, Any]]]]

# Check if tesseract is available
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")
HAVE_TESSERACT = False
try:
    import pytesseract

    # Check custom path or standard PATH
    candidate_paths = [
        TESSERACT_CMD,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for p in candidate_paths:
        if p and os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            HAVE_TESSERACT = True
            break
    if not HAVE_TESSERACT and shutil.which("tesseract"):
        HAVE_TESSERACT = True
except Exception as e:
    logger.info("pytesseract initialization check: %s", e)


def extract_barcodes_from_image(image: Image.Image) -> list[str]:
    """
    Extract 1D/2D barcodes (such as ISBN-13 / EAN-13) from a PIL Image.
    Uses multi-orientation and contrast enhancements to handle angled / poorly lit photos.
    """
    barcodes_found: list[str] = []

    # 1. Try original image
    results = zxingcpp.read_barcodes(image)
    for r in results:
        if r.text:
            barcodes_found.append(r.text.strip())

    if barcodes_found:
        return list(dict.fromkeys(barcodes_found))

    # 2. Try grayscale & enhanced contrast
    gray = ImageOps.grayscale(image)
    enhancer = ImageEnhance.Contrast(gray)
    high_contrast = enhancer.enhance(2.0)
    results = zxingcpp.read_barcodes(high_contrast)
    for r in results:
        if r.text:
            barcodes_found.append(r.text.strip())

    if barcodes_found:
        return list(dict.fromkeys(barcodes_found))

    # 3. Try 90, 180, 270 degree rotations for angled camera captures
    for angle in [90, 180, 270]:
        rotated = image.rotate(angle, expand=True)
        results = zxingcpp.read_barcodes(rotated)
        for r in results:
            if r.text:
                barcodes_found.append(r.text.strip())
        if barcodes_found:
            break

    return list(dict.fromkeys(barcodes_found))


def clean_ocr_lines(raw_text: str) -> list[str]:
    """
    Clean raw OCR text lines, filtering out noise, symbols, and single-character artifacts.
    """
    lines = []
    for line in raw_text.splitlines():
        # Remove unwanted control characters or pure punctuation
        cleaned = re.sub(r"[^\w\s\u0D00-\u0D7F.,'-]", " ", line).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        # Keep lines with at least 3 alphanumeric characters
        if len(cleaned) >= 3 and any(c.isalnum() for c in cleaned):
            lines.append(cleaned)
    return lines


def extract_text_from_image(image: Image.Image) -> dict[str, Any]:
    """
    Extract visible text from book cover using conventional OCR (Tesseract).
    Returns clean text lines and availability status.
    """
    if not HAVE_TESSERACT:
        return {
            "available": False,
            "lines": [],
            "raw_text": "",
            "message": "Conventional OCR engine (Tesseract) is not configured on this host. Barcode scanning and online metadata search are active.",
        }

    try:
        # Preprocessing: convert to grayscale and modest contrast enhancement
        gray = ImageOps.grayscale(image)
        # Resize large phone camera pictures to max 1600px width/height for fast OCR
        max_dim = 1600
        if max(gray.size) > max_dim:
            gray.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        # Try Malayalam + English if configured, else standard
        lang_str = "eng"
        try:
            available_langs = pytesseract.get_languages()
            if "mal" in available_langs:
                lang_str = "mal+eng"
        except Exception:
            pass

        raw_text = pytesseract.image_to_string(gray, lang=lang_str)
        cleaned_lines = clean_ocr_lines(raw_text)

        return {
            "available": True,
            "lines": cleaned_lines,
            "raw_text": raw_text.strip(),
            "message": "OCR text extraction completed.",
        }
    except Exception as exc:
        logger.warning("OCR text extraction failed: %s", exc)
        return {
            "available": False,
            "lines": [],
            "raw_text": "",
            "message": f"OCR processing error: {exc}",
        }


async def process_recognition_image(
    image_bytes: bytes,
    metadata_lookup: MetadataLookup | None = None,
) -> dict[str, Any]:
    """
    Full recognition pipeline:
    1. Reads image into memory.
    2. Scans for barcode (ISBN).
    3. Runs OCR to extract text lines.
    4. Automatically queries metadata providers for matches.
    5. Returns candidate results for librarian selection.
    6. Discards image data.
    """
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        return {
            "success": False,
            "message": f"Invalid or unreadable image file: {exc}",
            "barcode": None,
            "ocr_lines": [],
            "candidates": [],
        }

    # 1. Barcode scanning
    barcodes = extract_barcodes_from_image(image)
    detected_barcode = None
    candidates: list[dict[str, Any]] = []
    lookup = metadata_lookup or search_metadata

    # Check if any barcode is ISBN-like (e.g. 10 or 13 digits starting with 978/979)
    for b in barcodes:
        clean = clean_isbn(b)
        if len(clean) in (10, 13):
            detected_barcode = clean
            break
    if not detected_barcode and barcodes:
        detected_barcode = barcodes[0]

    # If barcode found, query metadata directly
    if detected_barcode:
        candidates = await lookup(isbn=detected_barcode)

    # 2. Conventional OCR text extraction
    ocr_result = extract_text_from_image(image)
    ocr_lines = ocr_result.get("lines", [])

    # If no barcode candidates found, search metadata using extracted OCR text
    if not candidates and ocr_lines:
        # Heuristic: the top prominent lines are usually Title and Author
        search_query = " ".join(ocr_lines[:3])
        candidates = await lookup(query=search_query)

    message = ""
    if detected_barcode and candidates:
        message = f"Found barcode {detected_barcode} with {len(candidates)} matching metadata record(s)."
    elif detected_barcode:
        message = f"Found barcode {detected_barcode}. No online metadata found; please enter details manually."
    elif ocr_lines and candidates:
        message = f"Extracted cover text with {len(candidates)} matching metadata candidate(s)."
    elif ocr_lines:
        message = "Cover text extracted, but no exact online metadata match found. You can copy the extracted text."
    else:
        message = "No barcode or readable cover text detected. You can search by title or author manually."

    return {
        "success": True,
        "message": message,
        "barcode": detected_barcode,
        "ocr_available": ocr_result.get("available", False),
        "ocr_lines": ocr_lines,
        "candidates": candidates,
    }
