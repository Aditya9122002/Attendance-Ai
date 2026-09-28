"""AttendanceAI application entry point."""

from fastapi import FastAPI
from pydantic import BaseModel

APP_VERSION = "0.1.0"


class HealthResponse(BaseModel):
    """Response body for the liveness endpoint."""

    status: str
    version: str


app = FastAPI(title="AttendanceAI", version=APP_VERSION)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe: reports that the process is up and serving requests."""
    return HealthResponse(status="ok", version=APP_VERSION)
