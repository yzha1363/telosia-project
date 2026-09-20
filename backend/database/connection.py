"""Database connection utilities for the Telosia backend.

This module is responsible for:
- Loading the PostgreSQL connection URL.
- Creating the shared SQLAlchemy database engine.
- Creating database sessions.
- Providing database sessions to FastAPI endpoints.
"""

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

# Load environment variables from the local .env file.
#
# DATABASE_URL is kept in .env instead of being written directly in the
# source code because database credentials/configuration can differ between
# local development, testing, and production environments.
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Stop the application immediately if the database URL has not been
# configured. This produces a clear error instead of a confusing database
# connection failure later.
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set.")


# ---------------------------------------------------------------------------
# SQLAlchemy engine
# ---------------------------------------------------------------------------

# The engine manages connections between the Telosia application and
# PostgreSQL.
#
# pool_pre_ping=True checks that a pooled database connection is still alive
# before SQLAlchemy gives it to the application. This helps prevent errors
# caused by stale or disconnected PostgreSQL connections.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


# ---------------------------------------------------------------------------
# Database session factory
# ---------------------------------------------------------------------------

# SessionLocal is a factory for creating database sessions.
#
# A session represents the application's interaction with the database
# during a unit of work, such as handling one API request.
#
# autocommit=False:
#     Database changes are not committed automatically.
#
# autoflush=False:
#     SQLAlchemy does not automatically flush pending changes before every
#     query. This gives the application more explicit control.
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# ---------------------------------------------------------------------------
# FastAPI database dependency
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """Provide a database session to a FastAPI request.

    FastAPI endpoints can use this function with ``Depends(get_db)``.

    A new SQLAlchemy session is created when the request starts. The session
    is automatically closed when the request finishes, even if an exception
    occurs.

    Yields:
        Session: An active SQLAlchemy session connected to PostgreSQL.
    """

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()