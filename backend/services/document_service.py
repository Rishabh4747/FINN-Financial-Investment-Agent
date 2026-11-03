"""
Primary Document Ingestion & Extraction Service.

Discovers, downloads, extracts, and validates primary corporate disclosures:
  1. Annual Reports (AR)
  2. Quarterly Financial Results
  3. Earnings-Call Transcripts

Follows strict guidelines:
  - Official primary filings only (exchange filings, company IR sites).
  - No broker reports, no news articles, no model hallucinations.
  - Page-by-page text extraction via pdfplumber.
  - Transparent tracking of extraction status: 'extracted', 'partial', 'scanned_image_only', 'failed'.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import pdfplumber
import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from config import get_settings, get_documents_dir
from db.models import Announcement, SourceDocument
from services.retrieval_service import index_document_chunks

logger = logging.getLogger(__name__)
settings = get_settings()

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
}

MAX_PDF_PAGES = 50  # Cap per document to bound memory/CPU usage
MAX_DOWNLOAD_BYTES = 35 * 1024 * 1024  # 35 MB limit


# ---------------------------------------------------------------------------
# Source Verification Helpers
# ---------------------------------------------------------------------------

OFFICIAL_DOMAINS = (
    "nseindia.com",
    "bseindia.com",
    "nsearchives.nseindia.com",
    "ril.com",
    "infosys.com",
    "tcs.com",
    "hdfcbank.com",
    "icicibank.com",
    "tatamotors.com",
    "marutisuzuki.com",
    "sunpharma.com",
    "drreddys.com",
    "titancompany.in",
    "pidilite.com",
    "adaniports.com",
    "powergrid.in",
    "nestle.in",
    "bajajfinserv.in",
    "bajajfinance.in",
)


def verify_source_origin(url: str) -> tuple[bool, str, str]:
    """
    Checks whether a canonical URL originates from a recognized official exchange
    or company investor relations domain.
    Returns (is_verified_primary, source_origin, verification_notes).
    """
    if not url:
        return False, "unknown", "Empty URL provided."

    try:
        domain = urlparse(url).netloc.lower()
        # Remove port if present
        domain = domain.split(":")[0]

        if any(domain.endswith(d) or domain == d for d in ("nseindia.com", "nsearchives.nseindia.com", "bseindia.com")):
            return True, "exchange_filing", f"Verified official exchange filing hosted on {domain}."

        if any(domain.endswith(d) or domain == d for d in OFFICIAL_DOMAINS):
            return True, "official_ir", f"Verified official corporate investor relations domain ({domain})."

        if "screener.in" in domain:
            return False, "screener_link", "Aggregator reference link; canonical PDF must be inspected directly."

        return False, "unverified_web", f"Third-party or unverified domain ({domain}); primary status unconfirmed."
    except Exception as exc:
        return False, "unknown", f"Error parsing domain: {exc}"


# ---------------------------------------------------------------------------
# Discovery Engine
# ---------------------------------------------------------------------------

def clean_ticker_symbol(ticker: str) -> str:
    """Normalizes 'RELIANCE.NS', 'RELIANCE.BO', or 'RELIANCE' to clean root symbol 'RELIANCE'."""
    return ticker.strip().upper().replace(".NS", "").replace(".BO", "")


def discover_sources_for_ticker(
    ticker: str,
    db: Optional[Session] = None,
    timeout: int = 10,
) -> list[dict[str, Any]]:
    """
    Discovers primary document candidates for a given ticker:
      1. Exchange filings in local announcements table (results, concalls)
      2. Official annual reports & transcripts linked on screener.in
    """
    clean_sym = clean_ticker_symbol(ticker)
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    # 1. Discover from ingested exchange announcements in SQLite if session available
    if db:
        ann_filings = (
            db.query(Announcement)
            .filter(
                Announcement.symbol == clean_sym,
                Announcement.pdf_url.isnot(None),
                Announcement.category.in_(["results", "earnings_call"]),
            )
            .order_by(Announcement.created_at.desc())
            .limit(5)
            .all()
        )
        for ann in ann_filings:
            if not ann.pdf_url or ann.pdf_url in seen_urls:
                continue
            seen_urls.add(ann.pdf_url)

            doc_type = "quarterly_result" if ann.category == "results" else "earnings_call"
            is_verified, origin, notes = verify_source_origin(ann.pdf_url)
            candidates.append({
                "ticker": clean_sym,
                "document_type": doc_type,
                "title": f"{ann.company or clean_sym} - {ann.headline}",
                "period": ann.filing_dt or "Recent Filing",
                "canonical_url": ann.pdf_url,
                "source_origin": origin,
                "is_verified_primary": is_verified,
                "verification_notes": notes,
            })

    # 2. Discover from company fundamental page
    screener_url = f"https://www.screener.in/company/{clean_sym}/"
    try:
        resp = requests.get(screener_url, headers=DEFAULT_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                text = a_tag.get_text(strip=True)
                lower_text = text.lower()
                lower_href = href.lower()

                if not (href.startswith("http://") or href.startswith("https://")):
                    continue
                if href in seen_urls:
                    continue

                doc_type: Optional[str] = None
                period: Optional[str] = None

                if "annual report" in lower_text or "annual report" in lower_href:
                    doc_type = "annual_report"
                    # Extract year if present, e.g. 2026, 2025
                    year_match = re.search(r"202\d", text + " " + href)
                    period = f"FY{year_match.group(0)}" if year_match else "Annual"
                elif "transcript" in lower_text or "concall" in lower_text:
                    doc_type = "earnings_call"
                    period = "Concall Transcript"
                elif "results" in lower_text and ".pdf" in lower_href:
                    doc_type = "quarterly_result"
                    period = "Financial Results"

                if doc_type:
                    seen_urls.add(href)
                    is_verified, origin, notes = verify_source_origin(href)
                    candidates.append({
                        "ticker": clean_sym,
                        "document_type": doc_type,
                        "title": f"{clean_sym} - {text or doc_type.replace('_', ' ').title()}",
                        "period": period,
                        "canonical_url": href,
                        "source_origin": origin,
                        "is_verified_primary": is_verified,
                        "verification_notes": notes,
                    })
    except Exception as exc:
        logger.warning(f"Source discovery request for {clean_sym} encountered error: {exc}")

    return candidates


# ---------------------------------------------------------------------------
# PDF Text Extraction
# ---------------------------------------------------------------------------

def extract_pdf_pages(
    pdf_bytes: bytes,
    max_pages: int = MAX_PDF_PAGES,
) -> tuple[list[tuple[int, str]], str]:
    """
    Extracts page-by-page text using pdfplumber.
    Returns ([(page_num, text)], extraction_status).
    extraction_status is one of:
      - 'extracted' (normal text extracted)
      - 'partial' (some pages empty/unreadable)
      - 'scanned_image_only' (0 text extracted across pages)
      - 'failed' (invalid or corrupted PDF)
    """
    if not pdf_bytes or len(pdf_bytes) < 30:
        return [], "failed"

    pages_text: list[tuple[int, str]] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total_pdf_pages = len(pdf.pages)
            pages_to_read = min(total_pdf_pages, max_pages)

            empty_pages = 0
            for idx in range(pages_to_read):
                page = pdf.pages[idx]
                page_num = idx + 1
                try:
                    text = page.extract_text() or ""
                    cleaned = " ".join(text.split())
                    if cleaned:
                        pages_text.append((page_num, cleaned))
                    else:
                        empty_pages += 1
                except Exception as page_exc:
                    logger.debug(f"Error on page {page_num}: {page_exc}")
                    empty_pages += 1

            if not pages_text:
                return [], "scanned_image_only"

            if empty_pages > 0 and len(pages_text) > 0:
                return pages_text, "partial"

            return pages_text, "extracted"
    except Exception as exc:
        logger.warning(f"PDF extraction failed: {exc}")
        return [], "failed"


# ---------------------------------------------------------------------------
# Document Ingestion Engine
# ---------------------------------------------------------------------------

def ingest_document(
    db: Session,
    doc_meta: dict[str, Any],
    pdf_bytes: Optional[bytes] = None,
    timeout: int = 15,
) -> SourceDocument:
    """
    Ingests a single primary document:
      1. Downloads PDF if bytes not already provided.
      2. Validates origin & size limits.
      3. Extracts page-by-page text.
      4. Stores SourceDocument record.
      5. Indexes chunks into SQLite FTS5 for evidence retrieval.
    """
    ticker = clean_ticker_symbol(doc_meta["ticker"])
    canonical_url = doc_meta["canonical_url"].strip()
    document_type = doc_meta.get("document_type", "annual_report")
    title = doc_meta.get("title", f"{ticker} Document")

    # Generate stable deduplication key
    dedup_raw = f"{ticker}_{document_type}_{canonical_url}"
    dedup_key = hashlib.sha256(dedup_raw.encode("utf-8")).hexdigest()[:32]

    # Check if already ingested
    existing = db.query(SourceDocument).filter(SourceDocument.dedup_key == dedup_key).first()
    if existing:
        logger.info(f"Document already ingested: {title} (ID: {existing.id})")
        return existing

    # Origin verification
    is_verified, origin, notes = verify_source_origin(canonical_url)

    # Fetch content if not passed directly
    status = "pending"
    pages_text: list[tuple[int, str]] = []

    # Check if raw PDF binary is already cached on persistent disk
    disk_pdf_path = get_documents_dir() / f"{ticker}_{dedup_key}.pdf"
    if pdf_bytes is None and disk_pdf_path.exists():
        try:
            pdf_bytes = disk_pdf_path.read_bytes()
            logger.info(f"Loaded existing document binary from persistent disk: {disk_pdf_path}")
        except Exception as exc:
            logger.warning(f"Could not read cached PDF from disk {disk_pdf_path}: {exc}")

    if pdf_bytes is None:
        try:
            resp = requests.get(canonical_url, headers=DEFAULT_HEADERS, timeout=timeout)
            if resp.status_code == 200:
                if len(resp.content) > MAX_DOWNLOAD_BYTES:
                    status = "failed"
                    notes += f" Download exceeded {MAX_DOWNLOAD_BYTES // (1024*1024)}MB size limit."
                else:
                    pdf_bytes = resp.content
            else:
                status = "failed"
                notes += f" Upstream returned HTTP {resp.status_code}."
        except requests.Timeout:
            status = "failed"
            notes += " Download timed out."
        except Exception as exc:
            status = "failed"
            notes += f" Download failed: {str(exc)}"

    if pdf_bytes and status != "failed":
        # Ensure document is saved to persistent disk
        if not disk_pdf_path.exists():
            try:
                disk_pdf_path.write_bytes(pdf_bytes)
                logger.info(f"Saved primary document PDF to persistent disk: {disk_pdf_path}")
            except Exception as exc:
                logger.warning(f"Could not persist PDF to disk: {exc}")

        pages_text, status = extract_pdf_pages(pdf_bytes)
        if status == "scanned_image_only":
            notes += " Document appears to be a scanned image PDF; text extraction yielded no selectable text."

    # Assemble raw text summary
    combined_raw = "\n\n".join(f"--- Page {p} ---\n{txt}" for p, txt in pages_text) if pages_text else None

    # Persist SourceDocument
    doc_record = SourceDocument(
        ticker=ticker,
        document_type=document_type,
        title=title,
        period=doc_meta.get("period"),
        doc_date=doc_meta.get("doc_date"),
        canonical_url=canonical_url,
        source_origin=origin,
        is_verified_primary=is_verified,
        verification_notes=notes,
        extraction_status=status,
        total_pages=len(pages_text),
        raw_text=combined_raw,
        dedup_key=dedup_key,
    )
    db.add(doc_record)
    db.commit()
    db.refresh(doc_record)

    # Index chunks if extraction succeeded
    if pages_text and status in ("extracted", "partial"):
        chunk_count = index_document_chunks(db, doc_record, pages_text)
        logger.info(f"Ingested {title}: {len(pages_text)} pages, {chunk_count} chunks indexed.")

    return doc_record
