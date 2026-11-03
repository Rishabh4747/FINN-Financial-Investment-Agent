"""
Push router — Phase 4 scope.

Provides endpoints for FINN's Push mode and financial insights:
  - GET   /api/push/digest                 — windowed prioritized digest (default 24h)
  - GET   /api/push/settings               — inspect push & alert threshold settings
  - PUT   /api/push/settings               — update push & alert threshold settings
  - GET   /api/push/alerts                 — unified triggered alerts feed (market + corporate)
  - PATCH /api/push/alerts/{type}/{id}/seen — mark alert as seen/acknowledged
  - POST  /api/push/evaluate               — trigger alert evaluation on demand
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Announcement, AnnouncementAlert, PriceAlert
from services.insights_service import (
    get_or_create_alert_preferences,
    update_alert_preferences,
    evaluate_announcement_alerts,
    generate_push_digest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/push", tags=["push"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class PushSettingsOut(BaseModel):
    digest_window_hours: float
    min_materiality_score: float
    enabled_categories: list[str]
    default_price_alert_pct: float
    default_vol_alert_mult: float
    portfolio_only: bool
    auto_insights: bool

    model_config = {"from_attributes": True}


class PushSettingsUpdate(BaseModel):
    digest_window_hours: Optional[float] = Field(None, ge=1.0, le=168.0, description="Digest window in hours (e.g. 24.0)")
    min_materiality_score: Optional[float] = Field(None, ge=1.0, le=10.0, description="Min materiality score to trigger alert")
    enabled_categories: Optional[list[str]] = Field(None, description="List of categories for push alerts")
    default_price_alert_pct: Optional[float] = Field(None, gt=0, description="±X% price move threshold")
    default_vol_alert_mult: Optional[float] = Field(None, gt=0, description="~X× volume spike multiplier")
    portfolio_only: Optional[bool] = Field(None, description="Whether alerts are restricted to active portfolio")
    auto_insights: Optional[bool] = Field(None, description="Enable automatic first-cut financial insights")


class UnifiedAlertOut(BaseModel):
    id: int
    alert_source: str  # 'market_price' | 'market_volume' | 'corporate_announcement'
    symbol: str
    headline_or_type: str
    value_or_category: str
    threshold_or_materiality: str
    financial_insights: Optional[dict[str, Any]] = None
    seen: bool
    created_at: Optional[str] = None


class DigestResponse(BaseModel):
    digest_window_hours: float
    as_of: str
    summary: dict[str, Any]
    config_applied: dict[str, Any]
    triggered_market_alerts: list[dict[str, Any]]
    prioritized_announcements: list[dict[str, Any]]


class EvaluateResult(BaseModel):
    status: str
    new_announcement_alerts: int
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/digest", response_model=DigestResponse)
def get_digest(
    hours: Optional[float] = Query(None, description="Time window in hours (default from settings, 24h)"),
    min_materiality: Optional[float] = Query(None, description="Min materiality score (default from settings)"),
    portfolio_only: Optional[bool] = Query(None, description="Filter only to portfolio companies"),
    category: Optional[str] = Query(None, description="Optional single category filter"),
    db: Session = Depends(get_db),
) -> DigestResponse:
    """
    Returns FINN's windowed Push Digest.
    Default 24h window; surfaces prioritized corporate filings with first-cut financial insights,
    triggered price/volume alerts, and collapsed routine items.
    """
    digest_data = generate_push_digest(
        db=db,
        hours=hours,
        min_materiality=min_materiality,
        portfolio_only=portfolio_only,
        category=category,
    )
    return DigestResponse(**digest_data)


@router.get("/settings", response_model=PushSettingsOut)
def get_settings(db: Session = Depends(get_db)) -> PushSettingsOut:
    """Returns the current configurable Push and Alert threshold settings."""
    prefs = get_or_create_alert_preferences(db)
    return PushSettingsOut(
        digest_window_hours=prefs.digest_window_hours,
        min_materiality_score=prefs.min_materiality_score,
        enabled_categories=[c.strip() for c in prefs.enabled_categories.split(",") if c.strip()],
        default_price_alert_pct=prefs.default_price_alert_pct,
        default_vol_alert_mult=prefs.default_vol_alert_mult,
        portfolio_only=prefs.portfolio_only,
        auto_insights=prefs.auto_insights,
    )


@router.put("/settings", response_model=PushSettingsOut)
def update_settings(
    payload: PushSettingsUpdate,
    db: Session = Depends(get_db),
) -> PushSettingsOut:
    """Updates user-configurable Push and Alert thresholds."""
    cat_str = ",".join(payload.enabled_categories) if payload.enabled_categories is not None else None
    prefs = update_alert_preferences(
        db=db,
        digest_window_hours=payload.digest_window_hours,
        min_materiality_score=payload.min_materiality_score,
        enabled_categories=cat_str,
        default_price_alert_pct=payload.default_price_alert_pct,
        default_vol_alert_mult=payload.default_vol_alert_mult,
        portfolio_only=payload.portfolio_only,
        auto_insights=payload.auto_insights,
    )
    return PushSettingsOut(
        digest_window_hours=prefs.digest_window_hours,
        min_materiality_score=prefs.min_materiality_score,
        enabled_categories=[c.strip() for c in prefs.enabled_categories.split(",") if c.strip()],
        default_price_alert_pct=prefs.default_price_alert_pct,
        default_vol_alert_mult=prefs.default_vol_alert_mult,
        portfolio_only=prefs.portfolio_only,
        auto_insights=prefs.auto_insights,
    )


@router.get("/alerts", response_model=list[UnifiedAlertOut])
def list_unified_alerts(
    unseen_only: bool = Query(True, description="Filter only to unacknowledged alerts"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[UnifiedAlertOut]:
    """
    Returns a unified feed of market price/volume alerts and corporate announcement alerts.
    """
    results: list[UnifiedAlertOut] = []

    # 1. Market Price Alerts
    price_q = db.query(PriceAlert).order_by(desc(PriceAlert.created_at))
    if unseen_only:
        price_q = price_q.filter(PriceAlert.seen == False)
    price_alerts = price_q.limit(limit).all()

    for pa in price_alerts:
        source_type = "market_price" if pa.alert_type == "price_move" else "market_volume"
        results.append(UnifiedAlertOut(
            id=pa.id,
            alert_source=source_type,
            symbol=pa.ticker,
            headline_or_type=pa.alert_type,
            value_or_category=f"{pa.value:+.2f}%" if pa.alert_type == "price_move" else f"{pa.value:.1f}× avg",
            threshold_or_materiality=f"±{pa.threshold}%" if pa.alert_type == "price_move" else f"{pa.threshold}×",
            financial_insights=None,
            seen=pa.seen,
            created_at=pa.created_at.isoformat() if pa.created_at else None,
        ))

    # 2. Corporate Announcement Alerts
    ann_q = db.query(AnnouncementAlert).order_by(desc(AnnouncementAlert.created_at))
    if unseen_only:
        ann_q = ann_q.filter(AnnouncementAlert.seen == False)
    ann_alerts = ann_q.limit(limit).all()

    for aa in ann_alerts:
        insights = json.loads(aa.financial_insights_json) if aa.financial_insights_json else None
        results.append(UnifiedAlertOut(
            id=aa.id,
            alert_source="corporate_announcement",
            symbol=aa.symbol,
            headline_or_type=aa.headline,
            value_or_category=aa.category,
            threshold_or_materiality=f"{aa.materiality} (score {aa.materiality_score:.1f})",
            financial_insights=insights,
            seen=aa.seen,
            created_at=aa.created_at.isoformat() if aa.created_at else None,
        ))

    # Sort merged list by created_at descending
    results.sort(key=lambda x: x.created_at or "", reverse=True)
    return results[:limit]


@router.patch("/alerts/{alert_type}/{alert_id}/seen", status_code=status.HTTP_200_OK)
def mark_alert_seen(
    alert_type: str,
    alert_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Marks a specific alert (market or corporate announcement) as seen."""
    if alert_type in ("price", "market", "price_move", "volume_spike"):
        alert = db.query(PriceAlert).filter(PriceAlert.id == alert_id).first()
        if not alert:
            raise HTTPException(status_code=404, detail="Price alert not found.")
        alert.seen = True
        db.commit()
        return {"status": "ok", "id": alert_id, "alert_type": "market", "seen": True}

    if alert_type in ("announcement", "corporate"):
        alert_ann = db.query(AnnouncementAlert).filter(AnnouncementAlert.id == alert_id).first()
        if not alert_ann:
            raise HTTPException(status_code=404, detail="Announcement alert not found.")
        alert_ann.seen = True
        db.commit()
        return {"status": "ok", "id": alert_id, "alert_type": "announcement", "seen": True}

    raise HTTPException(status_code=400, detail="Invalid alert_type. Use 'market' or 'announcement'.")


@router.post("/evaluate", response_model=EvaluateResult)
def evaluate_alerts(
    hours: float = Query(48.0, description="Hours of announcements to evaluate"),
    db: Session = Depends(get_db),
) -> EvaluateResult:
    """Manually triggers evaluation of announcement alerts across recent filings."""
    cutoff = datetime.now() - timedelta(hours=hours)
    recent_ann = db.query(Announcement).filter(
        (Announcement.filing_datetime >= cutoff) |
        (Announcement.filing_datetime.is_(None) & (Announcement.created_at >= cutoff))
    ).all()

    count = evaluate_announcement_alerts(db, recent_ann)
    return EvaluateResult(
        status="ok",
        new_announcement_alerts=count,
        message=f"Evaluated {len(recent_ann)} announcements; created {count} new alerts.",
    )
