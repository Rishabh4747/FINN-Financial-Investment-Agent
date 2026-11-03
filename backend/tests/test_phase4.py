"""
Phase 4 test suite for FINN backend.

Covers Alerts and Financial Insights:
  1. Financial insights extraction (Results, Management Changes, M&A, Fund Raise, Dividend, Capex)
  2. User alert preferences & configurable thresholds (window, categories, materiality)
  3. Announcement alert evaluation, filtering, and deduplication
  4. Windowed Push Digest (24h default, priority ranking, collapsed routine counts)
  5. Unified alerts feed and alert acknowledgement
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, date
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from db.database import Base, get_db
from db.models import (
    Announcement,
    AnnouncementAlert,
    AlertPreference,
    PortfolioCompany,
    PriceAlert,
)
from services.insights_service import (
    extract_financial_insights,
    get_or_create_alert_preferences,
    update_alert_preferences,
    evaluate_announcement_alerts,
    generate_push_digest,
)
from main import app


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def mem_engine():
    """Isolated in-memory SQLite engine using StaticPool."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture(scope="function")
def db_session(mem_engine):
    """In-memory DB session."""
    Session = sessionmaker(bind=mem_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(mem_engine):
    """FastAPI TestClient with in-memory DB override."""
    Session = sessionmaker(bind=mem_engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def sample_portfolio(db_session):
    """Seed test portfolio companies."""
    comps = [
        PortfolioCompany(ticker="RELIANCE.NS", name="Reliance Industries", exchange="NSE", sector="Energy"),
        PortfolioCompany(ticker="INFY.NS", name="Infosys Limited", exchange="NSE", sector="IT"),
        PortfolioCompany(ticker="HDFCBANK.NS", name="HDFC Bank", exchange="NSE", sector="Financials"),
    ]
    for c in comps:
        db_session.add(c)
    db_session.commit()
    return comps


# ============================================================================
# 1. Financial Insights Extractor (Unit Tests)
# ============================================================================

class TestFinancialInsightsExtraction:
    def test_results_headline_extraction(self):
        headline = "Financial Results for Q2 FY27"
        desc = (
            "Consolidated revenue of ₹2,45,000 Crore (+18% YoY). EBITDA was ₹38,500 Cr with margins at 15.7%. "
            "PBT reached ₹25,000 Crore. Net Profit (PAT) at ₹18,200 Crore (+14% YoY, +6% QoQ)."
        )
        res = extract_financial_insights(headline, desc, category="results")

        assert res["insight_type"] == "quarterly_results"
        assert res["scope"] == "Consolidated"
        metrics = res["headline_metrics"]
        assert "revenue" in metrics and "2,45,000" in metrics["revenue"]
        assert "ebitda" in metrics and "38,500" in metrics["ebitda"]
        assert "pbt" in metrics and "25,000" in metrics["pbt"]
        assert "pat" in metrics and "18,200" in metrics["pat"]
        assert res["growth"].get("yoy") in ("+18%", "+14%")
        assert "headline metrics:" in res["insight_summary"]

    def test_management_change_cfo_appointment(self):
        headline = "Outcome of Board Meeting - Appointment of CFO"
        desc = (
            "Appointment of Mr. Rajesh Sharma as Chief Financial Officer (CFO) of the Company with effect from November 1, 2026. "
            "Mr. Sharma is a Chartered Accountant with over 25 years of experience across corporate treasury and investment banking."
        )
        res = extract_financial_insights(headline, desc, category="management_change")

        assert res["insight_type"] == "management_change"
        assert res["role"] == "CFO"
        assert res["action"] == "Appointment"
        assert "Rajesh Sharma" in (res.get("executive_name") or "")
        assert res.get("background_bio") is not None
        assert "Chartered Accountant" in res["background_bio"]
        assert "Appointment of CFO" in res["insight_summary"]

    def test_management_change_ceo_resignation(self):
        headline = "Intimation under Regulation 30 - Resignation of Managing Director and CEO"
        desc = "Resignation of Mr. Vikram Mehta as Managing Director & CEO citing personal reasons."
        res = extract_financial_insights(headline, desc, category="management_change")

        assert res["insight_type"] == "management_change"
        assert res["role"] in ("CEO", "MD")
        assert res["action"] == "Resignation"
        assert "Vikram Mehta" in (res.get("executive_name") or "")

    def test_ma_deal_extraction(self):
        headline = "Acquisition of 51% stake in GreenTech Solutions"
        desc = "The Company has entered into a definitive agreement for acquisition of GreenTech Solutions for a cash consideration of ₹1,250 Crore."
        res = extract_financial_insights(headline, desc, category="M&A")

        assert res["insight_type"] == "ma_deal"
        assert "51%" in (res.get("stake") or "")
        assert "1,250" in (res.get("deal_value") or "")
        assert "M&A / Acquisition:" in res["insight_summary"]

    def test_fund_raise_ncd_extraction(self):
        headline = "Board approves fund raising"
        desc = "Board approved issuance of Non-Convertible Debentures (NCDs) on private placement basis for an aggregate amount up to ₹5,000 Crore."
        res = extract_financial_insights(headline, desc, category="fund_raise")

        assert res["insight_type"] == "fund_raise"
        assert "NCD" in (res.get("instrument") or "")
        assert "5,000" in (res.get("amount") or "")
        assert "Capital Raise:" in res["insight_summary"]

    def test_dividend_extraction(self):
        headline = "Declaration of Interim Dividend"
        desc = "The Board has declared an Interim Dividend of ₹12.50 per equity share. The record date is fixed as November 15, 2026."
        res = extract_financial_insights(headline, desc, category="dividend")

        assert res["insight_type"] == "dividend"
        assert "12.50" in (res.get("dividend_rate") or "")
        assert "November 15, 2026" in (res.get("record_date") or "")

    def test_capex_extraction(self):
        headline = "Expansion of manufacturing facility"
        desc = "Approval of capital expenditure with an outlay of ₹3,200 Crore for greenfield solar facility."
        res = extract_financial_insights(headline, desc, category="capex")

        assert res["insight_type"] == "capex"
        assert "3,200" in (res.get("outlay") or "")


# ============================================================================
# 2. Alert Preferences & Settings (DB & API Tests)
# ============================================================================

class TestAlertPreferences:
    def test_get_or_create_defaults(self, db_session):
        prefs = get_or_create_alert_preferences(db_session)
        assert prefs.id == 1
        assert prefs.digest_window_hours == 24.0
        assert prefs.min_materiality_score == 7.0
        assert "results" in prefs.enabled_categories
        assert prefs.portfolio_only is True

    def test_update_alert_preferences(self, db_session):
        prefs = update_alert_preferences(
            db_session,
            digest_window_hours=48.0,
            min_materiality_score=8.5,
            enabled_categories="results,M&A",
            portfolio_only=False,
        )
        assert prefs.digest_window_hours == 48.0
        assert prefs.min_materiality_score == 8.5
        assert prefs.enabled_categories == "results,M&A"
        assert prefs.portfolio_only is False

    def test_get_push_settings_api(self, client):
        r = client.get("/api/push/settings")
        assert r.status_code == 200
        body = r.json()
        assert body["digest_window_hours"] == 24.0
        assert body["min_materiality_score"] == 7.0
        assert isinstance(body["enabled_categories"], list)
        assert "results" in body["enabled_categories"]

    def test_put_push_settings_api(self, client):
        payload = {
            "digest_window_hours": 72.0,
            "min_materiality_score": 6.0,
            "enabled_categories": ["results", "M&A", "dividend"],
            "default_price_alert_pct": 4.0,
            "default_vol_alert_mult": 2.5,
            "portfolio_only": False,
        }
        r = client.put("/api/push/settings", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["digest_window_hours"] == 72.0
        assert body["min_materiality_score"] == 6.0
        assert body["enabled_categories"] == ["results", "M&A", "dividend"]
        assert body["default_price_alert_pct"] == 4.0
        assert body["portfolio_only"] is False


# ============================================================================
# 3. Announcement Alert Evaluation & Deduplication
# ============================================================================

class TestAnnouncementAlertEvaluation:
    def test_material_announcement_triggers_alert(self, db_session, sample_portfolio):
        # High materiality announcement for portfolio company RELIANCE
        ann = Announcement(
            exchange="NSE",
            symbol="RELIANCE",
            company="Reliance Industries",
            headline="Board approves Q2 Results: Net Profit up 18% YoY",
            description="Consolidated revenue of ₹2,40,000 Cr; PAT at ₹18,000 Cr.",
            category="results",
            materiality="HIGH",
            materiality_score=10.0,
            filing_datetime=datetime.now(),
        )
        db_session.add(ann)
        db_session.commit()

        count = evaluate_announcement_alerts(db_session, [ann])
        assert count == 1

        alert = db_session.query(AnnouncementAlert).filter(AnnouncementAlert.announcement_id == ann.id).first()
        assert alert is not None
        assert alert.symbol == "RELIANCE"
        assert alert.category == "results"
        assert alert.seen is False
        assert alert.financial_insights_json is not None
        insights = json.loads(alert.financial_insights_json)
        assert insights["insight_type"] == "quarterly_results"

    def test_routine_announcement_does_not_trigger_alert(self, db_session, sample_portfolio):
        ann = Announcement(
            exchange="NSE",
            symbol="RELIANCE",
            company="Reliance Industries",
            headline="Compliance Certificate under Regulation 74(5)",
            description="Routine depository participant confirmation certificate.",
            category="unclassified",
            materiality="LOW",
            materiality_score=1.5,
            filing_datetime=datetime.now(),
        )
        db_session.add(ann)
        db_session.commit()

        count = evaluate_announcement_alerts(db_session, [ann])
        assert count == 0
        stored = db_session.query(AnnouncementAlert).filter(AnnouncementAlert.announcement_id == ann.id).first()
        assert stored is None

    def test_portfolio_only_filter_behavior(self, db_session, sample_portfolio):
        # Stock NOT in portfolio (e.g. ZOMATO)
        ann = Announcement(
            exchange="NSE",
            symbol="ZOMATO",
            company="Zomato Limited",
            headline="Q2 Financial Results approved",
            category="results",
            materiality="HIGH",
            materiality_score=10.0,
            filing_datetime=datetime.now(),
        )
        db_session.add(ann)
        db_session.commit()

        # Default prefs has portfolio_only = True
        count = evaluate_announcement_alerts(db_session, [ann])
        assert count == 0

        # Change prefs to portfolio_only = False
        update_alert_preferences(db_session, portfolio_only=False)
        count2 = evaluate_announcement_alerts(db_session, [ann])
        assert count2 == 1

    def test_alert_deduplication(self, db_session, sample_portfolio):
        ann = Announcement(
            exchange="NSE",
            symbol="INFY",
            company="Infosys",
            headline="Acquisition of InSemi Technology for ₹280 Cr",
            category="M&A",
            materiality="HIGH",
            materiality_score=9.0,
            filing_datetime=datetime.now(),
        )
        db_session.add(ann)
        db_session.commit()

        # First evaluation generates 1 alert
        c1 = evaluate_announcement_alerts(db_session, [ann])
        assert c1 == 1

        # Second evaluation should be idempotent (0 new alerts)
        c2 = evaluate_announcement_alerts(db_session, [ann])
        assert c2 == 0
        total = db_session.query(AnnouncementAlert).filter(AnnouncementAlert.announcement_id == ann.id).count()
        assert total == 1


# ============================================================================
# 4. Windowed Push Digest (API Tests)
# ============================================================================

class TestPushDigest:
    def test_push_digest_structure_and_window(self, client, db_session, sample_portfolio):
        now = datetime.now()
        # 1. Recent material announcement (within 24h)
        ann1 = Announcement(
            exchange="NSE",
            symbol="RELIANCE",
            company="Reliance Industries",
            headline="Board approves Q2 FY27 Results",
            description="Revenue ₹2,40,000 Cr; PAT ₹18,000 Cr (+12% YoY).",
            category="results",
            materiality="HIGH",
            materiality_score=10.0,
            filing_datetime=now - timedelta(hours=2),
        )
        # 2. Routine compliance filing (within 24h)
        ann2 = Announcement(
            exchange="NSE",
            symbol="RELIANCE",
            company="Reliance Industries",
            headline="Submission of loss of share certificate",
            description="Duplicate certificate request received from shareholder.",
            category="unclassified",
            materiality="LOW",
            materiality_score=1.5,
            filing_datetime=now - timedelta(hours=5),
        )
        # 3. Older filing outside 24h
        ann3 = Announcement(
            exchange="NSE",
            symbol="RELIANCE",
            company="Reliance Industries",
            headline="Older M&A disclosure from 3 days ago",
            category="M&A",
            materiality="HIGH",
            materiality_score=9.0,
            filing_datetime=now - timedelta(hours=72),
        )
        # 4. Market price alert
        alert1 = PriceAlert(
            ticker="RELIANCE.NS",
            date=date.today(),
            alert_type="price_move",
            value=6.4,
            threshold=5.0,
            seen=False,
            created_at=now - timedelta(hours=1),
        )
        db_session.add_all([ann1, ann2, ann3, alert1])
        db_session.commit()

        # Call default 24h digest
        r = client.get("/api/push/digest")
        assert r.status_code == 200
        digest = r.json()

        assert digest["digest_window_hours"] == 24.0
        summary = digest["summary"]
        assert summary["total_announcements"] == 2  # ann1 & ann2, ann3 is excluded by 24h window
        assert summary["prioritized_count"] == 1    # ann1 is prioritized
        assert summary["collapsed_routine_count"] == 1 # ann2 is routine/collapsed

        # Check prioritized announcement item structure
        p_items = digest["prioritized_announcements"]
        assert len(p_items) == 1
        assert p_items[0]["symbol"] == "RELIANCE"
        assert p_items[0]["category"] == "results"
        assert "financial_insights" in p_items[0]
        assert p_items[0]["financial_insights"]["insight_type"] == "quarterly_results"

        # Check market alerts
        m_alerts = digest["triggered_market_alerts"]
        assert len(m_alerts) >= 1
        assert m_alerts[0]["ticker"] == "RELIANCE.NS"
        assert "+6.40%" in m_alerts[0]["message"]

    def test_push_digest_custom_window(self, client, db_session, sample_portfolio):
        now = datetime.now()
        ann = Announcement(
            exchange="NSE",
            symbol="INFY",
            company="Infosys",
            headline="Acquisition announcement from 48h ago",
            category="M&A",
            materiality="HIGH",
            materiality_score=9.0,
            filing_datetime=now - timedelta(hours=48),
        )
        db_session.add(ann)
        db_session.commit()

        # 24h window should not include it
        r24 = client.get("/api/push/digest?hours=24")
        assert r24.json()["summary"]["total_announcements"] == 0

        # 72h window should include it
        r72 = client.get("/api/push/digest?hours=72")
        assert r72.json()["summary"]["total_announcements"] == 1


# ============================================================================
# 5. Unified Alerts Feed & Acknowledgment (API Tests)
# ============================================================================

class TestUnifiedAlertsAPI:
    def test_list_unified_alerts(self, client, db_session):
        now = datetime.now()
        pa = PriceAlert(
            ticker="HDFCBANK.NS",
            date=date.today(),
            alert_type="volume_spike",
            value=3.2,
            threshold=2.0,
            seen=False,
            created_at=now,
        )
        aa = AnnouncementAlert(
            symbol="HDFCBANK",
            announcement_id=999,
            category="management_change",
            headline="Appointment of Executive Director",
            materiality="HIGH",
            materiality_score=8.0,
            financial_insights_json=json.dumps({"insight_type": "management_change", "insight_summary": "Appointment of Director"}),
            seen=False,
            created_at=now,
        )
        db_session.add_all([pa, aa])
        db_session.commit()

        r = client.get("/api/push/alerts?unseen_only=true")
        assert r.status_code == 200
        alerts = r.json()
        assert len(alerts) == 2

        sources = {a["alert_source"] for a in alerts}
        assert "market_volume" in sources
        assert "corporate_announcement" in sources

    def test_mark_alert_seen_market(self, client, db_session):
        pa = PriceAlert(
            ticker="TEST.NS",
            date=date.today(),
            alert_type="price_move",
            value=7.5,
            threshold=5.0,
            seen=False,
            created_at=datetime.now(),
        )
        db_session.add(pa)
        db_session.commit()

        r = client.patch(f"/api/push/alerts/market/{pa.id}/seen")
        assert r.status_code == 200
        assert r.json()["seen"] is True

        db_session.refresh(pa)
        assert pa.seen is True

    def test_mark_alert_seen_announcement(self, client, db_session):
        aa = AnnouncementAlert(
            symbol="TEST",
            announcement_id=888,
            category="results",
            headline="Q2 Results",
            materiality="HIGH",
            materiality_score=10.0,
            seen=False,
            created_at=datetime.now(),
        )
        db_session.add(aa)
        db_session.commit()

        r = client.patch(f"/api/push/alerts/announcement/{aa.id}/seen")
        assert r.status_code == 200
        assert r.json()["seen"] is True

        db_session.refresh(aa)
        assert aa.seen is True

    def test_evaluate_endpoint(self, client, db_session, sample_portfolio):
        ann = Announcement(
            exchange="NSE",
            symbol="RELIANCE",
            company="Reliance",
            headline="Acquisition of Retail Chain for ₹500 Cr",
            category="M&A",
            materiality="HIGH",
            materiality_score=9.0,
            filing_datetime=datetime.now(),
        )
        db_session.add(ann)
        db_session.commit()

        r = client.post("/api/push/evaluate?hours=24")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["new_announcement_alerts"] >= 1
