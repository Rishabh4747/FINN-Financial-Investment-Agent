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
    Stores complete filing metadata, categorization, explainable materiality,
    and raw payload for full traceability.
    """
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="NSE")   # 'NSE' | 'BSE'
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    company: Mapped[str] = mapped_column(String(120), nullable=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(40), nullable=True)    # results | M&A | fund_raise | etc.
    classification_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True, default="HIGH")
    materiality: Mapped[str] = mapped_column(String(10), nullable=True, default="LOW") # 'HIGH' | 'MEDIUM' | 'LOW'
    materiality_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=1.0) # 1.0 to 10.0
    materiality_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)           # concise one-liner
    filing_dt: Mapped[str | None] = mapped_column(String(30), nullable=True)   # raw exchange date string
    filing_datetime: Mapped[datetime | None] = mapped_column(DateTime, nullable=True) # normalized datetime for filtering
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(128), unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_announcements_symbol_dt", "symbol", "filing_dt"),
        Index("ix_announcements_filing_datetime", "filing_datetime"),
        Index("ix_announcements_category", "category"),
        Index("ix_announcements_materiality", "materiality"),
    )

    def __repr__(self) -> str:
        return f"<Announcement symbol={self.symbol} category={self.category} headline={self.headline[:35]}>"


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


class SourceDocument(Base):
    """
    Primary financial documents: Annual Reports, Quarterly Results, Earnings Call Transcripts.
    Tracks origin verification, canonical URL, and extraction status.
    """
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)  # annual_report | quarterly_result | earnings_call
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    period: Mapped[str | None] = mapped_column(String(50), nullable=True)   # e.g. FY26, Q2 FY27
    doc_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_origin: Mapped[str] = mapped_column(String(50), default="official_ir")  # official_ir | exchange_filing | verified_archive
    is_verified_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_status: Mapped[str] = mapped_column(String(30), default="pending")  # extracted | partial | scanned_image_only | failed | empty
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_source_docs_ticker_type", "ticker", "document_type"),
    )

    def __repr__(self) -> str:
        return f"<SourceDocument ticker={self.ticker} type={self.document_type} title={self.title[:30]}>"


class DocumentChunk(Base):
    """
    Semantic text chunks extracted from primary documents.
    Preserves exact provenance (document ID, ticker, page number, section).
    """
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_chunks_ticker_doc", "ticker", "document_id"),
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk doc_id={self.document_id} p={self.page_number} len={self.char_count}>"


class ResearchReportRecord(Base):
    """
    Evidence-grounded research reports.
    Caches structured analysis, citations, and evidence gaps.
    """
    __tablename__ = "research_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    report_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="completed")     # completed | extractive_only | failed
    mode: Mapped[str] = mapped_column(String(30), default="extractive_only") # llm_synthesized | extractive_only
    business_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    financial_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    trajectory: Mapped[str | None] = mapped_column(Text, nullable=True)
    balance_sheet: Mapped[str | None] = mapped_column(Text, nullable=True)
    cash_flow_quality: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative_vs_numbers: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    bull_bear: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations_json: Mapped[str] = mapped_column(Text, nullable=False)
    sources_used_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_gaps: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_report_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_research_reports_ticker_ver", "ticker", "report_version"),
    )


class AlertPreference(Base):
    """
    User configuration for FINN's Push mode & triggered alerts:
      - digest_window_hours: default time window for digest (default 24h)
      - min_materiality_score: minimum materiality threshold to trigger alert (e.g. 7.0 = HIGH)
      - enabled_categories: comma-separated announcement categories the user wants alerts for
      - default_price_alert_pct: default ±X% price move threshold
      - default_vol_alert_mult: default ~X× volume spike multiplier
      - portfolio_only: whether to restrict alerts to active portfolio holdings
      - auto_insights: whether to extract first-cut financial numbers and executive bios
    """
    __tablename__ = "alert_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    digest_window_hours: Mapped[float] = mapped_column(Float, default=24.0)
    min_materiality_score: Mapped[float] = mapped_column(Float, default=7.0)
    enabled_categories: Mapped[str] = mapped_column(
        String(255),
        default="results,M&A,fund_raise,management_change,litigation,capex,dividend",
    )
    default_price_alert_pct: Mapped[float] = mapped_column(Float, default=5.0)
    default_vol_alert_mult: Mapped[float] = mapped_column(Float, default=2.0)
    portfolio_only: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_insights: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<AlertPreference window={self.digest_window_hours}h min_score={self.min_materiality_score}>"


class AnnouncementAlert(Base):
    """
    Triggered alerts for corporate announcements that cross user-defined
    category and materiality thresholds.
    """
    __tablename__ = "announcement_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    announcement_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    materiality: Mapped[str] = mapped_column(String(10), nullable=False)
    materiality_score: Mapped[float] = mapped_column(Float, nullable=False)
    financial_insights_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_ann_alerts_symbol_seen", "symbol", "seen"),
        Index("ix_ann_alerts_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AnnouncementAlert symbol={self.symbol} cat={self.category} score={self.materiality_score}>"
