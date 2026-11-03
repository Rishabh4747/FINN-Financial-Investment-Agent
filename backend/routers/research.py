"""
Research router — Phase 3 implementation.

Provides evidence-grounded company research and primary document ingestion:
  - POST /api/research/report             — generate or retrieve evidence-backed report
  - GET  /api/research/report/{ticker}    — fetch latest cached report
  - GET  /api/research/documents/{ticker} — discover & list primary source documents
  - POST /api/research/documents/ingest   — ingest an official primary document
  - GET  /api/research/evidence           — direct passage retrieval & provenance search
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import ResearchReportRecord, SourceDocument
from services.document_service import (
    discover_sources_for_ticker,
    ingest_document,
    clean_ticker_symbol,
)
from services.research_service import generate_research_report
from services.retrieval_service import search_evidence

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research", tags=["research"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class ReportRequest(BaseModel):
    ticker: str = Field(..., description="NSE ticker symbol (e.g. INFY, RELIANCE)")
    force_refresh: bool = Field(False, description="Bypass cache and regenerate")


class DocumentIngestRequest(BaseModel):
    ticker: str
    document_type: str = Field(..., pattern="^(annual_report|quarterly_result|earnings_call)$")
    title: str
    canonical_url: str
    period: Optional[str] = None


class CitationOut(BaseModel):
    document_id: int
    document_title: str
    document_type: str
    canonical_url: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    passage_snippet: str
    is_verified_primary: bool


class SourceDocOut(BaseModel):
    id: int
    title: str
    document_type: str
    period: Optional[str] = None
    canonical_url: str
    source_origin: str
    is_verified_primary: bool
    extraction_status: str
    total_pages: Optional[int] = None


class ResearchReportOut(BaseModel):
    status: str
    ticker: str
    report_version: Optional[str] = None
    mode: Optional[str] = None
    generated_at: Optional[str] = None
    sections: dict[str, str] = {}
    evidence_gaps: Optional[str] = None
    sources_used: list[SourceDocOut] = []
    citations: list[CitationOut] = []
    message: Optional[str] = None


class DocumentListResponse(BaseModel):
    ticker: str
    ingested_count: int
    ingested_documents: list[SourceDocOut]
    discovered_candidates: list[dict[str, Any]]


class EvidenceSearchResult(BaseModel):
    ticker: str
    query: str
    total_results: int
    results: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# POST /api/research/report
# ---------------------------------------------------------------------------

@router.post("/report", response_model=ResearchReportOut)
def create_or_get_report(
    payload: ReportRequest,
    db: Session = Depends(get_db),
) -> ResearchReportOut:
    """
    Generates or retrieves a cached evidence-backed research report.
    Grounded in primary sources (Annual Reports, Results, Earnings Calls).
    """
    clean_sym = clean_ticker_symbol(payload.ticker)
    result = generate_research_report(db, clean_sym, force_refresh=payload.force_refresh)

    if result.get("status") == "error":
        return ResearchReportOut(
            status="error",
            ticker=clean_sym,
            message=result.get("message", "Could not generate report."),
            evidence_gaps=result.get("evidence_gaps"),
            sections={},
            sources_used=[],
            citations=[],
        )

    return ResearchReportOut(**result)


# ---------------------------------------------------------------------------
# GET /api/research/report/{ticker}
# ---------------------------------------------------------------------------

@router.get("/report/{ticker}", response_model=ResearchReportOut)
def get_latest_report(
    ticker: str,
    db: Session = Depends(get_db),
) -> ResearchReportOut:
    """Retrieves the latest generated report from SQLite cache."""
    clean_sym = clean_ticker_symbol(ticker)
    report = (
        db.query(ResearchReportRecord)
        .filter(ResearchReportRecord.ticker == clean_sym)
        .order_by(ResearchReportRecord.created_at.desc())
        .first()
    )
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No research report found for ticker {clean_sym}. Use POST /api/research/report to generate one.",
        )

    import json
    data = json.loads(report.full_report_json)
    return ResearchReportOut(**data)


# ---------------------------------------------------------------------------
# GET /api/research/documents/{ticker}
# ---------------------------------------------------------------------------

@router.get("/documents/{ticker}", response_model=DocumentListResponse)
def list_and_discover_documents(
    ticker: str,
    discover: bool = Query(True, description="Discover candidate URLs from exchange & IR sources"),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    """
    Lists all ingested primary documents and optionally discovers candidate
    Annual Reports, Results, and Concalls available for ingestion.
    """
    clean_sym = clean_ticker_symbol(ticker)

    # 1. Fetch ingested documents from SQLite
    ingested = (
        db.query(SourceDocument)
        .filter(SourceDocument.ticker == clean_sym)
        .order_by(SourceDocument.created_at.desc())
        .all()
    )

    ingested_out = [
        SourceDocOut(
            id=d.id,
            title=d.title,
            document_type=d.document_type,
            period=d.period,
            canonical_url=d.canonical_url,
            source_origin=d.source_origin,
            is_verified_primary=d.is_verified_primary,
            extraction_status=d.extraction_status,
            total_pages=d.total_pages,
        )
        for d in ingested
    ]

    # 2. Discover candidates
    candidates = discover_sources_for_ticker(clean_sym, db=db) if discover else []

    return DocumentListResponse(
        ticker=clean_sym,
        ingested_count=len(ingested_out),
        ingested_documents=ingested_out,
        discovered_candidates=candidates,
    )


# ---------------------------------------------------------------------------
# POST /api/research/documents/ingest
# ---------------------------------------------------------------------------

@router.post("/documents/ingest", response_model=SourceDocOut, status_code=status.HTTP_201_CREATED)
def ingest_primary_document(
    payload: DocumentIngestRequest,
    db: Session = Depends(get_db),
) -> SourceDocOut:
    """Ingests, extracts, and indexes an official primary document."""
    meta = payload.model_dump()
    doc = ingest_document(db, meta)

    return SourceDocOut(
        id=doc.id,
        title=doc.title,
        document_type=doc.document_type,
        period=doc.period,
        canonical_url=doc.canonical_url,
        source_origin=doc.source_origin,
        is_verified_primary=doc.is_verified_primary,
        extraction_status=doc.extraction_status,
        total_pages=doc.total_pages,
    )


# ---------------------------------------------------------------------------
# GET /api/research/evidence
# ---------------------------------------------------------------------------

@router.get("/evidence", response_model=EvidenceSearchResult)
def search_evidence_passages(
    ticker: str = Query(..., description="NSE ticker symbol"),
    query: str = Query(..., description="Financial search query"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> EvidenceSearchResult:
    """Searches indexed passages for transparent citation auditing."""
    clean_sym = clean_ticker_symbol(ticker)
    passages = search_evidence(db, clean_sym, query, limit=limit)

    return EvidenceSearchResult(
        ticker=clean_sym,
        query=query,
        total_results=len(passages),
        results=passages,
    )
