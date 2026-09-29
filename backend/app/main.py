"""AttendanceAI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import get_settings
from app.logging_config import configure_logging

APP_VERSION = "0.1.0"

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Response body for the liveness endpoint."""

    status: str
    version: str


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run startup and shutdown logic around the application's lifetime."""
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.app_env == "production")
    logger.info("app_started", extra={"env": settings.app_env, "version": APP_VERSION})
    yield
    logger.info("app_stopped")


app = FastAPI(title="AttendanceAI", version=APP_VERSION, lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe: reports that the process is up and serving requests."""
    return HealthResponse(status="ok", version=APP_VERSION)
