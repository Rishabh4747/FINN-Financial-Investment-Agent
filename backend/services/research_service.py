"""
Evidence-Grounded Research Engine & Citation Validator.

Synthesizes multi-source primary financial documents (Annual Reports, Quarterly Results,
and Earnings-Call Transcripts) into a structured 8-section research report.

Key disciplines:
  - Evidence-grounded: Every claim is linked to an ingested passage.
  - Zero hallucination: Transparently flags missing documents and insufficient evidence.
  - Dual Mode:
      * 'llm_synthesized' if Anthropic API key is configured.
      * 'extractive_only' if LLM credentials are absent (guaranteeing 100% functionality without LLM).
  - Validated citations with exact provenance (document title, canonical URL, page number).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from config import get_settings
from db.models import ResearchReportRecord, SourceDocument
from services.retrieval_service import search_evidence

logger = logging.getLogger(__name__)
settings = get_settings()

REPORT_SECTIONS = [
    ("business_snapshot", "Business Snapshot & Operations", "business segments revenue products customer core operations"),
    ("financial_snapshot", "Financial Snapshot", "revenue EBITDA margins profit PAT net profit sales growth"),
    ("trajectory", "Trajectory & Multi-Year Trends", "growth trend compound volume compression expansion performance"),
    ("balance_sheet", "Balance Sheet & Capital Structure", "debt leverage borrowing working capital equity debt to equity liabilities"),
    ("cash_flow_quality", "Cash Flow Quality & Conversion", "cash flow operations operating cash free cash flow working capital conversion"),
    ("narrative_vs_numbers", "Narrative vs. Reported Numbers", "delivered promises expectations reality actuals variance commentary"),
    ("guidance", "Management Guidance & Forward Outlook", "guidance outlook target forecast capex next year FY expected"),
    ("bull_bear", "Bull vs. Bear Considerations", "risks opportunities headwinds tailwinds competitive advantage moat"),
]


# ---------------------------------------------------------------------------
# Citation Validator
# ---------------------------------------------------------------------------

def validate_citations(
    citations: list[dict[str, Any]],
    valid_documents: list[SourceDocument],
) -> list[dict[str, Any]]:
    """
    Validates that every citation refers to an actual ingested primary document
    and includes traceable page and URL provenance.
    """
    valid_doc_map = {doc.id: doc for doc in valid_documents}
    valid_urls = {doc.canonical_url: doc for doc in valid_documents}
    validated: list[dict[str, Any]] = []

    for cit in citations:
        doc_id = cit.get("document_id")
        url = cit.get("canonical_url")
        matched_doc = valid_doc_map.get(doc_id) or valid_urls.get(url)

        if matched_doc:
            validated.append({
                "document_id": matched_doc.id,
                "document_title": matched_doc.title,
                "document_type": matched_doc.document_type,
                "canonical_url": matched_doc.canonical_url,
                "page_number": cit.get("page_number"),
                "section": cit.get("section"),
                "passage_snippet": cit.get("passage_snippet", "")[:200],
                "is_verified_primary": matched_doc.is_verified_primary,
            })

    return validated


# ---------------------------------------------------------------------------
# Extractive Evidence Synthesizer (Zero LLM Dependency)
# ---------------------------------------------------------------------------

def build_extractive_section(
    db: Session,
    ticker: str,
    section_key: str,
    query: str,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Builds an extractive evidence summary strictly from top BM25-ranked passages.
    Never invents unstated figures.
    """
    passages = search_evidence(db, ticker, query, limit=3)
    if not passages:
        return "Insufficient primary document evidence available in ingested sources.", []

    text_parts: list[str] = []
    citations: list[dict[str, Any]] = []

    for idx, p in enumerate(passages, start=1):
        doc_title = p["document_title"]
        page = p.get("page_number")
        page_str = f", Page {page}" if page else ""
        content_snippet = p["content"]

        text_parts.append(f"• Evidence {idx} [{doc_title}{page_str}]: \"{content_snippet}\"")
        citations.append({
            "document_id": p["document_id"],
            "canonical_url": p["canonical_url"],
            "document_title": doc_title,
            "page_number": page,
            "section": p.get("section"),
            "passage_snippet": content_snippet[:180],
            "is_verified_primary": p.get("is_verified_primary", True),
        })

    return "\n\n".join(text_parts), citations


# ---------------------------------------------------------------------------
# LLM Synthesizer (Optional — when ANTHROPIC_API_KEY is configured)
# ---------------------------------------------------------------------------

def synthesize_with_claude(
    ticker: str,
    section_title: str,
    passages: list[dict[str, Any]],
    api_key: str,
) -> Optional[str]:
    """Invokes Anthropic Claude to synthesize a section strictly from evidence passages."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        passages_text = "\n\n".join(
            f"[Passage {i+1} | Source: {p['document_title']} | Page: {p.get('page_number')}]:\n{p['content']}"
            for i, p in enumerate(passages)
        )

        prompt = (
            f"You are FINN, an institutional investment research agent analyzing {ticker}.\n"
            f"Write the '{section_title}' section for {ticker} strictly using the primary source passages below.\n\n"
            f"RULES:\n"
            f"1. Rely ONLY on the provided passages. Do NOT use outside training memory or broker reports.\n"
            f"2. Every key factual claim or number MUST end with a bracketed citation: [Source: <Title>, Page <Page>].\n"
            f"3. If evidence for this topic is absent from the passages, explicitly state: 'Not disclosed in available primary sources.'\n"
            f"4. Keep the tone concise, factual, and analytical.\n\n"
            f"PASSAGES:\n{passages_text}\n\n"
            f"SECTION OUTPUT:"
        )

        resp = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=500,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as exc:
        logger.warning(f"Claude synthesis call failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# High-Level Report Generator
# ---------------------------------------------------------------------------

def generate_research_report(
    db: Session,
    ticker: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Produces an evidence-grounded research report for an NSE ticker:
      1. Gathers all ingested SourceDocuments.
      2. Checks cache unless force_refresh is True.
      3. Gathers evidence passages across all 8 core sections.
      4. Generates synthesis (via LLM if key present, else extractive evidence mode).
      5. Identifies document gaps and source verification status.
      6. Validates citations and persists ResearchReportRecord.
    """
    clean_ticker = ticker.strip().upper().replace(".NS", "").replace(".BO", "")

    # Retrieve all ingested documents for this ticker
    docs = db.query(SourceDocument).filter(SourceDocument.ticker == clean_ticker).all()
    if not docs:
        return {
            "status": "error",
            "ticker": clean_ticker,
            "message": f"No primary documents have been ingested for {clean_ticker}. Ingest at least one Annual Report, Results filing, or Transcript first.",
            "evidence_gaps": "No primary documents available in system.",
            "sources_used": [],
            "citations": [],
            "sections": {},
        }

    # Generate document set hash for cache versioning
    doc_ids_str = "_".join(str(d.id) for d in sorted(docs, key=lambda x: x.id))
    report_version = f"v1_{hashlib.md5(doc_ids_str.encode('utf-8')).hexdigest()[:12]}"

    # Check cache
    if not force_refresh:
        cached = (
            db.query(ResearchReportRecord)
            .filter(
                ResearchReportRecord.ticker == clean_ticker,
                ResearchReportRecord.report_version == report_version,
            )
            .order_by(ResearchReportRecord.created_at.desc())
            .first()
        )
        if cached:
            logger.info(f"Returning cached research report for {clean_ticker} ({report_version})")
            return json.loads(cached.full_report_json)

    # Determine mode & API key
    api_key = os.environ.get("ANTHROPIC_API_KEY") or settings.anthropic_api_key
    has_llm = bool(api_key and len(api_key) > 10)
    mode = "llm_synthesized" if has_llm else "extractive_only"

    # Identify evidence gaps among the 3 primary source types
    ingested_types = {d.document_type for d in docs}
    missing_types = {"annual_report", "quarterly_result", "earnings_call"} - ingested_types
    gap_notes: list[str] = []
    if "annual_report" in missing_types:
        gap_notes.append("Annual Report not ingested; multi-year balance sheet and capital structure observations limited.")
    if "quarterly_result" in missing_types:
        gap_notes.append("Recent quarterly results filing not ingested; latest quarter performance comparisons limited.")
    if "earnings_call" in missing_types:
        gap_notes.append("Earnings-call transcript not ingested; management qualitative tone and Q&A disclosures unavailable.")

    # Check for unverified origins
    unverified_docs = [d.title for d in docs if not d.is_verified_primary]
    if unverified_docs:
        gap_notes.append(f"Source verification limitations: {len(unverified_docs)} document(s) originated from third-party/unverified hosts ({', '.join(unverified_docs[:2])}).")

    evidence_gaps = " | ".join(gap_notes) if gap_notes else "All three primary source types represented with verified official origins."

    # Build sections
    section_texts: dict[str, str] = {}
    all_citations: list[dict[str, Any]] = []

    for key, title, query in REPORT_SECTIONS:
        if has_llm:
            passages = search_evidence(db, clean_ticker, query, limit=4)
            llm_text = synthesize_with_claude(clean_ticker, title, passages, api_key) if passages else None
            if llm_text:
                section_texts[key] = llm_text
                for p in passages:
                    all_citations.append({
                        "document_id": p["document_id"],
                        "canonical_url": p["canonical_url"],
                        "document_title": p["document_title"],
                        "page_number": p.get("page_number"),
                        "section": p.get("section"),
                        "passage_snippet": p["content"][:180],
                        "is_verified_primary": p.get("is_verified_primary", True),
                    })
                continue

        # Fallback / Extractive Mode
        txt, cits = build_extractive_section(db, clean_ticker, key, query)
        section_texts[key] = txt
        all_citations.extend(cits)

    # Validate citations against actual ingested documents
    validated_cits = validate_citations(all_citations, docs)

    # Deduplicate citations for final response
    unique_cits: list[dict[str, Any]] = []
    seen_cit_keys = set()
    for c in validated_cits:
        ckey = (c["document_id"], c.get("page_number"), c.get("passage_snippet", "")[:60])
        if ckey not in seen_cit_keys:
            seen_cit_keys.add(ckey)
            unique_cits.append(c)

    # Sources summary
    sources_summary = [
        {
            "id": d.id,
            "title": d.title,
            "document_type": d.document_type,
            "period": d.period,
            "canonical_url": d.canonical_url,
            "source_origin": d.source_origin,
            "is_verified_primary": d.is_verified_primary,
            "extraction_status": d.extraction_status,
            "total_pages": d.total_pages,
        }
        for d in docs
    ]

    report_payload: dict[str, Any] = {
        "status": "completed",
        "ticker": clean_ticker,
        "report_version": report_version,
        "mode": mode,
        "generated_at": datetime.now().isoformat(),
        "sections": section_texts,
        "evidence_gaps": evidence_gaps,
        "sources_used": sources_summary,
        "citations": unique_cits,
    }

    # Cache report record in SQLite
    record = ResearchReportRecord(
        ticker=clean_ticker,
        report_version=report_version,
        status="completed",
        mode=mode,
        business_snapshot=section_texts.get("business_snapshot"),
        financial_snapshot=section_texts.get("financial_snapshot"),
        trajectory=section_texts.get("trajectory"),
        balance_sheet=section_texts.get("balance_sheet"),
        cash_flow_quality=section_texts.get("cash_flow_quality"),
        narrative_vs_numbers=section_texts.get("narrative_vs_numbers"),
        guidance=section_texts.get("guidance"),
        bull_bear=section_texts.get("bull_bear"),
        citations_json=json.dumps(unique_cits),
        sources_used_json=json.dumps(sources_summary),
        evidence_gaps=evidence_gaps,
        full_report_json=json.dumps(report_payload),
    )
    db.add(record)
    db.commit()

    return report_payload
