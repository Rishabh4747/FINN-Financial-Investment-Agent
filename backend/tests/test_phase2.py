"""
Phase 2 Test Suite for FINN — Corporate Announcements & Today Feed.

Covers:
  1. Announcement parsing and date normalization.
  2. Deterministic category classification (all 17 categories).
  3. Explainable materiality ranking and priority scoring.
  4. Deduplication logic (idempotent ingestion).
  5. Today API endpoints (time window filtering, category, ticker, materiality, search, alerts).
  6. Upstream network failure and malformed payload resilience.
  7. Optional live network test marked @pytest.mark.network.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import Base
from db.models import Announcement, PortfolioCompany, PriceAlert
from services.seed_service import seed_portfolio
from services.announcement_classifier import (
    classify_announcement,
    generate_concise_summary,
    CATEGORY_RULES,
)
from services.nse_service import (
    parse_nse_datetime,
    generate_dedup_key,
    parse_announcement_dict,
    ingest_announcements,
    load_synthetic_fixtures,
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
    return eng


@pytest.fixture(scope="function")
def db_session(mem_engine):
    Session = sessionmaker(bind=mem_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="function")
def seeded_db(db_session):
    seed_portfolio(db_session)
    return db_session


# ============================================================================
# 1. Parsing & Normalization Tests
# ============================================================================

class TestAnnouncementParsing:
    def test_parse_valid_standard_item(self):
        raw = {
            "symbol": "RELIANCE",
            "sm_name": "Reliance Industries Limited",
            "desc": "Outcome of Board Meeting - Financial Results",
            "attchmntText": "Financial results for quarter ended September 30, 2026 approved.",
            "an_dt": "30-Oct-2026 18:30:00",
            "attchmntFile": "https://nsearchives.nseindia.com/corporate/results.pdf",
            "seq_id": "1001",
        }
        parsed = parse_announcement_dict(raw, exchange="NSE")
        assert parsed is not None
        assert parsed["symbol"] == "RELIANCE"
        assert parsed["company"] == "Reliance Industries Limited"
        assert parsed["category"] == "results"
        assert parsed["materiality"] == "HIGH"
        assert parsed["materiality_score"] == 10.0
        assert parsed["dedup_key"] == "NSE_1001"
        assert isinstance(parsed["filing_datetime"], datetime)
        assert parsed["pdf_url"] == "https://nsearchives.nseindia.com/corporate/results.pdf"

    def test_parse_missing_symbol_returns_none(self):
        raw = {"desc": "Results without symbol", "an_dt": "30-Oct-2026 10:00:00"}
        assert parse_announcement_dict(raw) is None

    def test_parse_empty_dict_returns_none(self):
        assert parse_announcement_dict({}) is None
        assert parse_announcement_dict(None) is None  # type: ignore

    def test_parse_alternative_keys(self):
        raw = {
            "symbol": "INFY",
            "company": "Infosys Ltd",
            "headline": "Acquisition announcement",
            "description": "Company entered into joint venture agreement",
            "filing_dt": "2026-10-30 14:00:00",
            "pdf_url": "https://example.com/filing.pdf",
        }
        parsed = parse_announcement_dict(raw, exchange="BSE")
        assert parsed is not None
        assert parsed["exchange"] == "BSE"
        assert parsed["symbol"] == "INFY"
        assert parsed["company"] == "Infosys Ltd"
        assert parsed["category"] == "M&A"

    def test_date_parser_formats(self):
        # Format: DD-Mon-YYYY HH:MM:SS
        d1 = parse_nse_datetime("30-Oct-2026 20:28:12")
        assert d1 == datetime(2026, 10, 30, 20, 28, 12)

        # Format: ISO
        d2 = parse_nse_datetime("2026-10-30 20:28:12")
        assert d2 == datetime(2026, 10, 30, 20, 28, 12)

        # Format: 14-digit compact timestamp ddMMyyyyHHmmss
        d3 = parse_nse_datetime("30102026202812")
        assert d3 == datetime(2026, 10, 30, 20, 28, 12)

        # Invalid formats return None gracefully
        assert parse_nse_datetime("invalid-date") is None
        assert parse_nse_datetime(None) is None
        assert parse_nse_datetime("") is None


# ============================================================================
# 2. Classification & Materiality Ranking Tests
# ============================================================================

class TestCategoryClassification:
    @pytest.mark.parametrize(
        "headline,desc,expected_category,expected_materiality",
        [
            ("Financial Results for Q2 FY27", "Board approved unaudited financial results", "results", "HIGH"),
            ("Outcome of Board Meeting", "Approved unaudited standalone and consolidated results", "results", "HIGH"),
            ("Corporate Restructuring", "Acquisition of 100% equity stake in subsidiary", "M&A", "HIGH"),
            ("Scheme of Amalgamation", "Board approved merger with wholly owned subsidiary", "M&A", "HIGH"),
            ("Fund Raising", "Approved raising of funds via QIP and rights issue", "fund_raise", "HIGH"),
            ("Commercial Paper Allotment", "Issuance of commercial paper up to Rs 500 Cr", "fund_raise", "HIGH"),
            ("Change in Management", "Resignation of Chief Financial Officer (CFO)", "management_change", "HIGH"),
            ("Board Appointment", "Appointment of Managing Director and CEO", "management_change", "HIGH"),
            ("Litigation Disclosure", "Received penalty order from tax authorities", "litigation", "HIGH"),
            ("NCLT Proceedings", "Admission of insolvency petition under IBC", "litigation", "HIGH"),
            ("Bonus Shares Recommendation", "Board recommended 1:1 bonus issue", "bonus_split", "MEDIUM"),
            ("Stock Split Intimation", "Sub-division of equity shares from face value Rs 10 to Rs 1", "bonus_split", "MEDIUM"),
            ("Capital Expenditure Plan", "Setting up of new manufacturing plant in Gujarat", "capex", "MEDIUM"),
            ("Capacity Expansion", "Commissioning of new facility and commercial production", "capex", "MEDIUM"),
            ("Dividend Declaration", "Board declared interim dividend of Rs 8 per share", "dividend", "MEDIUM"),
            ("Credit Rating Action", "CRISIL reaffirmed AAA rating on long term debt", "credit_rating", "MEDIUM"),
            ("Insider Trading Disclosure", "Disclosures under Regulation 7(2) of SEBI PIT Regulations", "insider_trading", "MEDIUM"),
            ("Press Release", "Company secured major commercial order win worth Rs 1,200 Cr", "press_release", "MEDIUM"),
            ("Earnings Call Notification", "Transcript of conference call with analysts", "earnings_call", "LOW"),
            ("Investor Meet Schedule", "Schedule of institutional investor meeting with Fidelity", "investor_meetings", "LOW"),
            ("Promoter Share Encumbrance", "Release of pledge under SAST Regulations", "pledging", "LOW"),
            ("Shareholders Meeting", "Proceedings of Annual General Meeting (AGM) and voting results", "agm_egm", "LOW"),
            ("Postal Ballot Notice", "Notice of postal ballot and remote e-voting", "postal_ballot", "LOW"),
            ("ESOP Allotment", "Allotment of 5,000 equity shares under ESOP scheme", "unclassified", "LOW"),
            ("Loss of Share Certificate", "Duplicate share certificate issuance request", "unclassified", "LOW"),
        ],
    )
    def test_deterministic_rules(self, headline, desc, expected_category, expected_materiality):
        res = classify_announcement(headline, desc, "TestCo")
        assert res.category == expected_category
        assert res.materiality == expected_materiality
        assert res.materiality_score > 0
        assert len(res.classification_rationale) > 0
        assert len(res.materiality_rationale) > 0

    def test_explainable_rationale(self):
        res = classify_announcement("Outcome of Board Meeting", "Approved unaudited financial results", "TestCo")
        assert "Matched keyword/phrase" in res.classification_rationale
        assert "revenue, EBITDA" in res.materiality_rationale
        assert res.classification_confidence == "HIGH"

    def test_unclassified_fallback(self):
        res = classify_announcement("Routine Administrative Filing", "Certificate under Regulation 74(5)", "TestCo")
        assert res.category == "unclassified"
        assert res.materiality == "LOW"
        assert res.classification_confidence == "LOW"
        assert "routine" in res.classification_rationale.lower()

    def test_summary_factual_integrity(self):
        summary = generate_concise_summary(
            "management_change",
            "Change in Management",
            "Resignation of Rajesh Sharma as Chief Financial Officer",
            "Infosys",
        )
        assert "Infosys" in summary
        assert "Resignation" in summary
        assert "Rajesh Sharma" in summary


# ============================================================================
# 3. Deduplication Tests
# ============================================================================

class TestDeduplication:
    def test_stable_hash_without_seq_id(self):
        k1 = generate_dedup_key("NSE", "RELIANCE", "30-Oct-2026 18:30:00", "Financial Results")
        k2 = generate_dedup_key("NSE", "RELIANCE", "30-Oct-2026 18:30:00", "Financial Results")
        assert k1 == k2
        assert len(k1) == 32

    def test_seq_id_takes_precedence(self):
        k = generate_dedup_key("NSE", "RELIANCE", "30-Oct-2026", "Results", seq_id="999888")
        assert k == "NSE_999888"

    def test_idempotent_ingestion(self, db_session):
        # Run 1: Ingest synthetic fixtures
        res1 = ingest_announcements(db_session, use_fixtures=True)
        assert res1["status"] == "ok"
        assert res1["inserted"] > 0
        initial_inserted = res1["inserted"]
        assert res1["duplicates_skipped"] == 0

        # Run 2: Re-ingest the exact same fixtures
        res2 = ingest_announcements(db_session, use_fixtures=True)
        assert res2["status"] == "ok"
        assert res2["inserted"] == 0
        assert res2["duplicates_skipped"] == initial_inserted

        # Verify DB total count equals initial run
        total_in_db = db_session.query(Announcement).count()
        assert total_in_db == initial_inserted


# ============================================================================
# 4. Today API Endpoints Tests
# ============================================================================

class TestTodayAPI:
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
        Session = sessionmaker(bind=eng)

        with Session() as s:
            seed_portfolio(s)
            # Pre-load synthetic announcements into test DB
            ingest_announcements(s, use_fixtures=True)

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

    def test_get_announcements_default_window(self):
        # Use hours=0 to retrieve all announcements regardless of fixture timestamps,
        # since synthetic fixtures use fixed past dates that would fall outside a 24h window.
        r = self.client.get("/api/today/announcements?hours=0")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_announcement_response_schema(self):
        r = self.client.get("/api/today/announcements?hours=0&limit=1")
        assert r.status_code == 200
        item = r.json()[0]
        expected_fields = {
            "id", "exchange", "symbol", "company", "headline", "description",
            "category", "classification_rationale", "classification_confidence",
            "materiality", "materiality_score", "materiality_rationale",
            "summary", "filing_dt", "pdf_url", "created_at"
        }
        for field in expected_fields:
            assert field in item, f"Missing expected field '{field}' in announcement response"

    def test_sorting_high_materiality_first(self):
        r = self.client.get("/api/today/announcements?hours=0&limit=50")
        assert r.status_code == 200
        items = r.json()
        scores = [item["materiality_score"] for item in items if item["materiality_score"] is not None]
        # Assert non-ascending order (highest priority first)
        assert scores == sorted(scores, reverse=True)

    def test_filter_by_category(self):
        r = self.client.get("/api/today/announcements?hours=0&categories=results")
        assert r.status_code == 200
        items = r.json()
        assert len(items) > 0
        assert all(item["category"] == "results" for item in items)

    def test_filter_by_materiality(self):
        r = self.client.get("/api/today/announcements?hours=0&materiality=HIGH")
        assert r.status_code == 200
        items = r.json()
        assert len(items) > 0
        assert all(item["materiality"] == "HIGH" for item in items)

    def test_filter_by_ticker(self):
        r = self.client.get("/api/today/announcements?hours=0&tickers=RELIANCE")
        assert r.status_code == 200
        items = r.json()
        assert len(items) > 0
        assert all(item["symbol"] == "RELIANCE" for item in items)

    def test_free_text_search(self):
        r = self.client.get("/api/today/announcements?hours=0&search=Gopalpur")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        assert "Gopalpur" in items[0]["description"] or "Gopalpur" in items[0]["headline"]

    def test_portfolio_only_filter(self):
        # 'ZOMATO' is in the fixture but NOT in our 15 seeded companies
        r_all = self.client.get("/api/today/announcements?hours=0&tickers=ZOMATO")
        assert len(r_all.json()) >= 1

        r_port = self.client.get("/api/today/announcements?hours=0&tickers=ZOMATO&portfolio_only=true")
        assert len(r_port.json()) == 0

    def test_time_window_filtering(self):
        # hours=1 should filter out older fixtures
        r_1h = self.client.get("/api/today/announcements?hours=1")
        assert r_1h.status_code == 200

        # hours=0 (all) should return more than 1h
        r_all = self.client.get("/api/today/announcements?hours=0")
        assert len(r_all.json()) >= len(r_1h.json())

    def test_categories_endpoint(self):
        r = self.client.get("/api/today/categories")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 17
        names = {c["category"] for c in data}
        assert "results" in names
        assert "M&A" in names
        assert "fund_raise" in names
        assert "management_change" in names
        assert "unclassified" in names

    def test_summary_endpoint(self):
        r = self.client.get("/api/today/summary?hours=0")
        assert r.status_code == 200
        data = r.json()
        assert "total_announcements" in data
        assert "high_materiality" in data
        assert "medium_materiality" in data
        assert "low_materiality" in data
        assert "categories_breakdown" in data
        assert data["total_announcements"] > 0
        assert data["high_materiality"] > 0

    def test_today_alerts_endpoint(self):
        r = self.client.get("/api/today/alerts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_refresh_with_fixtures(self):
        r = self.client.post("/api/today/refresh?use_fixtures=true")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["source"] == "synthetic_fixture"
        assert "duplicates_skipped" in data


# ============================================================================
# 5. Upstream Resilience & Error Handling Tests
# ============================================================================

class TestUpstreamResilience:
    @patch("services.nse_service.requests.Session.get")
    def test_network_timeout_handled_gracefully(self, mock_get, db_session):
        mock_get.side_effect = requests.Timeout("Connection timed out")
        res = ingest_announcements(db_session, use_fixtures=False)
        assert res["status"] == "error"
        assert res["inserted"] == 0
        assert "timed out" in res["message"].lower() or "error" in res["status"]

    @patch("services.nse_service.requests.Session.get")
    def test_http_403_rate_limiting_handled_gracefully(self, mock_get, db_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_get.return_value = mock_resp
        res = ingest_announcements(db_session, use_fixtures=False)
        assert res["status"] == "error"
        assert res["inserted"] == 0
        assert "403" in (res["error"] or "")

    @patch("services.nse_service.requests.Session.get")
    def test_malformed_json_handled_gracefully(self, mock_get, db_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Invalid JSON response")
        mock_get.return_value = mock_resp
        res = ingest_announcements(db_session, use_fixtures=False)
        assert res["status"] == "error" or res["inserted"] == 0


# ============================================================================
# 6. Live Network Test (Separately marked, optional)
# ============================================================================

@pytest.mark.network
class TestNSELiveNetwork:
    """
    Validates live integration against the National Stock Exchange API.
    Skipped automatically if network is unreachable.
    """

    @pytest.fixture(autouse=True)
    def check_network(self):
        import socket
        try:
            socket.setdefaulttimeout(5)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("www.nseindia.com", 443))
        except OSError:
            pytest.skip("NSE is unreachable over network — skipping live network test.")

    def test_live_nse_announcements_ingestion(self, db_session):
        res = ingest_announcements(db_session, use_fixtures=False, timeout=12)
        # Even if NSE occasionally blocks or rate-limits, it must never raise an unhandled error
        assert "status" in res
        assert "fetched" in res
        assert "inserted" in res
        if res["status"] == "ok":
            assert res["fetched"] > 0
            # Confirm announcements in DB have valid classifications
            items = db_session.query(Announcement).limit(5).all()
            for it in items:
                assert it.category in [r.category for r in CATEGORY_RULES] + ["unclassified"]
                assert it.materiality in ("HIGH", "MEDIUM", "LOW")
                assert it.materiality_score is not None
