# Udaya Library — Antigravity Build Plan

## Project status and truth
The current ZIP is an early scaffold, not a finished app. It contains a React + TypeScript + Vite frontend and a Python FastAPI + SQLite backend. Current scope includes basic add/list/search/edit/soft-delete, generated serial numbers, manually entered unique stock numbers, missing-field flags, and basic audit events. The README is the source of truth for what is currently implemented. Verify every feature by inspecting code and running it; do not trust earlier chat claims without tests.

## Product goal
A minimal, bilingual (English/Malayalam), librarian-only system for Udaya Vayanasala, Erattapuzha, Blangad, Chavakkad, Thrissur. Register each physical book copy in under one minute where metadata is available.

## Persistent catalogue fields
1. Serial number — generated automatically and unique.
2. Stock number — entered manually and unique.
3. Book title — retrieved automatically where possible; editable.
4. Author name — retrieved automatically where possible; editable.
5. Publisher — retrieved automatically where possible; editable.
6. Category — selected/confirmed by librarian; hierarchical.
7. Subcategory — selected/confirmed by librarian.
8. Price — online suggestion where available; librarian confirms/edits; INR default.

Do not add Edition or ISBN as saved catalogue fields. ISBN can be entered/scanned and used temporarily for lookup, but do not persist it in the catalogue. Same title/author can appear many times: every physical copy is a separate record with its own stock number and serial number. Do not block matching titles. Missing metadata stays blank, is highlighted, and can be completed later. Never invent data.

## Agreed product requirements
- Input methods: ISBN typing, barcode scanning, title/author search, and front-cover photo recognition.
- Cover recognition: temporary photo; OCR/image processing extracts visible text; search providers; show candidate matches; librarian chooses. No AI confidence score and no custom offline AI model.
- Metadata providers: multiple-source fallback, initially investigate Google Books and Open Library plus reputable ISBN sources. Respect API terms, rate limits, attribution and availability. Do not scrape sites or assume price availability.
- Price: suggested price only; manual override; blank if unavailable. Use INR by default.
- Categories: librarian-managed two-level hierarchy with the approved 12-category seed, Malayalam labels, and conservative rule-based suggestions; no custom AI categorizer.
- Offline: local operation and queued changes; cached data where practical. Online lookup requires internet. Do not claim offline OCR/model capability unless implemented and tested.
- Devices: intended for one library and multiple devices over the internet. Cloud sync is a later phase after local data integrity and authentication are stable. Later add local-Wi-Fi sync and multi-library support.
- Users: administrator, librarian, restricted librarian. Email/password with optional trusted-device PIN.
- Catalogue: table and card views; table default.
- Search: title, author, publisher, stock number, serial number, category, subcategory and price; combined filters and sorting.
- Activity: audit actor, date/time, device, action and exact before/after changes; recycle bin and restore.
- Bulk: individual registration, Excel/CSV import, batch scanning.
- Export: XLSX, CSV, PDF; complete backup/restore.
- Language: English and Malayalam.
- No cover-image storage in version 1.
- Budget: ₹0 recurring software/API/hosting budget. Prefer free/open-source tools; local-first operation must not depend on paid hosting.
- Capacity target: design for at least 100,000 records with indexing and pagination.
- UI: modern minimal now; keep components modular for later redesign.

## Architecture direction
- Keep current React + TypeScript + Vite and FastAPI + SQLite scaffold initially.
- Add Tauri packaging only after the web/local application is stable.
- Plan PostgreSQL/cloud synchronization as a later milestone. Decide local web/mobile persistence and sync protocol explicitly before implementation; do not bolt on a speculative sync plugin.
- Mobile use can begin with responsive web/PWA. Native mobile packaging is a separate future decision.
- Avoid unnecessary AI models. OCR should use a maintained conventional OCR library; compare options before choosing.

## Phased implementation
### Phase 0 — Audit and baseline
Inspect the existing repo, dependencies, README, database schema, API routes, frontend screens and tests. Run backend install/start/tests and frontend install/typecheck/build. Report actual results. Fix only critical baseline defects. Create a Git baseline commit before feature work. Do not rewrite the scaffold.

### Phase 1 — Data model and core catalogue
Confirm only the eight persistent fields above. Enforce unique serial and stock numbers, allow repeated book details, implement robust validation, missing-field status, pagination, search, edit, soft-delete and restore. Add tests and migration/backup safety.

### Phase 2 — Categories and catalogue UX
Category/subcategory management, combined search/filter/sort, table/card view, bulk-friendly form UX, keyboard shortcuts if useful. English/Malayalam localization foundation.
The approved category seed is idempotent and preserves legacy category rows and book classifications.

### Phase 3 — Online metadata lookup
Provider adapter interface; implement and test Google Books/Open Library lookup. Search by ISBN and title/author. Normalize provider responses into the approved fields only. Show multiple candidates for librarian selection. Handle timeouts, rate limits, no results and conflicting data. Do not scrape or persist ISBN unless user approves.

### Phase 4 — Camera and barcode recognition
Barcode scanning and front-cover photo capture/upload. OCR extracts title/author text; query metadata providers; librarian selects candidate. Process temporary photos in memory/temp storage and delete them after use. Test poor lighting, angled covers, Malayalam/English text and unsupported books.

### Phase 5 — Price handling
Display price as an optional suggested value with source and retrieval date where feasible. Librarian accepts/edits/clears it. Never imply a suggested online retail price is the library's purchase price. No trustworthy result means blank/manual entry.

### Phase 6 — Accounts and audit
Secure email/password auth, optional device PIN, administrator/librarian/restricted roles, server-side authorization, session handling, audit history with before/after values, recycle bin/restore. Security tests.

### Phase 7 — Bulk import/export and backup
XLSX/CSV import with column mapping, preview, validation and error report; batch scanning queue; XLSX/CSV/PDF exports; verified backup/restore. Test malformed files and duplicate stock numbers.

### Phase 8 — Offline-first and sync
Define and document sync protocol, device identity, change queue, idempotency, conflict rules and recovery. Local offline writes; cloud PostgreSQL when hosting is available. Never overwrite conflicting edits silently. Test disconnections and repeated sync. Free hosting is not guaranteed; keep local-only mode fully usable.

### Phase 9 — Packaging and release
Tauri desktop build; responsive mobile browser/PWA; Malayalam polish; accessibility; performance at 100k records; security review; install guide; user manual; test report; release backup/restore verification.

## How to work in Antigravity efficiently
- Keep `AGENTS.md` and this plan in the project root; treat them as persistent context.
- Start in Plan mode for Phase 0. Ask for a concise audit and test report only; no broad refactor.
- Use one task per prompt and one phase at a time. Ask for plan before multi-file/database changes.
- Use the light/fast model for routine edits and tests; reserve stronger reasoning for schema, sync, security and architecture decisions.
- Do not run parallel agents on the same files. Delegate only independent research/review tasks if needed.
- Ask for concise summaries and diffs, not full-file dumps.
- After each task, run tests/build, inspect changed files, and commit a working checkpoint.
- Search GitHub only for a specific missing capability. Use multiple keyword queries, then inspect source, last commit, issues, dependency health, licence and security before adoption. No repository is trusted merely because it appears in search.

## First task to give Antigravity
"Read AGENTS.md and ANTIGRAVITY_PLAN.md. Perform Phase 0 only: audit this existing repository, inspect relevant files, run the available backend/frontend checks, and report (1) what is truly implemented, (2) exact commands and results, (3) defects/blockers, and (4) a small prioritized fix list. Do not add features, change the architecture, rewrite files, install new dependencies, or modify the database yet. Keep the report concise."
