"""Main entry point for the Telosia FastAPI backend.

This module creates the FastAPI application, registers feature routers,
and defines application-level endpoints such as the root endpoint and
health check.
"""

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.routes.chat import router as chat_router
from app.routes.injury_insight import router as injury_insight_router
from app.routes.occupations import router as occupations_router
from app.routes.sources import router as sources_router
from database.connection import get_db


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Telosia API",
    description="Backend API for Telosia. Map the risk. Move with purpose.",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

# The frontend runs on a different origin (Vite's dev server on
# localhost:5173, and a separately deployed origin once the frontend
# itself is deployed), so the browser blocks its requests to this API
# unless we explicitly allow those origins here.
#
# CORS_ALLOWED_ORIGINS lets the deployed origin be added without a code
# change once the frontend has one - see .env.example.
default_origins = "http://localhost:5173,http://127.0.0.1:5173"
allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", default_origins).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Feature routers
# ---------------------------------------------------------------------------

# /api/v1: the frontend's API_REQUIREMENTS.md expects this prefix. Nothing
# currently depends on the old unprefixed /occupations/search path (the
# frontend isn't calling this API yet - still on local mock data), so this
# is a safe time to adopt it consistently rather than having some routes
# prefixed and some not.
app.include_router(occupations_router, prefix="/api/v1")
app.include_router(injury_insight_router, prefix="/api/v1")
app.include_router(sources_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    """Return basic information about the API.

    This endpoint provides a simple confirmation that the Telosia backend
    application is running.

    Returns:
        dict: Basic API status information.
    """

    return {
        "message": "Telosia API is running"
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Check the health of the API and PostgreSQL database.

    A lightweight SQL query is executed against PostgreSQL. If the query
    succeeds, both the FastAPI application and database connection are
    functioning.

    Args:
        db: SQLAlchemy database session supplied by FastAPI.

    Returns:
        dict: Health status of the API and database.
    """

    db.execute(text("SELECT 1"))

    return {
        "status": "healthy",
        "api": "connected",
        "database": "connected",
    }
