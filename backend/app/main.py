import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import auth, dashboard, documents, duplicates, exports, invoices, organizations, reconciliation, transactions
from app.core.config import get_settings
from app.core.errors import install_error_handlers


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Development convenience only. Production uses `alembic upgrade head`.
    s = get_settings()
    if s.environment != "production" and s.auto_create_tables:
        from app import models  # noqa: F401
        from app.db import session as dbs
        from app.db.base import Base
        Base.metadata.create_all(dbs.engine)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    s.validate_for_production()
    app = FastAPI(lifespan=lifespan, title=s.app_name, version="1.0.0", description="Invoice OCR, expense reconciliation and accounting exports.")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                       allow_methods=["*"], allow_headers=["*"], allow_credentials=False)
    install_error_handlers(app)
    for r in (auth.router, organizations.router, documents.router, invoices.router, transactions.router,
              reconciliation.router, duplicates.router, exports.router, dashboard.router):
        app.include_router(r, prefix="/api/v1")

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    if s.static_dir and os.path.isdir(s.static_dir):
        app.mount("/", StaticFiles(directory=s.static_dir, html=True), name="static")
    return app


app = create_app()
