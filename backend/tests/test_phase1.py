"""
Phase 1 test suite for FINN backend.

Tests are grouped into three layers:
  1. DB layer  — table creation, schema, seed
  2. yfinance service — live fetch (network), enrichment, upsert, alert logic
  3. API layer — FastAPI endpoints via TestClient (no network for portfolio/prices GET)

Run with:
  cd D:/Assignment/backend
  python -m pytest tests/test_phase1.py -v

Network tests are marked @pytest.mark.network and will fail if run without
internet access. All other tests use an isolated in-memory SQLite DB.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

# ── Path setup ──────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import Base
from db.models import PortfolioCompany, PriceSnapshot, PriceAlert
from services.seed_service import seed_portfolio
from services.yfinance_service import (
    _enrich,
    _evaluate_alerts,
    _upsert_snapshots,
    _safe_float,
    _safe_int,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def mem_engine():
    """Fresh in-memory SQLite engine per test."""
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
def seeded_db(db_session):
    """DB session pre-populated with portfolio seed data."""
    seed_portfolio(db_session)
    return db_session


@pytest.fixture(scope="function")
def test_company(db_session) -> PortfolioCompany:
    """A single test company for alert/snapshot tests."""
    c = PortfolioCompany(
        ticker="TEST.NS",
        name="Test Co Ltd",
        exchange="NSE",
        sector="Testing",
        vol_alert_mult=2.0,
        price_alert_pct=5.0,
    )
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def sample_price_df() -> pd.DataFrame:
    """10 days of fake OHLCV data for a single ticker."""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(9, -1, -1)]
    return pd.DataFrame(
        {
            "open":   [100.0 + i for i in range(10)],
            "high":   [105.0 + i for i in range(10)],
            "low":    [95.0  + i for i in range(10)],
            "close":  [102.0 + i for i in range(10)],
            "volume": [1_000_000 + i * 10_000 for i in range(10)],
        },
        index=dates,
    )


# ============================================================================
# 1. DB layer tests
# ============================================================================

class TestDatabaseSchema:
    def test_all_tables_created(self, mem_engine):
        """All five ORM tables must exist after create_all."""
        from sqlalchemy import inspect
        insp = inspect(mem_engine)
        tables = set(insp.get_table_names())
        expected = {
            "portfolio_companies",
            "price_snapshots",
            "price_alerts",
            "announcements",
            "research_cache",
        }
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_price_snapshots_unique_constraint(self, db_session, test_company):
        """Inserting duplicate (ticker, date) should raise IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        snap1 = PriceSnapshot(ticker="TEST.NS", date=date.today(), close=100.0)
        snap2 = PriceSnapshot(ticker="TEST.NS", date=date.today(), close=200.0)
        db_session.add(snap1)
        db_session.commit()
        db_session.add(snap2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_portfolio_company_ticker_unique(self, db_session, test_company):
        """Duplicate tickers should raise IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        dup = PortfolioCompany(
            ticker="TEST.NS", name="Dup", exchange="NSE", sector="Testing"
        )
        db_session.add(dup)
        with pytest.raises(IntegrityError):
            db_session.commit()


class TestSeedPortfolio:
    def test_seed_inserts_15_companies(self, seeded_db):
        count = seeded_db.query(PortfolioCompany).count()
        assert count == 15, f"Expected 15 seeded companies, got {count}"

    def test_seed_is_idempotent(self, seeded_db):
        """Calling seed_portfolio again should insert 0 additional rows."""
        n = seed_portfolio(seeded_db)
        assert n == 0
        count = seeded_db.query(PortfolioCompany).count()
        assert count == 15

    def test_all_tickers_end_with_exchange_suffix(self, seeded_db):
        companies = seeded_db.query(PortfolioCompany).all()
        for c in companies:
            assert c.ticker.endswith(".NS") or c.ticker.endswith(".BO"), (
                f"{c.ticker} missing exchange suffix"
            )

    def test_all_companies_active_by_default(self, seeded_db):
        inactive = (
            seeded_db.query(PortfolioCompany)
            .filter(PortfolioCompany.is_active == False)
            .count()
        )
        assert inactive == 0

    def test_default_thresholds_are_positive(self, seeded_db):
        companies = seeded_db.query(PortfolioCompany).all()
        for c in companies:
            assert c.vol_alert_mult > 0, f"{c.ticker}: vol_alert_mult must be > 0"
            assert c.price_alert_pct > 0, f"{c.ticker}: price_alert_pct must be > 0"

    def test_portfolio_json_is_valid(self):
        """The seed file must be parseable and contain required keys."""
        path = BACKEND_DIR / "data" / "portfolio.json"
        assert path.exists(), "portfolio.json not found"
        data = json.loads(path.read_text(encoding="utf-8"))
        required_keys = {"ticker", "name", "exchange", "sector"}
        for item in data:
            missing = required_keys - set(item.keys())
            assert not missing, f"portfolio.json entry missing keys: {missing} — {item}"


# ============================================================================
# 2. yfinance service — unit tests (no network)
# ============================================================================

class TestEnrich:
    def test_avg_vol_20d_computed(self, sample_price_df):
        enriched = _enrich(sample_price_df)
        assert "avg_vol_20d" in enriched.columns
        assert enriched["avg_vol_20d"].notna().all()

    def test_pct_change_first_row_is_nan(self, sample_price_df):
        enriched = _enrich(sample_price_df)
        assert pd.isna(enriched["pct_change"].iloc[0])

    def test_pct_change_positive_for_rising_prices(self, sample_price_df):
        enriched = _enrich(sample_price_df)
        # All closes are strictly increasing so all non-NaN pct_change should be > 0
        non_nan = enriched["pct_change"].dropna()
        assert (non_nan > 0).all(), f"Expected all positive pct_change, got:\n{non_nan}"

    def test_custom_window(self, sample_price_df):
        enriched = _enrich(sample_price_df, window=5)
        # With min_periods=1, all rows should have avg_vol_20d
        assert enriched["avg_vol_20d"].notna().all()


class TestUpsertSnapshots:
    def test_upsert_inserts_rows(self, db_session, test_company, sample_price_df):
        enriched = _enrich(sample_price_df)
        count = _upsert_snapshots(db_session, "TEST.NS", enriched)
        db_session.commit()
        assert count == 10
        stored = db_session.query(PriceSnapshot).filter(
            PriceSnapshot.ticker == "TEST.NS"
        ).count()
        assert stored == 10

    def test_upsert_is_idempotent(self, db_session, test_company, sample_price_df):
        """Running upsert twice should not duplicate rows."""
        enriched = _enrich(sample_price_df)
        _upsert_snapshots(db_session, "TEST.NS", enriched)
        db_session.commit()
        _upsert_snapshots(db_session, "TEST.NS", enriched)
        db_session.commit()
        stored = db_session.query(PriceSnapshot).filter(
            PriceSnapshot.ticker == "TEST.NS"
        ).count()
        assert stored == 10  # not 20

    def test_upsert_updates_existing_close(self, db_session, test_company, sample_price_df):
        """Upsert should overwrite the close price if run again with different data."""
        enriched = _enrich(sample_price_df)
        _upsert_snapshots(db_session, "TEST.NS", enriched)
        db_session.commit()

        # Modify closes and upsert again
        modified = sample_price_df.copy()
        modified["close"] = modified["close"] + 999.0
        modified_enriched = _enrich(modified)
        _upsert_snapshots(db_session, "TEST.NS", modified_enriched)
        db_session.commit()

        first_snap = (
            db_session.query(PriceSnapshot)
            .filter(PriceSnapshot.ticker == "TEST.NS")
            .order_by(PriceSnapshot.date)
            .first()
        )
        # Original close[0] was 102.0; after update it should be 102.0 + 999 = 1101.0
        assert first_snap.close == pytest.approx(1101.0, abs=0.01)


class TestAlertEvaluation:
    def _make_latest(self, pct_change: float, volume: float, avg_vol: float) -> pd.Series:
        today = date.today()
        return pd.Series(
            {"pct_change": pct_change, "volume": volume, "avg_vol_20d": avg_vol},
            name=today,
        )

    def test_price_alert_triggered(self, db_session, test_company):
        """A 6% move should trigger a price_move alert (threshold 5%)."""
        latest = self._make_latest(pct_change=6.0, volume=1_000_000, avg_vol=1_000_000)
        n = _evaluate_alerts(db_session, "TEST.NS", latest, test_company)
        db_session.commit()
        assert n >= 1
        alert = db_session.query(PriceAlert).filter(
            PriceAlert.ticker == "TEST.NS",
            PriceAlert.alert_type == "price_move",
        ).first()
        assert alert is not None
        assert alert.value == pytest.approx(6.0)

    def test_price_alert_negative_move(self, db_session, test_company):
        """A -7% move should also trigger (abs check)."""
        latest = self._make_latest(pct_change=-7.0, volume=500_000, avg_vol=1_000_000)
        n = _evaluate_alerts(db_session, "TEST.NS", latest, test_company)
        db_session.commit()
        assert n >= 1

    def test_volume_spike_alert_triggered(self, db_session, test_company):
        """3× average volume should trigger volume_spike (threshold 2×)."""
        latest = self._make_latest(pct_change=1.0, volume=3_000_000, avg_vol=1_000_000)
        n = _evaluate_alerts(db_session, "TEST.NS", latest, test_company)
        db_session.commit()
        alert = db_session.query(PriceAlert).filter(
            PriceAlert.ticker == "TEST.NS",
            PriceAlert.alert_type == "volume_spike",
        ).first()
        assert alert is not None
        assert alert.value == pytest.approx(3.0)

    def test_no_alert_within_thresholds(self, db_session, test_company):
        """3% move and 1.5× volume should not trigger any alert."""
        latest = self._make_latest(pct_change=3.0, volume=1_500_000, avg_vol=1_000_000)
        n = _evaluate_alerts(db_session, "TEST.NS", latest, test_company)
        db_session.commit()
        assert n == 0

    def test_alert_deduplication(self, db_session, test_company):
        """Running evaluate_alerts twice for the same ticker+date should not double-insert."""
        latest = self._make_latest(pct_change=8.0, volume=1_000_000, avg_vol=1_000_000)
        _evaluate_alerts(db_session, "TEST.NS", latest, test_company)
        db_session.commit()
        _evaluate_alerts(db_session, "TEST.NS", latest, test_company)
        db_session.commit()
        count = db_session.query(PriceAlert).filter(
            PriceAlert.ticker == "TEST.NS",
            PriceAlert.alert_type == "price_move",
        ).count()
        assert count == 1


class TestSafeConversions:
    def test_safe_float_normal(self):
        assert _safe_float(1.5) == pytest.approx(1.5)

    def test_safe_float_nan(self):
        assert _safe_float(float("nan")) is None

    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_safe_int_normal(self):
        assert _safe_int(1_234_567.9) == 1_234_567

    def test_safe_int_nan(self):
        assert _safe_int(float("nan")) is None


# ============================================================================
# 3. API layer tests (FastAPI TestClient — no network)
# ============================================================================

class TestAPIHealth:
    def test_health_returns_ok(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as client:
            r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["phases"]["1_backend_skeleton"] == "complete"

    def test_openapi_schema_loads(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as client:
            r = client.get("/openapi.json")
        assert r.status_code == 200


class TestPortfolioAPI:
    """Uses TestClient with an isolated in-memory DB injected via dependency override."""

    @pytest.fixture(autouse=True)
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        from db.database import get_db
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool
        from sqlalchemy.orm import sessionmaker

        eng = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=eng)
        Session = sessionmaker(bind=eng)
        self._session_factory = Session

        # Seed once for the in-memory database
        with Session() as s:
            seed_portfolio(s)

        def override_get_db():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            self._client = c
            yield c
        app.dependency_overrides.clear()

    def test_list_companies_returns_15(self):
        r = self._client.get("/api/portfolio/companies")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 15

    def test_list_companies_schema(self):
        r = self._client.get("/api/portfolio/companies")
        first = r.json()[0]
        for key in ("id", "ticker", "name", "exchange", "sector", "is_active",
                    "vol_alert_mult", "price_alert_pct"):
            assert key in first, f"Missing key '{key}' in company response"

    def test_get_prices_returns_list(self):
        """Before any refresh, all companies should return data_status='no_data'."""
        r = self._client.get("/api/portfolio/prices")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 15

    def test_get_prices_no_data_status_before_refresh(self):
        r = self._client.get("/api/portfolio/prices")
        statuses = {item["data_status"] for item in r.json()}
        # Before a refresh all must be 'no_data'
        assert statuses == {"no_data"}, f"Unexpected statuses: {statuses}"

    def test_get_prices_schema(self):
        r = self._client.get("/api/portfolio/prices")
        first = r.json()[0]
        for key in ("ticker", "name", "sector", "data_status", "data_source"):
            assert key in first, f"Missing key '{key}' in price response"

    def test_add_and_delete_company(self):
        payload = {
            "ticker": "WIPRO.NS",
            "name": "Wipro Ltd",
            "exchange": "NSE",
            "sector": "IT Services",
            "vol_alert_mult": 2.5,
            "price_alert_pct": 4.0,
        }
        r = self._client.post("/api/portfolio/companies", json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["ticker"] == "WIPRO.NS"

        # Soft-delete
        r2 = self._client.delete("/api/portfolio/companies/WIPRO.NS")
        assert r2.status_code == 204

        # Company still exists but is_active = False
        r3 = self._client.get("/api/portfolio/companies")
        wipro = next((c for c in r3.json() if c["ticker"] == "WIPRO.NS"), None)
        assert wipro is not None
        assert wipro["is_active"] is False

    def test_add_duplicate_company_returns_409(self):
        payload = {
            "ticker": "RELIANCE.NS",
            "name": "Reliance Industries Ltd",
            "exchange": "NSE",
            "sector": "Conglomerate",
        }
        r = self._client.post("/api/portfolio/companies", json=payload)
        assert r.status_code == 409

    def test_update_thresholds(self):
        r = self._client.put(
            "/api/portfolio/companies/INFY.NS",
            json={"price_alert_pct": 3.0, "vol_alert_mult": 3.0},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["price_alert_pct"] == pytest.approx(3.0)
        assert data["vol_alert_mult"] == pytest.approx(3.0)

    def test_update_nonexistent_ticker_returns_404(self):
        r = self._client.put(
            "/api/portfolio/companies/FAKE.NS",
            json={"price_alert_pct": 3.0},
        )
        assert r.status_code == 404

    def test_get_alerts_returns_list(self):
        r = self._client.get("/api/portfolio/alerts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_today_stub_returns_not_implemented(self):
        r = self._client.get("/api/today/announcements")
        assert r.status_code == 200
        assert r.json()["status"] == "not_implemented"

    def test_research_stub_returns_not_implemented(self):
        r = self._client.post("/api/research/report", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "not_implemented"


# ============================================================================
# 4. Live network tests — skipped if no network
# ============================================================================

@pytest.mark.network
class TestYFinanceLive:
    """
    These tests hit Yahoo Finance over the network.
    They are skipped automatically if the network is unavailable.
    Run explicitly with: pytest -m network
    """

    @pytest.fixture(autouse=True)
    def check_network(self):
        import socket
        try:
            socket.setdefaulttimeout(5)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
                ("query1.finance.yahoo.com", 443)
            )
        except OSError:
            pytest.skip("No network access — skipping live yfinance tests.")

    def test_reliance_fetch_returns_data(self):
        import yfinance as yf
        df = yf.download("RELIANCE.NS", period="5d", auto_adjust=True, progress=False)
        assert not df.empty, "yfinance returned empty DataFrame for RELIANCE.NS"

    def test_fetch_and_store_prices_live(self, seeded_db):
        # Note: seeded_db uses the in-memory engine which picks up portfolio.json
        # (with BAJFINANCE.NS replacing TATAMOTORS.NS)
        from services.yfinance_service import fetch_and_store_prices
        result = fetch_and_store_prices(seeded_db)
        # Allow partial success — at least some tickers should return data
        # (market may be closed; EOD data for today may not be available yet)
        total = len(result["success"]) + len(result["no_data"])
        assert total == 15, f"Expected 15 tickers total, got {total}"
        assert len(result["success"]) > 0, (
            f"No tickers returned data. no_data={result['no_data']}"
        )
        # Verify at least one snapshot was stored
        snap_count = seeded_db.query(PriceSnapshot).count()
        assert snap_count > 0

    def test_live_prices_via_api(self):
        """
        End-to-end: call /api/portfolio/prices/refresh, then verify
        /api/portfolio/prices returns 'ok' status for ≥1 ticker.
        """
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as client:
            r = client.post("/api/portfolio/prices/refresh")
            assert r.status_code == 200
            body = r.json()
            assert len(body["success"]) > 0, f"Refresh returned no successes: {body}"
            assert body["snapshots_upserted"] > 0

            # Now prices endpoint should show 'ok' for successful tickers
            r2 = client.get("/api/portfolio/prices")
            assert r2.status_code == 200
            ok_items = [x for x in r2.json() if x["data_status"] == "ok"]
            assert len(ok_items) > 0, "No items with data_status='ok' after refresh"
            # Spot-check one item has a real close price
            first_ok = ok_items[0]
            assert first_ok["close"] is not None
            assert first_ok["close"] > 0
