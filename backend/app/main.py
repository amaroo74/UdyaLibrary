from contextlib import asynccontextmanager
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from .database import Base, engine, run_migrations
from .category_seed import seed_default_categories
from . import models
from .routers.books import router as books_router
from .routers.categories import router as categories_router
from .routers.recognition import router as recognition_router
from .routers.auth import router as auth_router
from .routers.bulk import router as bulk_router
from .routers.sync import router as sync_router
from .routers.auth import provision_initial_admin


def initialize_database() -> None:
    """Initialize database tables, run migrations, provision admin, and seed categories."""
    Base.metadata.create_all(bind=engine)
    run_migrations()
    with Session(engine) as seed_session:
        provision_initial_admin(seed_session)
        seed_default_categories(seed_session)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Udaya Library Dataset API",
    description="Book catalogue API for Udaya Vayanasala, Erattapuzha, Chavakkad, Thrissur.",
    version="0.1.0",
    lifespan=lifespan,
)
REPO_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST_DIR = REPO_DIR / "frontend" / "dist"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:8000,http://127.0.0.1:8000",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in origins],
    allow_origin_regex=r"^http://(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}):8000$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Device-ID"],
)
app.include_router(books_router)
app.include_router(categories_router)
app.include_router(recognition_router)
app.include_router(auth_router)
app.include_router(bulk_router)
app.include_router(sync_router)

@app.get("/api/health")
def health():
    return {"status": "ok", "application": "Udaya Library Dataset System", "version": app.version}


if FRONTEND_ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="frontend-assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend_spa(path: str):
    """Serve the compiled frontend while leaving API routes and docs untouched."""
    if path == "api" or path.startswith("api/") or not FRONTEND_DIST_DIR.is_dir():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Not found")
    requested_file = FRONTEND_DIST_DIR / path
    if requested_file.is_file() and FRONTEND_DIST_DIR in requested_file.resolve().parents:
        return FileResponse(requested_file)
    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="Frontend build not found")
