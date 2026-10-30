"""
Portfolio router — Phase 1 scope.

Endpoints implemented here:
  GET  /api/portfolio/companies          — list portfolio companies with latest price
  POST /api/portfolio/companies          — add a company
  PUT  /api/portfolio/companies/{ticker} — update alert thresholds
  DELETE /api/portfolio/companies/{ticker} — soft-delete (is_active = False)
  GET  /api/portfolio/prices             — latest EOD snapshot for every active company
  POST /api/portfolio/prices/refresh     — pull yfinance + run alert checks (async-friendly)
  GET  /api/portfolio/alerts             — unseen price/volume alerts

Phase 2 (announcements per company) is left as stubs with clear TODO markers.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import PortfolioCompany, PriceSnapshot, PriceAlert
from services.yfinance_service import fetch_and_store_prices

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CompanyOut(BaseModel):
    id: int
    ticker: str
    name: str
    exchange: str
    sector: str
    is_active: bool
    vol_alert_mult: float
    price_alert_pct: float

    model_config = {"from_attributes": True}


class CompanyCreate(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=120)
    exchange: str = Field(..., pattern="^(NSE|BSE)$")
    sector: str = Field(..., min_length=1, max_length=60)
    vol_alert_mult: float = Field(2.0, gt=0)
    price_alert_pct: float = Field(5.0, gt=0)


class CompanyUpdate(BaseModel):
    vol_alert_mult: float | None = Field(None, gt=0)
    price_alert_pct: float | None = Field(None, gt=0)
    is_active: bool | None = None


class SnapshotOut(BaseModel):
    ticker: str
    name: str
    sector: str
    date: date | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    avg_vol_20d: float | None
    pct_change: float | None
    # Data-quality flag — tells the frontend exactly what kind of data this is
    data_source: str = "yfinance_eod"  # always real EOD data
    data_status: str  # 'ok' | 'no_data' | 'stale'

    model_config = {"from_attributes": True}


class AlertOut(BaseModel):
    id: int
    ticker: str
    date: date
    alert_type: str
    value: float
    threshold: float
    seen: bool

    model_config = {"from_attributes": True}


class RefreshResult(BaseModel):
    success: list[str]
    no_data: list[str]
    alerts_generated: int
    snapshots_upserted: int
    message: str


# ---------------------------------------------------------------------------
# GET /api/portfolio/companies
# ---------------------------------------------------------------------------

@router.get("/companies", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)) -> list[CompanyOut]:
    """Return all portfolio companies (active and inactive)."""
    return db.query(PortfolioCompany).order_by(PortfolioCompany.ticker).all()


# ---------------------------------------------------------------------------
# POST /api/portfolio/companies
# ---------------------------------------------------------------------------

@router.post("/companies", response_model=CompanyOut, status_code=201)
def add_company(body: CompanyCreate, db: Session = Depends(get_db)) -> CompanyOut:
    """Add a new company to the portfolio."""
    existing = db.query(PortfolioCompany).filter(
        PortfolioCompany.ticker == body.ticker
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"{body.ticker} is already in the portfolio.")

    company = PortfolioCompany(**body.model_dump())
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


# ---------------------------------------------------------------------------
# PUT /api/portfolio/companies/{ticker}
# ---------------------------------------------------------------------------

@router.put("/companies/{ticker}", response_model=CompanyOut)
def update_company(
    ticker: str,
    body: CompanyUpdate,
    db: Session = Depends(get_db),
) -> CompanyOut:
    """Update alert thresholds or active status for a company."""
    company = _get_company_or_404(db, ticker)
    update_data = body.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(company, key, value)
    db.commit()
    db.refresh(company)
    return company


# ---------------------------------------------------------------------------
# DELETE /api/portfolio/companies/{ticker}
# ---------------------------------------------------------------------------

@router.delete("/companies/{ticker}", status_code=204)
def remove_company(ticker: str, db: Session = Depends(get_db)) -> None:
    """Soft-delete: sets is_active = False. Does not purge price history."""
    company = _get_company_or_404(db, ticker)
    company.is_active = False
    db.commit()


# ---------------------------------------------------------------------------
# GET /api/portfolio/prices
# ---------------------------------------------------------------------------

@router.get("/prices", response_model=list[SnapshotOut])
def get_prices(db: Session = Depends(get_db)) -> list[SnapshotOut]:
    """
    Return the latest EOD snapshot for every active portfolio company.

    For each company:
      - 'ok'      — latest snapshot found
      - 'no_data' — yfinance has never returned data for this ticker
      - 'stale'   — latest snapshot is >5 calendar days old (weekend/holiday gap is fine;
                    >5 days suggests the refresh hasn't run yet)
    """
    companies = (
        db.query(PortfolioCompany)
        .filter(PortfolioCompany.is_active == True)
        .order_by(PortfolioCompany.ticker)
        .all()
    )

    today = date.today()
    result: list[SnapshotOut] = []

    for company in companies:
        # Get the latest snapshot for this ticker
        snap: PriceSnapshot | None = (
            db.query(PriceSnapshot)
            .filter(PriceSnapshot.ticker == company.ticker)
            .order_by(PriceSnapshot.date.desc())
            .first()
        )

        if snap is None:
            result.append(SnapshotOut(
                ticker=company.ticker,
                name=company.name,
                sector=company.sector,
                date=None,
                open=None, high=None, low=None, close=None,
                volume=None, avg_vol_20d=None, pct_change=None,
                data_status="no_data",
            ))
        else:
            days_old = (today - snap.date).days
            status = "ok" if days_old <= 5 else "stale"
            result.append(SnapshotOut(
                ticker=company.ticker,
                name=company.name,
                sector=company.sector,
                date=snap.date,
                open=snap.open,
                high=snap.high,
                low=snap.low,
                close=snap.close,
                volume=snap.volume,
                avg_vol_20d=snap.avg_vol_20d,
                pct_change=snap.pct_change,
                data_status=status,
            ))

    return result


# ---------------------------------------------------------------------------
# POST /api/portfolio/prices/refresh
# ---------------------------------------------------------------------------

@router.post("/prices/refresh", response_model=RefreshResult)
def refresh_prices(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> RefreshResult:
    """
    Trigger a synchronous yfinance fetch + alert evaluation for all active companies.

    Runs in the request cycle (not backgrounded) so the caller gets the result immediately.
    For a production setup this would move to a background task or scheduled job.
    """
    logger.info("Manual price refresh triggered via API.")
    summary = fetch_and_store_prices(db)
    return RefreshResult(
        **summary,
        message=(
            f"Fetched data for {len(summary['success'])} tickers. "
            f"No data: {summary['no_data'] or 'none'}. "
            f"{summary['alerts_generated']} alert(s) generated."
        ),
    )


# ---------------------------------------------------------------------------
# GET /api/portfolio/alerts
# ---------------------------------------------------------------------------

@router.get("/alerts", response_model=list[AlertOut])
def get_alerts(
    unseen_only: bool = True,
    db: Session = Depends(get_db),
) -> list[AlertOut]:
    """Return price/volume alerts. Set unseen_only=false to see all."""
    query = db.query(PriceAlert).order_by(PriceAlert.created_at.desc())
    if unseen_only:
        query = query.filter(PriceAlert.seen == False)
    return query.limit(100).all()


@router.patch("/alerts/{alert_id}/seen", response_model=AlertOut)
def mark_alert_seen(alert_id: int, db: Session = Depends(get_db)) -> AlertOut:
    """Mark a single alert as seen."""
    alert = db.query(PriceAlert).filter(PriceAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    alert.seen = True
    db.commit()
    db.refresh(alert)
    return alert


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_company_or_404(db: Session, ticker: str) -> PortfolioCompany:
    company = db.query(PortfolioCompany).filter(
        PortfolioCompany.ticker == ticker
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found in portfolio.")
    return company
