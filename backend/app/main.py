from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin, auth, public, system
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app.services.storage import StorageService


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    StorageService().ensure_directories()
    yield


settings = get_settings()
app = FastAPI(
    title="Webnovel API",
    version="0.1.0",
    description="Copyright-first catalogue, ingestion, reading, and administration API.",
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.environment != "production" else None,
    lifespan=lifespan,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.include_router(system.router)
app.include_router(public.router)
app.include_router(auth.router)
app.include_router(admin.router)
