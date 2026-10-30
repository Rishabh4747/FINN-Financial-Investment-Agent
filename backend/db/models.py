"""
SQLAlchemy ORM models for FINN.
All tables are created on startup via Base.metadata.create_all().
"""
from datetime import datetime, date as date_type
from sqlalchemy import (
    Integer, String, Float, Boolean, DateTime, Date,
    Text, UniqueConstraint, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base


class PortfolioCompany(Base):
    """
    The 15–20 NSE/BSE companies in the mock portfolio.
    Alert thresholds are configurable per company.
    """
    __tablename__ = "portfolio_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)   # 'NSE' | 'BSE'
    sector: Mapped[str] = mapped_column(String(60), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Configurable alert thresholds
    vol_alert_mult: Mapped[float] = mapped_column(Float, default=2.0)   # e.g. 2× 20-day avg
    price_alert_pct: Mapped[float] = mapped_column(Float, default=5.0)  # e.g. ±5% daily move
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<PortfolioCompany ticker={self.ticker} name={self.name}>"


class PriceSnapshot(Base):
    """
    End-of-day OHLCV data fetched via yfinance.
    One row per (ticker, date). Duplicates are ignored on upsert.
    """
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=True)
    high: Mapped[float] = mapped_column(Float, nullable=True)
    low: Mapped[float] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=True)
    volume: Mapped[int] = mapped_column(Integer, nullable=True)
    avg_vol_20d: Mapped[float] = mapped_column(Float, nullable=True)  # rolling 20-day avg volume
    pct_change: Mapped[float] = mapped_column(Float, nullable=True)   # day-over-day % change

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_ticker_date"),
        Index("ix_price_snapshots_ticker_date", "ticker", "date"),
    )

    def __repr__(self) -> str:
        return f"<PriceSnapshot ticker={self.ticker} date={self.date} close={self.close}>"


class PriceAlert(Base):
    """
    Generated when a ticker's price or volume breaches its threshold.
    `seen` is set to True once the user has acknowledged the alert in the UI.
    """
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False)  # 'price_move' | 'volume_spike'
    value: Mapped[float] = mapped_column(Float, nullable=False)     # actual value (pct or ratio)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)  # threshold that was crossed
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_price_alerts_ticker_date", "ticker", "date"),
    )

    def __repr__(self) -> str:
        return f"<PriceAlert ticker={self.ticker} type={self.alert_type} value={self.value}>"


class Announcement(Base):
    """
    Corporate announcements fetched from NSE/BSE feeds.
    Populated in Phase 2; schema created here so DB is complete from startup.
    """
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)   # 'NSE' | 'BSE'
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    company: Mapped[str] = mapped_column(String(120), nullable=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=True)    # LLM-classified
    materiality: Mapped[str] = mapped_column(String(10), nullable=True) # 'high'|'medium'|'low'
    summary: Mapped[str] = mapped_column(Text, nullable=True)           # LLM one-liner
    filing_dt: Mapped[str] = mapped_column(String(30), nullable=True)
    pdf_url: Mapped[str] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_announcements_symbol_dt", "symbol", "filing_dt"),
    )

    def __repr__(self) -> str:
        return f"<Announcement symbol={self.symbol} headline={self.headline[:40]}>"


class ResearchCache(Base):
    """
    Cached research reports keyed by (ticker, cache_date).
    Avoids re-fetching PDFs and re-calling LLM for the same ticker on the same day.
    """
    __tablename__ = "research_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    cache_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("ticker", "cache_date", name="uq_research_ticker_date"),
        Index("ix_research_cache_ticker", "ticker"),
    )

    def __repr__(self) -> str:
        return f"<ResearchCache ticker={self.ticker} date={self.cache_date}>"
