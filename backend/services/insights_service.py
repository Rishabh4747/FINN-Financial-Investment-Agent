"""
Financial Insights & Push Alert Service.

Implements FINN's Push mode and financial insights engine:
  1. Financial Insights Extraction:
     - Quarterly results: First-cut headline numbers (Revenue, EBITDA, PBT, PAT) with YoY/QoQ growth.
     - Management change: Executive role (CFO/CEO/MD), action, name, and background/bio context.
     - Corporate actions (M&A, Fund Raise, Dividend, Capex): Deal value, instruments, yield, capacity.
  2. Configurable Push Alerts:
     - Announcement alert evaluation based on user-configured categories and materiality thresholds.
     - Idempotent deduplication (one alert per announcement).
     - End-of-day price move (±X%) and volume spike (~X×) integration.
  3. Windowed Push Digest:
     - Selectable time window (default 24 hours).
     - Prioritizes high-materiality items; collapses routine administrative filings.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, date as date_type
from typing import Any, Optional

from sqlalchemy import or_, desc
from sqlalchemy.orm import Session

from db.models import (
    Announcement,
    AnnouncementAlert,
    AlertPreference,
    PortfolioCompany,
    PriceAlert,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Financial Insights Extractor
# ---------------------------------------------------------------------------

def extract_financial_insights(
    headline: str,
    description: Optional[str] = None,
    category: Optional[str] = None,
) -> dict[str, Any]:
    """
    Extracts high-signal headline financial metrics, executive bios, and deal values
    from corporate filing text. Deterministic and factual — never invents figures.
    """
    hl = (headline or "").strip()
    desc_txt = (description or "").strip()
    full_text = f"{hl} {desc_txt}"
    cat = (category or "").lower()

    # ── Quarterly Results ──────────────────────────────────────────────────
    if cat == "results" or "financial results" in full_text.lower():
        metrics: dict[str, Any] = {}
        highlights: list[str] = []

        # Revenue / Sales / Top-line
        rev_match = re.search(
            r"(?:revenue|turnover|total income|sales)\s*(?:of|at|reached|was|is)?\s*(?:₹|rs\.?|inr)?\s*([0-9,]+(?:\.[0-9]+)?)\s*(crore|cr|lakh|bn|billion|m|million)?",
            full_text,
            re.IGNORECASE,
        )
        if rev_match:
            unit = rev_match.group(2) or "Cr"
            metrics["revenue"] = f"₹{rev_match.group(1)} {unit}".strip()
            highlights.append(f"Revenue {metrics['revenue']}")

        # EBITDA / Operating Profit
        ebitda_match = re.search(
            r"(?:ebitda|operating profit)\s*(?:of|at|was|is)?\s*(?:₹|rs\.?|inr)?\s*([0-9,]+(?:\.[0-9]+)?)\s*(crore|cr|lakh|bn|billion|m|million)?",
            full_text,
            re.IGNORECASE,
        )
        if ebitda_match:
            unit = ebitda_match.group(2) or "Cr"
            metrics["ebitda"] = f"₹{ebitda_match.group(1)} {unit}".strip()
            highlights.append(f"EBITDA {metrics['ebitda']}")

        # PBT (Profit Before Tax)
        pbt_match = re.search(
            r"(?:pbt|profit before tax)\s*(?:of|at|was|is|reached|stood at)?\s*(?:₹|rs\.?|inr)?\s*([0-9,]+(?:\.[0-9]+)?)\s*(crore|cr|lakh|bn|billion|m|million)?",
            full_text,
            re.IGNORECASE,
        )
        if pbt_match:
            unit = pbt_match.group(2) or "Cr"
            metrics["pbt"] = f"₹{pbt_match.group(1)} {unit}".strip()
            highlights.append(f"PBT {metrics['pbt']}")

        # PAT / Net Profit
        pat_match = re.search(
            r"(?:pat|net profit|profit after tax)\s*(?:\([a-z\s]+\))?\s*(?:of|at|was|is|reached|stood at)?\s*(?:₹|rs\.?|inr)?\s*([0-9,]+(?:\.[0-9]+)?)\s*(crore|cr|lakh|bn|billion|m|million)?",
            full_text,
            re.IGNORECASE,
        )
        if pat_match:
            unit = pat_match.group(2) or "Cr"
            metrics["pat"] = f"₹{pat_match.group(1)} {unit}".strip()
            highlights.append(f"PAT {metrics['pat']}")

        # YoY / QoQ Growth Rates
        growth_matches = re.findall(
            r"([+-]?[0-9]+(?:\.[0-9]+)?%)\s*(yoy|qoq|year-on-year|quarter-on-quarter)",
            full_text,
            re.IGNORECASE,
        )
        growth_dict: dict[str, str] = {}
        for val, period in growth_matches:
            k = "yoy" if "y" in period.lower() else "qoq"
            if k not in growth_dict:
                growth_dict[k] = val
                highlights.append(f"{val} {k.upper()}")

        # Standalone vs Consolidated scope
        scope = "Consolidated & Standalone" if "consolidated" in full_text.lower() and "standalone" in full_text.lower() else (
            "Consolidated" if "consolidated" in full_text.lower() else "Standalone" if "standalone" in full_text.lower() else "Results"
        )

        insight_summary = (
            f"{scope} headline metrics: {', '.join(highlights)}."
            if highlights
            else f"{scope} financial results approved by the Board."
        )

        return {
            "insight_type": "quarterly_results",
            "scope": scope,
            "headline_metrics": metrics,
            "growth": growth_dict,
            "insight_summary": insight_summary,
        }

    # ── Management Change ──────────────────────────────────────────────────
    if cat == "management_change" or any(w in full_text.lower() for w in ["cfo", "ceo", "managing director", "resignation", "appointment"]):
        role_match = re.search(
            r"\b(chief financial officer|cfo|chief executive officer|ceo|managing director|md|executive director|independent director|whole-time director|company secretary)\b",
            full_text,
            re.IGNORECASE,
        )
        role = role_match.group(0).upper() if role_match else "Key Executive"
        if role.lower() in ("chief financial officer", "cfo"):
            role = "CFO"
        elif role.lower() in ("chief executive officer", "ceo"):
            role = "CEO"
        elif role.lower() in ("managing director", "md"):
            role = "MD"

        # Action: Resignation vs Appointment
        action = "Resignation" if re.search(r"\b(resignation|resigned|cessation|stepping down|stepped down)\b", full_text, re.IGNORECASE) else "Appointment"

        # Executive Name extraction - prioritize formal honorifics
        name = None
        honorific_match = re.search(r"(?:mr\.?|ms\.?|dr\.?|mrs\.?)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})", full_text, re.IGNORECASE)
        if honorific_match:
            name = honorific_match.group(1).strip()
        else:
            name_match = re.search(
                r"(?:resignation|appointment|cessation)\s+of\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})(?:,|\sas|\swith|\sfrom|\son|\sfor|\.|$)",
                full_text,
                re.IGNORECASE,
            )
            if name_match and not any(w in name_match.group(1).lower() for w in ["cfo", "ceo", "md", "director", "managing"]):
                name = name_match.group(1).strip()

        if not name:
            name = "Key Executive"

        # Incoming Bio / Background extraction
        bio_context = None
        bio_match = re.search(
            r"((?:[A-Za-z\s]+)?(?:has over|brings over|with over|experience of|chartered accountant|iim|iit|prior to|previously served|career spanning)[^.]+?\.)",
            full_text,
            re.IGNORECASE,
        )
        if bio_match:
            bio_context = " ".join(bio_match.group(1).split()).strip()

        insight_summary = f"{action} of {role} ({name})."
        if bio_context:
            insight_summary += f" Background: {bio_context}"

        return {
            "insight_type": "management_change",
            "role": role,
            "action": action,
            "executive_name": name,
            "background_bio": bio_context,
            "insight_summary": insight_summary,
        }

    # ── M&A / Acquisitions ─────────────────────────────────────────────────
    if cat == "m&a" or any(w in full_text.lower() for w in ["acquisition", "merger", "demerger", "stake sale"]):
        # Extract consideration / deal size
        amt_match = re.search(
            r"(?:₹|rs\.?|inr|usd|\$)\s*([0-9,]+(?:\.[0-9]+)?)\s*(crore|cr|billion|bn|million|m)?",
            full_text,
            re.IGNORECASE,
        )
        amount = f"₹{amt_match.group(1)} {amt_match.group(2) or 'Cr'}".strip() if amt_match else None

        # Extract stake %
        stake_match = re.search(r"([0-9]+(?:\.[0-9]+)?%)\s*(?:stake|equity|shares)", full_text, re.IGNORECASE)
        stake = stake_match.group(1) if stake_match else None

        # Extract target
        target_match = re.search(
            r"(?:acquisition of|stake in|acquires)\s+(?:a\s+)?(?:[0-9]+%?\s+stake in\s+)?([A-Z][A-Za-z0-9\s]+?)(?:for|at|with|\.|$|,|The Company)",
            full_text,
            re.IGNORECASE,
        )
        target = target_match.group(1).strip() if target_match else "Target Entity"
        if "The Company" in target:
            target = target.split("The Company")[0].strip()

        details = []
        if target:
            details.append(f"Target: {target[:50]}")
        if stake:
            details.append(f"Stake: {stake}")
        if amount:
            details.append(f"Value: {amount}")

        summary = f"M&A / Acquisition: {'; '.join(details)}." if details else "Corporate acquisition or restructuring disclosure."
        return {
            "insight_type": "ma_deal",
            "target": target[:60] if target else None,
            "stake": stake,
            "deal_value": amount,
            "insight_summary": summary,
        }

    # ── Fund Raising ───────────────────────────────────────────────────────
    if cat == "fund_raise" or any(w in full_text.lower() for w in ["fund raise", "qip", "rights issue", "ncd", "commercial paper", "issuance of debentures"]):
        amt_match = re.search(
            r"(?:₹|rs\.?|inr|up to|worth)?\s*([0-9,]+(?:\.[0-9]+)?)\s*(crore|cr|lakh|billion|bn)",
            full_text,
            re.IGNORECASE,
        )
        amount = f"₹{amt_match.group(1)} {amt_match.group(2)}".strip() if amt_match else None

        if re.search(r"\bncds?\b|non-convertible debentures?", full_text, re.IGNORECASE):
            instrument = "NCDs / Non-Convertible Debentures"
        elif re.search(r"\bqip\b|qualified institutions placement", full_text, re.IGNORECASE):
            instrument = "QIP (Qualified Institutions Placement)"
        elif re.search(r"\brights issue\b", full_text, re.IGNORECASE):
            instrument = "Rights Issue"
        elif re.search(r"\bcommercial paper\b", full_text, re.IGNORECASE):
            instrument = "Commercial Paper"
        else:
            instrument = "Securities"

        summary = f"Capital Raise: Authorization/allotment of {instrument}"
        if amount:
            summary += f" totaling {amount}."
        else:
            summary += "."

        return {
            "insight_type": "fund_raise",
            "instrument": instrument,
            "amount": amount,
            "insight_summary": summary,
        }

    # ── Dividend ───────────────────────────────────────────────────────────
    if cat == "dividend" or "dividend" in full_text.lower():
        div_amt = re.search(r"(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:per equity share|per share|/- per share)", full_text, re.IGNORECASE)
        rate = f"₹{div_amt.group(1)} per share" if div_amt else None

        rec_date = re.search(
            r"(?:record date(?: is| has been)?(?: fixed as)?|fixed as)\s*(?:is|on)?\s*([A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            full_text,
            re.IGNORECASE,
        )
        date_str = rec_date.group(1).strip() if rec_date else None

        summary = f"Dividend Declaration: {rate or 'Cash dividend'}"
        if date_str:
            summary += f" (Record Date: {date_str})."
        else:
            summary += "."

        return {
            "insight_type": "dividend",
            "dividend_rate": rate,
            "record_date": date_str[:30] if date_str else None,
            "insight_summary": summary,
        }

    # ── Capex ──────────────────────────────────────────────────────────────
    if cat == "capex" or "capex" in full_text.lower() or "capacity expansion" in full_text.lower():
        amt_match = re.search(
            r"(?:investment of|capex of|outlay of)?\s*(?:₹|rs\.?|inr)?\s*([0-9,]+(?:\.[0-9]+)?)\s*(crore|cr|billion|bn)",
            full_text,
            re.IGNORECASE,
        )
        amount = f"₹{amt_match.group(1)} {amt_match.group(2)}".strip() if amt_match else None

        summary = "Capital Expenditure: Capacity or manufacturing expansion project"
        if amount:
            summary += f" with outlay of {amount}."
        else:
            summary += "."

        return {
            "insight_type": "capex",
            "outlay": amount,
            "insight_summary": summary,
        }

    # ── General Fallback ───────────────────────────────────────────────────
    one_liner = " ".join((desc_txt or hl).split())[:120]
    return {
        "insight_type": "general",
        "insight_summary": f"{cat.title() if cat else 'Disclosure'}: {one_liner}...",
    }


# ---------------------------------------------------------------------------
# 2. Preferences Management
# ---------------------------------------------------------------------------

def get_or_create_alert_preferences(db: Session) -> AlertPreference:
    """Retrieves user alert configuration; initializes singleton if not present."""
    prefs = db.query(AlertPreference).filter(AlertPreference.id == 1).first()
    if not prefs:
        prefs = AlertPreference(
            id=1,
            digest_window_hours=24.0,
            min_materiality_score=7.0,
            enabled_categories="results,M&A,fund_raise,management_change,litigation,capex,dividend",
            default_price_alert_pct=5.0,
            default_vol_alert_mult=2.0,
            portfolio_only=True,
            auto_insights=True,
        )
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


def update_alert_preferences(
    db: Session,
    digest_window_hours: Optional[float] = None,
    min_materiality_score: Optional[float] = None,
    enabled_categories: Optional[str] = None,
    default_price_alert_pct: Optional[float] = None,
    default_vol_alert_mult: Optional[float] = None,
    portfolio_only: Optional[bool] = None,
    auto_insights: Optional[bool] = None,
) -> AlertPreference:
    """Updates user-defined alert thresholds and push criteria."""
    prefs = get_or_create_alert_preferences(db)
    if digest_window_hours is not None:
        prefs.digest_window_hours = max(1.0, float(digest_window_hours))
    if min_materiality_score is not None:
        prefs.min_materiality_score = max(1.0, min(10.0, float(min_materiality_score)))
    if enabled_categories is not None:
        prefs.enabled_categories = enabled_categories.strip()
    if default_price_alert_pct is not None:
        prefs.default_price_alert_pct = max(0.5, float(default_price_alert_pct))
    if default_vol_alert_mult is not None:
        prefs.default_vol_alert_mult = max(1.0, float(default_vol_alert_mult))
    if portfolio_only is not None:
        prefs.portfolio_only = bool(portfolio_only)
    if auto_insights is not None:
        prefs.auto_insights = bool(auto_insights)

    db.commit()
    db.refresh(prefs)
    return prefs


# ---------------------------------------------------------------------------
# 3. Announcement Alert Evaluation
# ---------------------------------------------------------------------------

def evaluate_announcement_alerts(
    db: Session,
    announcements: list[Announcement],
    prefs: Optional[AlertPreference] = None,
) -> int:
    """
    Evaluates corporate announcements against user-defined alert criteria:
      1. Category matches user's enabled alert categories.
      2. Materiality score >= user's configured threshold (e.g. >= 7.0 for HIGH).
      3. Belongs to active portfolio when portfolio_only is enabled.
    Generates an AnnouncementAlert with extracted financial insights.
    Deduplicates to guarantee zero duplicate alerts.
    """
    if not announcements:
        return 0

    if not prefs:
        prefs = get_or_create_alert_preferences(db)

    # Allowed categories
    allowed_categories = {c.strip().lower() for c in prefs.enabled_categories.split(",") if c.strip()}
    min_score = prefs.min_materiality_score

    # Portfolio symbols set
    portfolio_symbols: set[str] = set()
    if prefs.portfolio_only:
        p_comps = db.query(PortfolioCompany.ticker).filter(PortfolioCompany.is_active == True).all()
        for c in p_comps:
            raw = c[0]
            portfolio_symbols.add(raw.upper())
            portfolio_symbols.add(raw.upper().replace(".NS", "").replace(".BO", ""))

    # Find existing alerted announcement IDs to avoid double insertion
    existing_alert_ann_ids = {
        row[0]
        for row in db.query(AnnouncementAlert.announcement_id)
        .filter(AnnouncementAlert.announcement_id.in_([a.id for a in announcements]))
        .all()
    }

    new_alerts_count = 0
    for ann in announcements:
        if ann.id in existing_alert_ann_ids:
            continue

        ann_cat = (ann.category or "unclassified").lower()
        ann_sym = ann.symbol.upper().replace(".NS", "").replace(".BO", "")

        # Check portfolio constraint
        if prefs.portfolio_only and ann_sym not in portfolio_symbols:
            continue

        # Check category and materiality threshold
        score = ann.materiality_score if ann.materiality_score is not None else 1.0
        if ann_cat not in allowed_categories and score < min_score:
            continue

        # Extract insights
        insights = extract_financial_insights(ann.headline, ann.description, ann.category)

        # Create alert row
        alert = AnnouncementAlert(
            symbol=ann.symbol,
            announcement_id=ann.id,
            category=ann.category or "unclassified",
            headline=ann.headline,
            materiality=ann.materiality or "LOW",
            materiality_score=score,
            financial_insights_json=json.dumps(insights),
            seen=False,
            created_at=datetime.now(),
        )
        db.add(alert)
        existing_alert_ann_ids.add(ann.id)
        new_alerts_count += 1

    if new_alerts_count > 0:
        db.commit()
        logger.info(f"Generated {new_alerts_count} new announcement alerts.")

    return new_alerts_count


# ---------------------------------------------------------------------------
# 4. Windowed Push Digest Generator
# ---------------------------------------------------------------------------

def generate_push_digest(
    db: Session,
    hours: Optional[float] = None,
    min_materiality: Optional[float] = None,
    portfolio_only: Optional[bool] = None,
    category: Optional[str] = None,
) -> dict[str, Any]:
    """
    Generates FINN's windowed Push Digest:
      - Default 24 hours (or caller specified).
      - Surfaces prioritized announcements with first-cut financial insights.
      - Collapses routine administrative paperwork into concise counters.
      - Pulls triggered price/volume alerts for portfolio stocks.
    """
    prefs = get_or_create_alert_preferences(db)

    apply_cutoff = (hours is None) or (float(hours) > 0)
    effective_hours = float(hours) if (hours is not None and float(hours) > 0) else prefs.digest_window_hours
    effective_min_score = float(min_materiality) if min_materiality is not None else prefs.min_materiality_score
    effective_portfolio_only = bool(portfolio_only) if portfolio_only is not None else prefs.portfolio_only

    # 1. Fetch announcements in time window
    query = db.query(Announcement)
    if apply_cutoff:
        cutoff = datetime.now() - timedelta(hours=effective_hours)
        query = query.filter(
            or_(
                Announcement.filing_datetime >= cutoff,
                Announcement.filing_datetime.is_(None) & (Announcement.created_at >= cutoff),
            )
        )

    # Portfolio filtering
    portfolio_symbols = set()
    p_comps = db.query(PortfolioCompany.ticker).filter(PortfolioCompany.is_active == True).all()
    for c in p_comps:
        raw = c[0]
        portfolio_symbols.add(raw.upper())
        portfolio_symbols.add(raw.upper().replace(".NS", "").replace(".BO", ""))

    if effective_portfolio_only:
        query = query.filter(Announcement.symbol.in_(portfolio_symbols))

    if category:
        query = query.filter(Announcement.category == category)

    all_announcements = query.order_by(
        desc(Announcement.materiality_score),
        desc(Announcement.filing_datetime),
        desc(Announcement.created_at),
    ).all()

    # Partition into prioritized vs collapsed routine items
    prioritized_items: list[dict[str, Any]] = []
    collapsed_routine_count = 0
    cat_breakdown: dict[str, int] = {}

    for ann in all_announcements:
        c = ann.category or "unclassified"
        cat_breakdown[c] = cat_breakdown.get(c, 0) + 1
        score = ann.materiality_score or 1.0

        # Prioritize if score >= min_score or high-priority category
        if score >= effective_min_score or c in ("results", "M&A", "management_change", "fund_raise"):
            insights = extract_financial_insights(ann.headline, ann.description, ann.category)
            prioritized_items.append({
                "id": ann.id,
                "symbol": ann.symbol,
                "company": ann.company or ann.symbol,
                "category": ann.category,
                "headline": ann.headline,
                "summary": ann.summary,
                "materiality": ann.materiality,
                "materiality_score": score,
                "materiality_rationale": ann.materiality_rationale,
                "filing_datetime": ann.filing_datetime.isoformat() if ann.filing_datetime else None,
                "pdf_url": ann.pdf_url,
                "financial_insights": insights,
            })
        else:
            collapsed_routine_count += 1

    # 2. Fetch triggered price and volume alerts in window
    price_alerts_query = db.query(PriceAlert)
    if apply_cutoff:
        price_alerts_query = price_alerts_query.filter(PriceAlert.created_at >= cutoff)
    price_alerts = price_alerts_query.order_by(PriceAlert.created_at.desc()).limit(20).all()

    triggered_alerts = [
        {
            "id": a.id,
            "ticker": a.ticker,
            "alert_type": a.alert_type,
            "value": a.value,
            "threshold": a.threshold,
            "seen": a.seen,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "message": (
                f"{a.ticker} moved {a.value:+.2f}% (crossed ±{a.threshold}%)"
                if a.alert_type == "price_move"
                else f"{a.ticker} volume surged to {a.value:.1f}× 20-day avg (threshold {a.threshold}×)"
            ),
        }
        for a in price_alerts
    ]

    return {
        "digest_window_hours": effective_hours,
        "as_of": datetime.now().isoformat(),
        "summary": {
            "total_announcements": len(all_announcements),
            "prioritized_count": len(prioritized_items),
            "collapsed_routine_count": collapsed_routine_count,
            "triggered_price_alerts_count": len(triggered_alerts),
            "category_breakdown": cat_breakdown,
        },
        "config_applied": {
            "min_materiality_score": effective_min_score,
            "portfolio_only": effective_portfolio_only,
            "enabled_categories": prefs.enabled_categories.split(","),
        },
        "triggered_market_alerts": triggered_alerts,
        "prioritized_announcements": prioritized_items,
    }
