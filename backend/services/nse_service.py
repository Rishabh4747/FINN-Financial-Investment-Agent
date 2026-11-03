"""
NSE Corporate Announcements Ingestion Service.

Fetches announcements from the National Stock Exchange of India (NSE),
parses and normalizes disparate payload schemas, performs deterministic
classification, explainable materiality ranking, and idempotent deduplication.

Gracefully handles:
  - Network timeouts and rate limits (403, 429, 5xx)
  - Malformed records or missing fields (symbol, attachment, timestamp)
  - Varied date formats (DD-Mon-YYYY HH:MM:SS, ISO, compact timestamp)
  - Offline / synthetic fixture loading for guaranteed test reproducibility
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from sqlalchemy.orm import Session

from config import get_settings
from db.models import Announcement
from services.announcement_classifier import classify_announcement

logger = logging.getLogger(__name__)
settings = get_settings()

NSE_HOME_URL = "https://www.nseindia.com/"
NSE_ANNOUNCEMENTS_API = "https://www.nseindia.com/api/home-corporate-announcements?index=equities"
NSE_CORP_API_FALLBACK = "https://www.nseindia.com/api/corporate-announcements?index=equities"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
    "Accept-Language": "en-US,en;q=0.9",
}

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "synthetic_announcements.json"


# ---------------------------------------------------------------------------
# Date Normalization Helper
# ---------------------------------------------------------------------------

def parse_nse_datetime(raw_dt: Optional[str]) -> Optional[datetime]:
    """
    Parses various date/time formats returned by NSE API endpoints into a python datetime:
      - '30-Oct-2026 20:28:12'
      - '30-OCT-2026 19:55:12'
      - '2026-10-30 20:28:12'
      - '30102026202812' (ddMMyyyyHHmmss)
    """
    if not raw_dt or not isinstance(raw_dt, str):
        return None

    cleaned = raw_dt.strip()
    if not cleaned:
        return None

    # Format 1: 30-Oct-2026 20:28:12 or 30-OCT-2026 20:28:12
    for fmt in (
        "%d-%b-%Y %H:%M:%S",
        "%d-%B-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            pass

    # Format 2: compact digits e.g. '30102026202812'
    if cleaned.isdigit() and len(cleaned) == 14:
        try:
            return datetime.strptime(cleaned, "%d%m%Y%H%M%S")
        except ValueError:
            pass

    # If all parsers fail, return None without raising
    logger.debug(f"Unable to parse timestamp: {raw_dt}")
    return None


# ---------------------------------------------------------------------------
# Deduplication Key Generator
# ---------------------------------------------------------------------------

def generate_dedup_key(exchange: str, symbol: str, filing_dt: Optional[str], headline: str, seq_id: Optional[str] = None) -> str:
    """
    Creates a unique, stable deduplication hash.
    If official seq_id is available, uses that; otherwise hashes normalized fields.
    """
    if seq_id and str(seq_id).strip():
        return f"{exchange}_{str(seq_id).strip()}"

    raw_signature = f"{exchange.upper()}_{symbol.upper()}_{(filing_dt or '').strip()}_{(headline or '').strip().lower()}"
    return hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Single Announcement Parsing
# ---------------------------------------------------------------------------

def parse_announcement_dict(item: dict[str, Any], exchange: str = "NSE") -> Optional[dict[str, Any]]:
    """
    Validates and normalizes a raw dictionary from NSE or synthetic fixture.
    Returns a clean dictionary ready for insertion, or None if invalid.
    """
    if not isinstance(item, dict):
        return None

    symbol = item.get("symbol")
    if not symbol or not str(symbol).strip():
        return None
    symbol = str(symbol).strip().upper()

    company = item.get("sm_name") or item.get("company")
    if company:
        company = str(company).strip()

    headline = item.get("desc") or item.get("headline") or item.get("subject") or "Corporate Announcement"
    headline = str(headline).strip()

    description = item.get("attchmntText") or item.get("description")
    if description:
        description = str(description).strip()

    raw_dt = item.get("an_dt") or item.get("sort_date") or item.get("filing_dt")
    filing_datetime = parse_nse_datetime(raw_dt) if raw_dt else None

    pdf_url = item.get("attchmntFile") or item.get("pdf_url")
    if pdf_url:
        pdf_url = str(pdf_url).strip()

    seq_id = item.get("seq_id")
    dedup_key = generate_dedup_key(exchange, symbol, raw_dt, headline, seq_id)

    # Deterministic classification & explainability
    classification = classify_announcement(headline, description, company)

    return {
        "exchange": exchange,
        "symbol": symbol,
        "company": company,
        "headline": headline,
        "description": description,
        "category": classification.category,
        "classification_rationale": classification.classification_rationale,
        "classification_confidence": classification.classification_confidence,
        "materiality": classification.materiality,
        "materiality_score": classification.materiality_score,
        "materiality_rationale": classification.materiality_rationale,
        "summary": classification.summary,
        "filing_dt": raw_dt,
        "filing_datetime": filing_datetime,
        "pdf_url": pdf_url,
        "raw_json": json.dumps(item),
        "dedup_key": dedup_key,
    }


# ---------------------------------------------------------------------------
# Upstream Fetcher
# ---------------------------------------------------------------------------

def fetch_raw_announcements(timeout: int = 12) -> tuple[list[dict[str, Any]], Optional[str]]:
    """
    Attempts to fetch live announcements from NSE.
    Returns (items, error_message).
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    # Attempt 1: Direct home endpoint
    try:
        resp = session.get(NSE_ANNOUNCEMENTS_API, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", [])
            if isinstance(items, list) and items:
                logger.info(f"Fetched {len(items)} items from NSE home endpoint.")
                return items, None
    except requests.Timeout:
        logger.warning("Timeout contacting NSE home announcements endpoint.")
    except Exception as exc:
        logger.warning(f"Error on NSE home announcements endpoint: {exc}")

    # Attempt 2: Session-warmed corporate endpoint fallback
    try:
        session.get(NSE_HOME_URL, timeout=timeout)
        resp2 = session.get(NSE_CORP_API_FALLBACK, timeout=timeout)
        if resp2.status_code == 200:
            data2 = resp2.json()
            items2 = data2 if isinstance(data2, list) else data2.get("data", [])
            if isinstance(items2, list) and items2:
                logger.info(f"Fetched {len(items2)} items from NSE corporate fallback endpoint.")
                return items2, None
        return [], f"NSE returned HTTP {resp2.status_code}"
    except requests.Timeout:
        return [], "NSE API timed out."
    except Exception as exc:
        return [], f"Failed to connect to NSE: {str(exc)}"


# ---------------------------------------------------------------------------
# Fixture Loader
# ---------------------------------------------------------------------------

def load_synthetic_fixtures() -> list[dict[str, Any]]:
    """Loads verified synthetic announcement fixtures for testing / offline use."""
    if FIXTURE_PATH.exists():
        try:
            return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error(f"Error loading synthetic fixtures: {exc}")
    return []


# ---------------------------------------------------------------------------
# High-Level Ingestion Service
# ---------------------------------------------------------------------------

def ingest_announcements(
    db: Session,
    use_fixtures: bool = False,
    timeout: int = 12,
) -> dict[str, Any]:
    """
    Ingests corporate announcements into the SQLite database.
    Performs parsing, classification, explainable scoring, and deduplication.

    Returns:
      {
        "status": "ok" | "partial" | "error",
        "fetched": int,
        "inserted": int,
        "duplicates_skipped": int,
        "source": "NSE" | "synthetic_fixture",
        "error": Optional[str],
        "message": str,
      }
    """
    raw_items: list[dict[str, Any]] = []
    source = "synthetic_fixture" if use_fixtures else "NSE"
    fetch_error: Optional[str] = None

    if use_fixtures:
        raw_items = load_synthetic_fixtures()
        logger.info(f"Loaded {len(raw_items)} synthetic fixtures.")
    else:
        raw_items, fetch_error = fetch_raw_announcements(timeout=timeout)
        # If live NSE access failed and 0 items fetched, record the failure
        if fetch_error and not raw_items:
            logger.warning(f"Live NSE fetch failed: {fetch_error}")
            return {
                "status": "error",
                "fetched": 0,
                "inserted": 0,
                "duplicates_skipped": 0,
                "source": "NSE",
                "error": fetch_error,
                "message": f"Failed to fetch live announcements from NSE: {fetch_error}",
            }

    inserted_count = 0
    duplicate_count = 0
    parsing_errors = 0

    # Query existing dedup_keys in database for fast in-memory check
    existing_keys: set[str] = {
        key[0] for key in db.query(Announcement.dedup_key).filter(Announcement.dedup_key.isnot(None)).all()
    }

    new_records: list[Announcement] = []
    for raw_item in raw_items:
        parsed = parse_announcement_dict(raw_item, exchange="NSE")
        if not parsed:
            parsing_errors += 1
            continue

        dedup_key = parsed["dedup_key"]
        if dedup_key in existing_keys:
            duplicate_count += 1
            continue

        # Create new Announcement model instance
        record = Announcement(
            exchange=parsed["exchange"],
            symbol=parsed["symbol"],
            company=parsed["company"],
            headline=parsed["headline"],
            description=parsed["description"],
            category=parsed["category"],
            classification_rationale=parsed["classification_rationale"],
            classification_confidence=parsed["classification_confidence"],
            materiality=parsed["materiality"],
            materiality_score=parsed["materiality_score"],
            materiality_rationale=parsed["materiality_rationale"],
            summary=parsed["summary"],
            filing_dt=parsed["filing_dt"],
            filing_datetime=parsed["filing_datetime"],
            pdf_url=parsed["pdf_url"],
            raw_json=parsed["raw_json"],
            dedup_key=dedup_key,
        )
        db.add(record)
        new_records.append(record)
        existing_keys.add(dedup_key)
        inserted_count += 1

    db.commit()

    # Trigger Push alert evaluation for newly ingested announcements
    if new_records:
        try:
            from services.insights_service import evaluate_announcement_alerts
            evaluate_announcement_alerts(db, new_records)
        except Exception as exc:
            logger.warning(f"Error evaluating announcement alerts during ingestion: {exc}")

    status = "ok" if not fetch_error else "partial"
    message = (
        f"Ingestion from {source} completed: {inserted_count} new announcements stored, "
        f"{duplicate_count} duplicates skipped."
    )
    if parsing_errors:
        message += f" ({parsing_errors} invalid items skipped)."

    logger.info(message)
    return {
        "status": status,
        "fetched": len(raw_items),
        "inserted": inserted_count,
        "duplicates_skipped": duplicate_count,
        "source": source,
        "error": fetch_error,
        "message": message,
    }
