# Udaya Library — Project Rules

## Product
Build a reliable librarian-only book-catalogue dataset system for Udaya Vayanasala, Erattapuzha, Blangad, Chavakkad, Thrissur, Kerala.

## Token and workflow rules
- Read this file and `ANTIGRAVITY_PLAN.md` before each task; do not ask the user to repeat requirements.
- Work on one phase or one clearly bounded task per prompt. Do not attempt the entire roadmap in one run.
- Inspect only files relevant to the task. Do not dump whole files or the whole repository into chat.
- Before editing, summarize the proposed changes in at most 5 bullets. For multi-file or database changes, wait for approval.
- Prefer small diffs and reuse existing working code. Do not rewrite files without a concrete reason.
- Do not repeat web/GitHub research unless a new dependency or unresolved technical decision requires it.
- Keep explanations and test output concise. Report exact commands, pass/fail results, and remaining issues.
- Never claim a feature or test works unless it was actually implemented and executed.

## Architecture guardrails
- Existing scaffold: React + TypeScript + Vite frontend; Python FastAPI backend; SQLAlchemy/SQLite local database.
- Preserve the current stack unless a documented technical reason justifies a change.
- Tauri desktop packaging and PostgreSQL/cloud synchronization are later phases, not prerequisites for improving the local prototype.
- Do not introduce microservices, paid APIs, paid hosting, or unnecessary dependencies.
- Prefer free/open-source components. Check each dependency's maintenance, licence, security advisories, compatibility, and actual need before adding it.
- Do not copy complete GitHub projects. Reuse only suitable, licence-compatible libraries or small well-understood modules, with attribution where required.

## Book data rules
- Persistent book-copy fields only: automatically generated serial number; manually entered unique stock number; title; author name; publisher; category; subcategory; price.
- Do not add edition, ISBN, language, page count, description, cover-image URL, or other persistent catalogue fields unless the user explicitly approves a future change. ISBN may be used transiently for lookup but is not saved in the catalogue.
- Each physical copy is a separate record. Repeated titles and identical bibliographic details are allowed. Stock number must be unique. Serial number must be unique and automatically generated.
- Never block a record merely because its title/author matches another record.
- Missing information may remain blank, must be visibly flagged, and can be completed later. Never invent metadata.
- Price lookup is a suggestion only. Librarian can edit/replace it. Default currency is INR (₹). If no trustworthy price is found, leave it blank for manual entry.
- Book-cover photos are temporary inputs for recognition; do not store cover images in the catalogue.
- For cover recognition use conventional OCR/image processing plus metadata search. Show candidate results and let the librarian choose. Do not build offline AI or confidence-score models.
- Category/subcategory are hierarchical and librarian-managed. Keep AI categorization optional and defer it unless explicitly requested.

## UX and localization
- Minimal, fast interface; prioritize quick registration.
- English and Malayalam interface support. Use Unicode-safe storage and fonts.
- Catalogue supports table and card views; table is the default.
- Search across title, author, publisher, stock number, serial number, category, subcategory and price; support combined filters and sorting.
- Do not store cover art in version 1.

## Security, data integrity, and audit
- Roles planned: administrator, librarian, restricted librarian. Email/password login with optional trusted-device PIN.
- Audit important actions with actor, timestamp, device, action, and before/after values where applicable. Protect audit history from ordinary users.
- Use soft delete/recycle bin and restore controls.
- Validate inputs on frontend and backend. Enforce unique stock number and serial number at database level.
- Never expose secrets in source control. Use environment variables and `.env.example`.
- Backups must be verified before restore. Do not risk the user's only copy of library data.

## Testing and delivery
- Add/update tests for every feature and migration.
- Run relevant backend tests, frontend typecheck/build, and integration checks after changes.
- Do not proceed to the next phase while a regression or failing test remains unexplained.
- Update README and this plan when architecture or behavior changes.
- Before any destructive database operation, create/verify a backup and ask for approval.
