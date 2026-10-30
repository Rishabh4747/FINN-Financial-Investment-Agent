"""
FINN Backend — FastAPI application entry point.

Startup sequence:
  1. Create all DB tables (SQLAlchemy DDL).
  2. Seed the portfolio (idempotent — skips if already seeded).
  3. Mount routers: portfolio (Phase 1), today (Phase 2 stub), research (Phase 3 stub).

CORS is open for local development (localhost:5173 = Vite dev server).
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Logging — configure before any imports that trigger logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure backend/ is on sys.path when running from the project root
# ---------------------------------------------------------------------------
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

# ---------------------------------------------------------------------------
# Internal imports (after path fix)
# ---------------------------------------------------------------------------
from config import get_settings
from db.database import engine, SessionLocal
from db.models import Base
from services.seed_service import seed_portfolio
from routers import portfolio, today, research

settings = get_settings()


# ---------------------------------------------------------------------------
# Lifespan — startup + shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("FINN backend starting up…")

    # Create all tables that don't already exist
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified / created.")

    # Seed portfolio (no-op if already seeded)
    with SessionLocal() as db:
        inserted = seed_portfolio(db)
        if inserted:
            logger.info(f"Portfolio seeded with {inserted} companies.")

    logger.info("Startup complete. FINN is ready.")
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("FINN backend shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FINN — Financial Investment Agent API",
    description=(
        "Backend for FINN, ENAM Holdings AI Engineer Build Challenge. "
        "Provides portfolio price data, corporate announcement feed, and research reports."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the Vite dev server and any localhost port during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(portfolio.router)
app.include_router(today.router)
app.include_router(research.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health", tags=["health"])
def health() -> dict:
    """Simple liveness probe — returns server status and phase completion."""
    return {
        "status": "ok",
        "service": "FINN",
        "version": "0.1.0",
        "phases": {
            "1_backend_skeleton": "complete",
            "2_announcements": "stub",
            "3_research": "stub",
            "4_frontend": "not_started",
        },
    }


# ---------------------------------------------------------------------------
# Entry point — python main.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level="info",
    )
