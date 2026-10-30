"""
Seed utility — loads portfolio.json into the portfolio_companies table.
Runs on startup if the table is empty.
Idempotent: does not overwrite existing rows.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from db.models import PortfolioCompany

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = Path(__file__).resolve().parent.parent / "data" / "portfolio.json"


def seed_portfolio(db: Session) -> int:
    """
    Insert portfolio companies from data/portfolio.json if none exist yet.
    Returns the number of rows inserted (0 if already seeded).
    """
    existing_count = db.query(PortfolioCompany).count()
    if existing_count > 0:
        logger.info(f"Portfolio already seeded ({existing_count} companies). Skipping.")
        return 0

    data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    inserted = 0
    for item in data:
        company = PortfolioCompany(
            ticker=item["ticker"],
            name=item["name"],
            exchange=item["exchange"],
            sector=item["sector"],
            vol_alert_mult=item.get("vol_alert_mult", 2.0),
            price_alert_pct=item.get("price_alert_pct", 5.0),
        )
        db.add(company)
        inserted += 1

    db.commit()
    logger.info(f"Seeded {inserted} companies into portfolio_companies.")
    return inserted
