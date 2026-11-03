"""
Phase 3 Test Suite for FINN — Primary Document Ingestion, Retrieval, & Research Report.

Covers:
  1. PDF text extraction across multiple pages, scanned image detection, and corrupted file handling.
  2. Source origin verification (official exchange filings, company IR, unverified domains).
  3. Chunking, provenance preservation (page numbers, section headers), and SQLite BM25 retrieval.
  4. Citation validation and transparent gap disclosure.
  5. Dual-mode research report generation (extractive evidence mode vs. LLM mode).
  6. SQLite caching and cache invalidation via force_refresh.
  7. API endpoints: POST /api/research/report, GET /api/research/report/{ticker},
     GET /api/research/documents/{ticker}, POST /api/research/documents/ingest, GET /api/research/evidence.
  8. Optional live-source discovery test marked @pytest.mark.network.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import Base, run_migrations
from db.models import SourceDocument, DocumentChunk, ResearchReportRecord
from services.seed_service import seed_portfolio
from services.document_service import (
    extract_pdf_pages,
    verify_source_origin,
    ingest_document,
    discover_sources_for_ticker,
    clean_ticker_symbol,
)
from services.retrieval_service import (
    chunk_page_text,
    index_document_chunks,
    search_evidence,
    detect_section,
)
from services.research_service import (
    generate_research_report,
    validate_citations,
    build_extractive_section,
)
from tests.fixtures.pdf_fixtures import (
    create_synthetic_annual_report_pdf,
    create_synthetic_quarterly_results_pdf,
    create_synthetic_concall_transcript_pdf,
    create_synthetic_scanned_image_pdf,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def mem_engine():
    """In-memory SQLite engine with StaticPool for safe multithreaded test client."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    run_migrations(eng)
    return eng


@pytest.fixture(scope="function")
def db_session(mem_engine):
    Session = sessionmaker(bind=mem_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="function")
def ingested_test_docs(db_session):
    """Pre-ingests synthetic Annual Report, Quarterly Results, and Concall Transcript."""
    ar_bytes = create_synthetic_annual_report_pdf("INFY", "Infosys Limited")
    res_bytes = create_synthetic_quarterly_results_pdf("INFY", "Infosys Limited")
    cc_bytes = create_synthetic_concall_transcript_pdf("INFY", "Infosys Limited")

    d1 = ingest_document(
        db_session,
        {
            "ticker": "INFY",
            "document_type": "annual_report",
            "title": "Infosys Integrated Annual Report FY26",
            "period": "FY26",
            "canonical_url": "https://www.infosys.com/investors/reports/ar2026.pdf",
        },
        pdf_bytes=ar_bytes,
    )
    d2 = ingest_document(
        db_session,
        {
            "ticker": "INFY",
            "document_type": "quarterly_result",
            "title": "Infosys Unaudited Results Q2 FY27",
            "period": "Q2 FY27",
            "canonical_url": "https://nsearchives.nseindia.com/corporate/INFY_Q2FY27_Results.pdf",
        },
        pdf_bytes=res_bytes,
    )
    d3 = ingest_document(
        db_session,
        {
            "ticker": "INFY",
            "document_type": "earnings_call",
            "title": "Infosys Earnings Call Transcript Q2 FY27",
            "period": "Q2 FY27",
            "canonical_url": "https://www.bseindia.com/stockinfo/INFY_Concall_Q2FY27.pdf",
        },
        pdf_bytes=cc_bytes,
    )
    return [d1, d2, d3]


# ============================================================================
# 1. Document Extraction & Source Verification Tests
# ============================================================================

class TestDocumentIngestionAndExtraction:
    def test_extract_pdf_pages_success(self):
        ar_bytes = create_synthetic_annual_report_pdf("INFY", "Infosys Limited")
        pages, status = extract_pdf_pages(ar_bytes)
        assert status == "extracted"
        assert len(pages) == 4
        # Verify page numbers are 1-indexed
        assert pages[0][0] == 1
        assert "ANNUAL REPORT FY26" in pages[0][1]
        assert pages[1][0] == 2
        assert "FINANCIAL HIGHLIGHTS" in pages[1][1]
        assert pages[2][0] == 3
        assert "BALANCE SHEET" in pages[2][1]
        assert pages[3][0] == 4
        assert "CASH FLOW" in pages[3][1]

    def test_scanned_image_pdf_handling(self):
        scanned_bytes = create_synthetic_scanned_image_pdf()
        pages, status = extract_pdf_pages(scanned_bytes)
        assert status == "scanned_image_only"
        assert len(pages) == 0

    def test_corrupted_pdf_handling(self):
        corrupted_bytes = b"NOT_A_VALID_PDF_STREAM_HEADER"
        pages, status = extract_pdf_pages(corrupted_bytes)
        assert status == "failed"
        assert len(pages) == 0

    def test_empty_bytes_handling(self):
        pages, status = extract_pdf_pages(b"")
        assert status == "failed"
        assert len(pages) == 0

    def test_source_origin_verification(self):
        # Official exchange filing
        v1, o1, _ = verify_source_origin("https://nsearchives.nseindia.com/corporate/filing.pdf")
        assert v1 is True
        assert o1 == "exchange_filing"

        # Official company IR site
        v2, o2, _ = verify_source_origin("https://www.infosys.com/investors/reports/ar2026.pdf")
        assert v2 is True
        assert o2 == "official_ir"

        # Third-party / unverified site
        v3, o3, _ = verify_source_origin("https://random-broker-reports.com/notes.pdf")
        assert v3 is False
        assert o3 == "unverified_web"

    def test_deduplication_on_repeated_ingestion(self, db_session):
        pdf_bytes = create_synthetic_quarterly_results_pdf("TCS", "TCS Limited")
        doc_meta = {
            "ticker": "TCS",
            "document_type": "quarterly_result",
            "title": "TCS Results Q2 FY27",
            "canonical_url": "https://www.tcs.com/investors/q2_results.pdf",
        }
        # Ingestion 1
        d1 = ingest_document(db_session, doc_meta, pdf_bytes=pdf_bytes)
        assert d1.id is not None

        # Ingestion 2 with exact same URL
        d2 = ingest_document(db_session, doc_meta, pdf_bytes=pdf_bytes)
        assert d1.id == d2.id

        # Confirm count in DB is 1
        count = db_session.query(SourceDocument).filter(SourceDocument.ticker == "TCS").count()
        assert count == 1


# ============================================================================
# 2. Chunking & BM25 Retrieval Tests
# ============================================================================

class TestChunkingAndRetrieval:
    def test_chunk_page_text_bounds(self):
        sample_page = (
            "Consolidated Financial Statements for the fiscal year ended March 31, 2026. "
            "Revenue from operations was INR 153,670 crore. Operating profit margin reached 22.2 percent. "
            "Profit before tax stood at INR 33,850 crore. The digital transformation segment grew significantly."
        )
        chunks = chunk_page_text(page_number=1, text_content=sample_page, chunk_size=120, overlap=30)
        assert len(chunks) >= 2
        for chk in chunks:
            assert chk["page_number"] == 1
            assert chk["char_count"] > 0
            assert len(chk["content"]) > 0

    def test_section_detection(self):
        sec1 = detect_section("Consolidated Balance Sheet as at March 31, 2026")
        assert sec1 == "Balance Sheet"

        sec2 = detect_section("Statement of Cash Flows for the period")
        assert sec2 == "Cash Flow Statement"

        sec3 = detect_section("Management Guidance and Forward-Looking Outlook for FY27")
        assert sec3 == "Guidance & Outlook"

    def test_bm25_retrieval_passages(self, db_session, ingested_test_docs):
        # Search for revenue numbers
        res = search_evidence(db_session, "INFY", "revenue operations profit", limit=3)
        assert len(res) > 0
        top = res[0]
        assert top["ticker"] == "INFY"
        assert top["page_number"] is not None
        assert "revenue" in top["content"].lower() or "profit" in top["content"].lower()
        assert top["canonical_url"].startswith("http")

    def test_bm25_retrieval_guidance(self, db_session, ingested_test_docs):
        # Search for guidance
        res = search_evidence(db_session, "INFY", "guidance outlook target", limit=3)
        assert len(res) > 0
        combined = " ".join(r["content"] for r in res)
        assert "guidance" in combined.lower()


# ============================================================================
# 3. Citation Validation Tests
# ============================================================================

class TestCitationValidation:
    def test_validate_citations_filters_phantoms(self, db_session, ingested_test_docs):
        valid_doc = ingested_test_docs[0]
        citations = [
            # Valid citation referencing ingested document
            {
                "document_id": valid_doc.id,
                "canonical_url": valid_doc.canonical_url,
                "page_number": 2,
                "section": "Financial Highlights",
                "passage_snippet": "Consolidated revenue reached INR 153,670 crore",
            },
            # Phantom citation referencing non-existent document ID
            {
                "document_id": 99999,
                "canonical_url": "https://phantom-fake-site.com/doc.pdf",
                "page_number": 10,
                "section": "Invented Section",
                "passage_snippet": "Invented claim",
            },
        ]
        validated = validate_citations(citations, ingested_test_docs)
        assert len(validated) == 1
        assert validated[0]["document_id"] == valid_doc.id
        assert validated[0]["document_title"] == valid_doc.title
        assert validated[0]["page_number"] == 2


# ============================================================================
# 4. Research Report Generation Tests
# ============================================================================

class TestResearchReportGeneration:
    def test_report_without_documents_returns_error(self, db_session):
        res = generate_research_report(db_session, "UNKNOWN_TICKER")
        assert res["status"] == "error"
        assert "No primary documents" in res["message"]
        assert len(res["sources_used"]) == 0

    def test_report_extractive_mode_generation(self, db_session, ingested_test_docs):
        # Tests deterministic extractive mode (zero LLM dependency)
        res = generate_research_report(db_session, "INFY")
        assert res["status"] == "completed"
        assert res["ticker"] == "INFY"
        assert res["mode"] == "extractive_only"

        # Check that all 8 core sections are present
        sections = res["sections"]
        expected_sections = [
            "business_snapshot",
            "financial_snapshot",
            "trajectory",
            "balance_sheet",
            "cash_flow_quality",
            "narrative_vs_numbers",
            "guidance",
            "bull_bear",
        ]
        for sec in expected_sections:
            assert sec in sections, f"Missing section '{sec}'"
            assert len(sections[sec]) > 20, f"Section '{sec}' was unexpectedly empty"

        # Verify sources used
        assert len(res["sources_used"]) == 3
        # Verify citations generated and validated
        assert len(res["citations"]) > 0
        for cit in res["citations"]:
            assert "document_title" in cit
            assert "canonical_url" in cit

    def test_report_gap_disclosure_when_source_missing(self, db_session):
        # Ingest ONLY Quarterly Results (missing Annual Report and Transcript)
        res_bytes = create_synthetic_quarterly_results_pdf("MARUTI", "Maruti Suzuki")
        ingest_document(
            db_session,
            {
                "ticker": "MARUTI",
                "document_type": "quarterly_result",
                "title": "Maruti Suzuki Results Q2 FY27",
                "canonical_url": "https://www.marutisuzuki.com/results.pdf",
            },
            pdf_bytes=res_bytes,
        )
        report = generate_research_report(db_session, "MARUTI")
        assert report["status"] == "completed"
        # Should disclose Annual Report and Transcript gaps transparently
        assert "Annual Report not ingested" in report["evidence_gaps"]
        assert "Earnings-call transcript not ingested" in report["evidence_gaps"]

    def test_report_caching_and_force_refresh(self, db_session, ingested_test_docs):
        # Initial run
        r1 = generate_research_report(db_session, "INFY", force_refresh=False)
        # Second run should read from SQLite cache
        r2 = generate_research_report(db_session, "INFY", force_refresh=False)
        assert r1["report_version"] == r2["report_version"]
        assert r1["generated_at"] == r2["generated_at"]

        # Force refresh generates fresh timestamp
        r3 = generate_research_report(db_session, "INFY", force_refresh=True)
        assert r3["status"] == "completed"


# ============================================================================
# 5. API Endpoints Tests
# ============================================================================

class TestResearchAPI:
    @pytest.fixture(autouse=True)
    def setup_api_client(self):
        from fastapi.testclient import TestClient
        from main import app
        from db.database import get_db

        eng = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=eng)
        run_migrations(eng)
        Session = sessionmaker(bind=eng)

        # Pre-seed portfolio and ingest test docs
        with Session() as s:
            seed_portfolio(s)
            ar_bytes = create_synthetic_annual_report_pdf("INFY", "Infosys Limited")
            ingest_document(
                s,
                {
                    "ticker": "INFY",
                    "document_type": "annual_report",
                    "title": "Infosys Integrated Annual Report FY26",
                    "period": "FY26",
                    "canonical_url": "https://www.infosys.com/investors/reports/ar2026.pdf",
                },
                pdf_bytes=ar_bytes,
            )

        def override_get_db():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            self.client = c
            yield c
        app.dependency_overrides.clear()

    def test_post_report_endpoint(self):
        r = self.client.post("/api/research/report", json={"ticker": "INFY"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "completed"
        assert data["ticker"] == "INFY"
        assert "business_snapshot" in data["sections"]
        assert len(data["sources_used"]) >= 1

    def test_get_report_endpoint_cached(self):
        # Generate first
        self.client.post("/api/research/report", json={"ticker": "INFY"})
        # Retrieve cached
        r = self.client.get("/api/research/report/INFY")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "completed"
        assert data["ticker"] == "INFY"

    def test_get_report_404_for_unseen_ticker(self):
        r = self.client.get("/api/research/report/NONEXISTENT")
        assert r.status_code == 404

    def test_get_documents_endpoint(self):
        # Disables external network scrape during fast unit test
        r = self.client.get("/api/research/documents/INFY?discover=false")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "INFY"
        assert data["ingested_count"] >= 1
        assert len(data["ingested_documents"]) >= 1

    def test_post_documents_ingest_endpoint(self):
        payload = {
            "ticker": "INFY",
            "document_type": "quarterly_result",
            "title": "Q1 FY27 Results",
            "canonical_url": "https://nsearchives.nseindia.com/corporate/INFY_Q1.pdf",
            "period": "Q1 FY27",
        }
        with patch("services.document_service.requests.get") as mock_get:
            mock_resp = mock_get.return_value
            mock_resp.status_code = 200
            mock_resp.content = create_synthetic_quarterly_results_pdf("INFY", "Infosys Limited")
            r = self.client.post("/api/research/documents/ingest", json=payload)
            assert r.status_code == 201
            data = r.json()
            assert data["title"] == "Q1 FY27 Results"
            assert data["document_type"] == "quarterly_result"

    def test_get_evidence_endpoint(self):
        r = self.client.get("/api/research/evidence?ticker=INFY&query=revenue&limit=3")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "INFY"
        assert "results" in data
        assert isinstance(data["results"], list)


# ============================================================================
# 6. Live Source Discovery Test (Marked @pytest.mark.network)
# ============================================================================

@pytest.mark.network
class TestLiveSourceDiscovery:
    """Exercises real web discovery for an NSE ticker; skipped automatically if offline."""

    @pytest.fixture(autouse=True)
    def check_network(self):
        import socket
        try:
            socket.setdefaulttimeout(5)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("www.screener.in", 443))
        except OSError:
            pytest.skip("Network access to screener.in unavailable; skipping live test.")

    def test_live_discovery_reliance(self):
        candidates = discover_sources_for_ticker("RELIANCE", timeout=12)
        assert isinstance(candidates, list)
        # Verify candidate structure
        for c in candidates[:3]:
            assert "canonical_url" in c
            assert "document_type" in c
            assert "source_origin" in c
            assert "is_verified_primary" in c
