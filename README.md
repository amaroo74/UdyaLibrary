# Udaya Library Dataset System

Initial development scaffold for Udaya Vayanasala, Erattapuzha, Blangad, Chavakkad, Thrissur.

## Phase 1 scope

Implemented in this scaffold:
- FastAPI backend with SQLite storage.
- React + TypeScript + Vite responsive interface.
- Add, list, search, edit and soft-delete book-copy records.
- Automatically generated serial numbers (`UDY-000001`, etc.).
- Manually entered, unique stock numbers.
- Repeated book titles are allowed; every physical copy is a separate record.
- Missing metadata is preserved and flagged for later completion.
- Basic audit log entries for book creation, edits and deletion.
- English and Malayalam interface labels, including category and subcategory labels.
- Idempotent two-level category seed with 12 main categories and 59 subcategories.

Not implemented yet (planned phases): front-cover OCR, Excel/CSV/PDF export, full audit viewer/recycle-bin restore, cloud PostgreSQL sync, PWA/Tauri packaging.

## Requirements

- Windows 11 or Windows 10
- Python 3.11 or later
- Node.js 20 or later and npm

## Start on Windows PowerShell

### 1. Backend

```powershell
cd .\backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Before starting the backend, copy `.env.example` to `.env` inside `backend/`. The application loads that exact `backend/.env` file on startup without overriding values already supplied by the process environment. Set a fresh `JWT_SECRET_KEY` on every installation; set the three `INITIAL_ADMIN_*` values only for the first startup of an empty database, then remove `INITIAL_ADMIN_PASSWORD`.

The API documentation will be available at `http://127.0.0.1:8000/docs`.

### 2. Frontend (open a second PowerShell window)

```powershell
cd .\frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Database

The SQLite database is created at `backend/data/udaya_library.db` on first start. Backend startup seeds the approved category tree idempotently; it never renames or deletes existing categories or rewrites book classifications. Back up this file before migrations or other data changes. The verified category-expansion backup is `backend/data/udaya_library.db.backup-20261116-231523`.

## Notes

This is an early development build, not yet suitable for live multi-device library use. Do not enter the library's only copy of important records until backup/restore, authentication, and synchronization have been completed and tested.
