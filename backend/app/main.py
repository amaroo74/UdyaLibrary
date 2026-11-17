import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

Base.metadata.create_all(bind=engine)
run_migrations()
with Session(engine) as seed_session:
    provision_initial_admin(seed_session)
    seed_default_categories(seed_session)

app = FastAPI(
    title="Udaya Library Dataset API",
    description="Book catalogue API for Udaya Vayanasala, Erattapuzha, Chavakkad, Thrissur.",
    version="0.1.0",
)
origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in origins],
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
