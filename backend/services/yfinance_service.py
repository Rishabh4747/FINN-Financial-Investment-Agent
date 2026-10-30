"""
yfinance service — fetches end-of-day price + volume data for all portfolio tickers.

Responsibilities:
  - Download OHLCV history for a list of tickers (one batched yfinance call).
  - Compute 20-day average volume per ticker.
  - Compute day-over-day % price change.
  - Upsert results into price_snapshots table.
  - Evaluate alert thresholds and write new PriceAlert rows where breached.

Design notes:
  - All calculations are deterministic Python/pandas — no LLM involved.
  - Clearly marks tickers where yfinance returned no data.
  - Uses yfinance 1.7.x batch download API (auto_adjust=True for split/dividend-adj closes).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from config import get_settings
from db.models import PortfolioCompany, PriceSnapshot, PriceAlert

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------

def fetch_and_store_prices(db: Session) -> dict[str, Any]:
    """
    Main entry point called by the /api/portfolio/prices/refresh endpoint
    and by the APScheduler job.

    Returns a summary dict:
      {
        "success": [...tickers with data],
        "no_data": [...tickers yfinance returned nothing for],
        "alerts_generated": int,
        "snapshots_upserted": int,
      }
    """
    companies: list[PortfolioCompany] = (
        db.query(PortfolioCompany).filter(PortfolioCompany.is_active == True).all()
    )
    if not companies:
        return {"success": [], "no_data": [], "alerts_generated": 0, "snapshots_upserted": 0}

    tickers = [c.ticker for c in companies]
    threshold_map = {c.ticker: c for c in companies}

    # yfinance needs `period` or explicit start/end; we pull 30 days to compute
    # the 20-day rolling average volume.
    history_days = settings.yf_history_days
    end_date = date.today()
    start_date = end_date - timedelta(days=history_days + 5)  # +5 buffer for weekends

    logger.info(f"Fetching yfinance data for {len(tickers)} tickers ({start_date} → {end_date})")

    raw: pd.DataFrame = _download_batch(tickers, start_date, end_date)

    if raw.empty:
        logger.warning("yfinance returned an empty DataFrame for all tickers.")
        return {"success": [], "no_data": tickers, "alerts_generated": 0, "snapshots_upserted": 0}

    success_tickers: list[str] = []
    no_data_tickers: list[str] = []
    snapshots_upserted = 0
    alerts_generated = 0

    for ticker in tickers:
        series = _extract_ticker_series(raw, ticker)
        if series is None or series.empty:
            logger.warning(f"No data returned for {ticker}")
            no_data_tickers.append(ticker)
            continue

        success_tickers.append(ticker)
        company = threshold_map[ticker]

        # Enrich with rolling avg volume + pct change
        series = _enrich(series, window=settings.yf_avg_vol_window)

        # Upsert snapshots
        count = _upsert_snapshots(db, ticker, series)
        snapshots_upserted += count

        # Evaluate alerts for the most recent row only
        latest = series.iloc[-1]
        n = _evaluate_alerts(db, ticker, latest, company)
        alerts_generated += n

    db.commit()
    logger.info(
        f"Done. {len(success_tickers)} tickers OK, {len(no_data_tickers)} empty, "
        f"{snapshots_upserted} snapshots upserted, {alerts_generated} alerts generated."
    )
    return {
        "success": success_tickers,
        "no_data": no_data_tickers,
        "alerts_generated": alerts_generated,
        "snapshots_upserted": snapshots_upserted,
    }


# ---------------------------------------------------------------------------
# yfinance helpers
# ---------------------------------------------------------------------------

def _download_batch(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """
    Download OHLCV for all tickers in one call.
    yfinance 1.7.x returns a MultiIndex DataFrame when len(tickers) > 1.
    auto_adjust=True applies split + dividend adjustments to Close.
    """
    try:
        df = yf.download(
            tickers=tickers,
            start=str(start),
            end=str(end),
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )
        return df
    except Exception as exc:
        logger.error(f"yfinance download failed: {exc}")
        return pd.DataFrame()


def _extract_ticker_series(raw: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """
    Extract a clean single-ticker DataFrame with columns:
    [open, high, low, close, volume] indexed by date.

    yfinance 1.7.x returns a MultiIndex DataFrame for multiple tickers.
    The orientation of the MultiIndex (which level holds the ticker vs. the field)
    depends on whether group_by='ticker' was passed:
      - Without group_by (our default): level 0 = ticker, level 1 = field
      - With group_by='ticker':         level 0 = field, level 1 = ticker
    We detect which orientation is present by checking both levels.
    """
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            l0_vals = raw.columns.get_level_values(0).unique().tolist()
            l1_vals = raw.columns.get_level_values(1).unique().tolist()

            if ticker in l0_vals:
                # Orientation: level 0 = ticker, level 1 = field
                df = raw.xs(ticker, axis=1, level=0).copy()
            elif ticker in l1_vals:
                # Orientation: level 0 = field, level 1 = ticker
                df = raw.xs(ticker, axis=1, level=1).copy()
            else:
                logger.warning(f"{ticker}: not found in any MultiIndex level")
                return None
        else:
            # Single ticker — columns are just field names
            df = raw.copy()

        df.columns = [c.lower() for c in df.columns]

        # yfinance may return both 'close' and 'adj close'; prefer 'close'
        # (auto_adjust=True means 'close' is already split/dividend adjusted)
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            logger.warning(f"{ticker}: missing columns {missing} (have: {list(df.columns)})")
            return None

        df = df[list(required)].dropna(subset=["close"])
        # Ensure index is plain date (not datetime)
        df.index = pd.to_datetime(df.index).date
        return df.sort_index()
    except Exception as exc:
        logger.error(f"Could not extract series for {ticker}: {exc}")
        return None


def _enrich(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    Add `avg_vol_20d` (rolling mean of volume) and `pct_change` (daily % move in close).
    Both are deterministic pandas calculations — no LLM.
    """
    df = df.copy()
    df["avg_vol_20d"] = df["volume"].rolling(window=window, min_periods=1).mean()
    df["pct_change"] = df["close"].pct_change() * 100  # percentage points
    return df


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _upsert_snapshots(db: Session, ticker: str, df: pd.DataFrame) -> int:
    """
    Upsert PriceSnapshot rows for all dates in `df`.
    SQLite INSERT OR REPLACE semantics via sqlite_insert.
    Returns the number of rows written.
    """
    rows = []
    for row_date, row in df.iterrows():
        rows.append({
            "ticker": ticker,
            "date": row_date,
            "open": _safe_float(row.get("open")),
            "high": _safe_float(row.get("high")),
            "low": _safe_float(row.get("low")),
            "close": _safe_float(row.get("close")),
            "volume": _safe_int(row.get("volume")),
            "avg_vol_20d": _safe_float(row.get("avg_vol_20d")),
            "pct_change": _safe_float(row.get("pct_change")),
        })

    if not rows:
        return 0

    stmt = sqlite_insert(PriceSnapshot).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker", "date"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "avg_vol_20d": stmt.excluded.avg_vol_20d,
            "pct_change": stmt.excluded.pct_change,
        },
    )
    db.execute(stmt)
    return len(rows)


# ---------------------------------------------------------------------------
# Alert evaluation
# ---------------------------------------------------------------------------

def _evaluate_alerts(
    db: Session,
    ticker: str,
    latest: pd.Series,
    company: PortfolioCompany,
) -> int:
    """
    Check the most recent day's data against the company's configured thresholds.
    Writes a PriceAlert row if a threshold is crossed.
    Returns the count of new alerts written.
    """
    alerts_written = 0
    row_date = latest.name if hasattr(latest, "name") else date.today()

    pct = _safe_float(latest.get("pct_change"))
    vol = _safe_float(latest.get("volume"))
    avg_vol = _safe_float(latest.get("avg_vol_20d"))

    # Price move alert
    if pct is not None and abs(pct) >= company.price_alert_pct:
        if not _alert_exists(db, ticker, row_date, "price_move"):
            db.add(PriceAlert(
                ticker=ticker,
                date=row_date,
                alert_type="price_move",
                value=round(pct, 4),
                threshold=company.price_alert_pct,
            ))
            alerts_written += 1
            logger.info(f"ALERT price_move: {ticker} moved {pct:.2f}% (threshold ±{company.price_alert_pct}%)")

    # Volume spike alert
    if vol is not None and avg_vol and avg_vol > 0:
        vol_ratio = vol / avg_vol
        if vol_ratio >= company.vol_alert_mult:
            if not _alert_exists(db, ticker, row_date, "volume_spike"):
                db.add(PriceAlert(
                    ticker=ticker,
                    date=row_date,
                    alert_type="volume_spike",
                    value=round(vol_ratio, 4),
                    threshold=company.vol_alert_mult,
                ))
                alerts_written += 1
                logger.info(
                    f"ALERT volume_spike: {ticker} vol {vol:.0f} = {vol_ratio:.1f}× avg "
                    f"(threshold {company.vol_alert_mult}×)"
                )

    return alerts_written


def _alert_exists(db: Session, ticker: str, row_date: date, alert_type: str) -> bool:
    return db.query(PriceAlert).filter(
        PriceAlert.ticker == ticker,
        PriceAlert.date == row_date,
        PriceAlert.alert_type == alert_type,
    ).first() is not None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _safe_float(val: Any) -> float | None:
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    try:
        f = float(val)
        return None if pd.isna(f) else int(f)
    except (TypeError, ValueError):
        return None
