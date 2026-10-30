"""
Today router — Phase 2 implementation.

Provides endpoints for the Today dashboard view:
  - GET  /api/today/announcements  — prioritized, filtered corporate announcements with configurable time window (default 24h)
  - POST /api/today/refresh        — trigger live NSE ingestion (or synthetic fixtures)
  - GET  /api/today/categories     — available categories, metadata, and active counts
  - GET  /api/today/summary        — summary stats (counts by materiality, time window)
  - GET  /api/today/alerts         — price/volume alerts for the Today view
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, desc
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Announcement, PortfolioCompany, PriceAlert
from services.nse_service import ingest_announcements
from services.announcement_classifier import CATEGORY_RULES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/today", tags=["today"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class AnnouncementOut(BaseModel):
    id: int
    exchange: str
    symbol: str
    company: Optional[str] = None
    headline: str
    description: Optional[str] = None
    category: Optional[str] = None
    classification_rationale: Optional[str] = None
    classification_confidence: Optional[str] = None
    materiality: Optional[str] = None
    materiality_score: Optional[float] = None
    materiality_rationale: Optional[str] = None
    summary: Optional[str] = None
    filing_dt: Optional[str] = None
    filing_datetime: Optional[datetime] = None
    pdf_url: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RefreshResponse(BaseModel):
    status: str
    fetched: int
    inserted: int
    duplicates_skipped: int
    source: str
    error: Optional[str] = None
    message: str


class CategoryInfo(BaseModel):
    category: str
    materiality: str
    default_score: float
    description: str
    count: int


class TodaySummary(BaseModel):
    window_hours: Optional[float]
    total_announcements: int
    high_materiality: int
    medium_materiality: int
    low_materiality: int
    active_alerts: int
    categories_breakdown: dict[str, int]


class AlertSummaryOut(BaseModel):
    id: int
    ticker: str
    date: Any
    alert_type: str
    value: float
    threshold: float
    seen: bool

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# GET /api/today/announcements
# ---------------------------------------------------------------------------

@router.get("/announcements", response_model=list[AnnouncementOut])
def list_announcements(
    hours: Optional[float] = Query(24.0, description="Time window in hours (default 24h). Pass <= 0 for all."),
    tickers: Optional[str] = Query(None, description="Comma-separated ticker symbols (e.g. RELIANCE,INFY)"),
    categories: Optional[str] = Query(None, description="Comma-separated categories (e.g. results,M&A)"),
    materiality: Optional[str] = Query(None, description="Materiality level: HIGH, MEDIUM, LOW"),
    search: Optional[str] = Query(None, description="Free text search in headline, description, company"),
    portfolio_only: bool = Query(False, description="Filter only to active portfolio tickers"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[AnnouncementOut]:
    """
    Returns prioritized corporate announcements.
    Default ordering surfaces high-materiality events first, followed by recency.
    """
    query = db.query(Announcement)

    # Time window filter (based on filing_datetime or fallback to created_at)
    if hours and hours > 0:
        cutoff = datetime.now() - timedelta(hours=hours)
        query = query.filter(
            or_(
                Announcement.filing_datetime >= cutoff,
                Announcement.filing_datetime.is_(None) & (Announcement.created_at >= cutoff),
            )
        )

    # Portfolio-only filter
    if portfolio_only:
        portfolio_tickers = db.query(PortfolioCompany.ticker).filter(PortfolioCompany.is_active == True).all()
        # Normalize: both 'RELIANCE' and 'RELIANCE.NS'
        allowed_symbols = set()
        for t in portfolio_tickers:
            raw = t[0]
            allowed_symbols.add(raw)
            allowed_symbols.add(raw.replace(".NS", "").replace(".BO", ""))
        query = query.filter(Announcement.symbol.in_(allowed_symbols))

    # Explicit ticker filter
    if tickers:
        ticker_list = [t.strip().upper().replace(".NS", "").replace(".BO", "") for t in tickers.split(",") if t.strip()]
        if ticker_list:
            query = query.filter(Announcement.symbol.in_(ticker_list))

    # Category filter
    if categories:
        cat_list = [c.strip() for c in categories.split(",") if c.strip()]
        if cat_list:
            query = query.filter(Announcement.category.in_(cat_list))

    # Materiality filter
    if materiality:
        query = query.filter(Announcement.materiality == materiality.strip().upper())

    # Text search
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Announcement.headline.ilike(term),
                Announcement.description.ilike(term),
                Announcement.company.ilike(term),
            )
        )

    # Sort: Materiality score descending (highest priority first), then filing recency
    query = query.order_by(
        desc(Announcement.materiality_score),
        desc(Announcement.filing_datetime),
        desc(Announcement.created_at),
    )

    return query.offset(offset).limit(limit).all()


# ---------------------------------------------------------------------------
# POST /api/today/refresh
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=RefreshResponse)
def refresh_announcements(
    use_fixtures: bool = Query(False, description="Load synthetic fixtures for deterministic offline testing"),
    db: Session = Depends(get_db),
) -> RefreshResponse:
    """
    Triggers corporate announcements ingestion from NSE (or test fixtures).
    Performs parsing, classification, materiality scoring, and deduplication.
    """
    logger.info(f"Triggering announcement ingestion (use_fixtures={use_fixtures}).")
    result = ingest_announcements(db=db, use_fixtures=use_fixtures)
    return RefreshResponse(**result)


# ---------------------------------------------------------------------------
# GET /api/today/categories
# ---------------------------------------------------------------------------

@router.get("/categories", response_model=list[CategoryInfo])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryInfo]:
    """
    Returns the supported announcement categories, materiality definitions,
    and current record counts in the database.
    """
    # Count occurrences per category in DB
    counts_raw = (
        db.query(Announcement.category, Announcement.id)
        .all()
    )
    counts: dict[str, int] = {}
    for cat, _ in counts_raw:
        c = cat or "unclassified"
        counts[c] = counts.get(c, 0) + 1

    result: list[CategoryInfo] = []
    seen_categories = set()

    for rule in CATEGORY_RULES:
        seen_categories.add(rule.category)
        result.append(CategoryInfo(
            category=rule.category,
            materiality=rule.materiality,
            default_score=rule.materiality_score,
            description=rule.materiality_rationale,
            count=counts.get(rule.category, 0),
        ))

    # Add unclassified
    result.append(CategoryInfo(
        category="unclassified",
        materiality="LOW",
        default_score=1.5,
        description="Routine compliance paperwork, statutory certificates, or low-relevance filings.",
        count=counts.get("unclassified", 0),
    ))

    return result


# ---------------------------------------------------------------------------
# GET /api/today/summary
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=TodaySummary)
def get_today_summary(
    hours: Optional[float] = Query(24.0, description="Time window in hours"),
    db: Session = Depends(get_db),
) -> TodaySummary:
    """Returns overview counts and category breakdown for the Today dashboard."""
    query = db.query(Announcement)
    if hours and hours > 0:
        cutoff = datetime.now() - timedelta(hours=hours)
        query = query.filter(
            or_(
                Announcement.filing_datetime >= cutoff,
                Announcement.filing_datetime.is_(None) & (Announcement.created_at >= cutoff),
            )
        )

    all_items = query.all()
    high_count = sum(1 for a in all_items if (a.materiality or "").upper() == "HIGH")
    med_count = sum(1 for a in all_items if (a.materiality or "").upper() == "MEDIUM")
    low_count = sum(1 for a in all_items if (a.materiality or "").upper() == "LOW")

    cat_breakdown: dict[str, int] = {}
    for a in all_items:
        cat = a.category or "unclassified"
        cat_breakdown[cat] = cat_breakdown.get(cat, 0) + 1

    # Active unseen alerts
    alerts_count = db.query(PriceAlert).filter(PriceAlert.seen == False).count()

    return TodaySummary(
        window_hours=hours,
        total_announcements=len(all_items),
        high_materiality=high_count,
        medium_materiality=med_count,
        low_materiality=low_count,
        active_alerts=alerts_count,
        categories_breakdown=cat_breakdown,
    )


# ---------------------------------------------------------------------------
# GET /api/today/alerts
# ---------------------------------------------------------------------------

@router.get("/alerts", response_model=list[AlertSummaryOut])
def get_today_alerts(
    unseen_only: bool = True,
    db: Session = Depends(get_db),
) -> list[AlertSummaryOut]:
    """Provides market price/volume alerts for display on the Today dashboard."""
    query = db.query(PriceAlert).order_by(PriceAlert.created_at.desc())
    if unseen_only:
        query = query.filter(PriceAlert.seen == False)
    return query.limit(50).all()
