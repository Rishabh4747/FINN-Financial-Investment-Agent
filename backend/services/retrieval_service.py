"""
Evidence Chunking & Retrieval Service.

Chunks extracted document pages with strict provenance (page number, document title,
canonical URL) and indexes them into SQLite FTS5 for BM25-ranked passage search.

Provides reliable fallback search if FTS5 syntax fails or virtual table is uncompiled.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.models import DocumentChunk, SourceDocument

logger = logging.getLogger(__name__)

CHUNK_TARGET_SIZE = 600   # target characters per chunk
CHUNK_OVERLAP = 100       # overlapping context characters


# ---------------------------------------------------------------------------
# Section Detection
# ---------------------------------------------------------------------------

SECTION_PATTERNS = [
    ("Balance Sheet", re.compile(r"balance\s+sheet|statement\s+of\s+assets", re.IGNORECASE)),
    ("Cash Flow Statement", re.compile(r"cash\s+flows?|cash\s+from\s+operations", re.IGNORECASE)),
    ("Profit and Loss / Income", re.compile(r"statement\s+of\s+profit\s+and\s+loss|revenue\s+from\s+operations", re.IGNORECASE)),
    ("Guidance & Outlook", re.compile(r"guidance|forward\s+looking|outlook|target\s+growth", re.IGNORECASE)),
    ("Management Discussion & Analysis", re.compile(r"management\s+discussion|md&a|operating\s+review", re.IGNORECASE)),
    ("Segment Reporting", re.compile(r"segment\s+(reporting|revenue|results)", re.IGNORECASE)),
    ("Consolidated Financial Statements", re.compile(r"consolidated\s+(financial|results|statements)", re.IGNORECASE)),
    ("Standalone Financial Statements", re.compile(r"standalone\s+(financial|results|statements)", re.IGNORECASE)),
]


def detect_section(text_passage: str) -> Optional[str]:
    """Infers high-level financial section name based on passage content."""
    for name, pattern in SECTION_PATTERNS:
        if pattern.search(text_passage[:300]):
            return name
    return None


# ---------------------------------------------------------------------------
# Chunking Logic
# ---------------------------------------------------------------------------

def chunk_page_text(
    page_number: int,
    text_content: str,
    chunk_size: int = CHUNK_TARGET_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """
    Splits a single page of text into overlapping passages.
    Preserves exact page number and detects section headers.
    """
    clean_text = " ".join(text_content.split())
    if not clean_text:
        return []

    chunks: list[dict[str, Any]] = []
    start = 0
    text_len = len(clean_text)

    while start < text_len:
        end = start + chunk_size
        # Try to break on sentence or space boundary
        if end < text_len:
            space_pos = clean_text.rfind(" ", start + chunk_size // 2, end)
            if space_pos != -1:
                end = space_pos + 1

        passage = clean_text[start:end].strip()
        if passage:
            chunks.append({
                "page_number": page_number,
                "section": detect_section(passage),
                "content": passage,
                "char_count": len(passage),
            })

        if end >= text_len:
            break
        start = max(start + 1, end - overlap)

    return chunks


# ---------------------------------------------------------------------------
# Ingestion & Indexing
# ---------------------------------------------------------------------------

def index_document_chunks(
    db: Session,
    doc: SourceDocument,
    pages_text: list[tuple[int, str]],
) -> int:
    """
    Splits pages into semantic chunks, writes them to document_chunks table,
    and inserts them into the fts_chunks virtual table for BM25 retrieval.
    """
    all_chunks: list[dict[str, Any]] = []
    chunk_idx = 0

    for page_num, text_content in pages_text:
        page_chunks = chunk_page_text(page_num, text_content)
        for chk in page_chunks:
            chk["chunk_index"] = chunk_idx
            chunk_idx += 1
            all_chunks.append(chk)

    if not all_chunks:
        return 0

    # Bulk create DocumentChunk records
    chunk_records: list[DocumentChunk] = []
    for chk in all_chunks:
        record = DocumentChunk(
            document_id=doc.id,
            ticker=doc.ticker,
            chunk_index=chk["chunk_index"],
            page_number=chk["page_number"],
            section=chk["section"],
            content=chk["content"],
            char_count=chk["char_count"],
        )
        chunk_records.append(record)

    db.add_all(chunk_records)
    db.commit()

    # Index into FTS5 virtual table if available
    try:
        fts_values = [
            (rec.id, doc.id, doc.ticker, rec.page_number, rec.content)
            for rec in chunk_records
        ]
        # Execute insert into fts_chunks
        conn = db.connection()
        conn.execute(
            text("""
                INSERT INTO fts_chunks (chunk_id, document_id, ticker, page_number, content)
                VALUES (:chunk_id, :document_id, :ticker, :page_number, :content)
            """),
            [
                {
                    "chunk_id": v[0],
                    "document_id": v[1],
                    "ticker": v[2],
                    "page_number": v[3],
                    "content": v[4],
                }
                for v in fts_values
            ],
        )
        db.commit()
    except Exception as exc:
        logger.debug(f"FTS5 indexing skipped or uncompiled: {exc}")

    return len(chunk_records)


# ---------------------------------------------------------------------------
# Evidence Retrieval
# ---------------------------------------------------------------------------

def search_evidence(
    db: Session,
    ticker: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Retrieves evidence passages relevant to a query for a given ticker.
    Attempts SQLite FTS5 BM25 search first; falls back to SQL keyword search.
    """
    clean_ticker = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    clean_query = query.strip()
    if not clean_query:
        return []

    # Clean query for FTS5 (remove special characters like quotes, colons)
    fts_terms = re.findall(r"\w+", clean_query)
    if not fts_terms:
        return []

    # 1. Attempt FTS5 Search
    try:
        fts_query_str = " OR ".join(fts_terms[:6])
        sql = text("""
            SELECT
                c.id AS chunk_id,
                c.document_id,
                c.ticker,
                c.page_number,
                c.section,
                c.content,
                d.title AS document_title,
                d.canonical_url,
                d.document_type,
                d.period,
                d.is_verified_primary,
                bm25(fts_chunks) AS score
            FROM fts_chunks f
            JOIN document_chunks c ON c.id = f.chunk_id
            JOIN source_documents d ON d.id = c.document_id
            WHERE f.ticker = :ticker AND fts_chunks MATCH :match_query
            ORDER BY bm25(fts_chunks)
            LIMIT :limit
        """)
        rows = db.execute(sql, {"ticker": clean_ticker, "match_query": fts_query_str, "limit": limit}).fetchall()
        if rows:
            return [
                {
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "ticker": r.ticker,
                    "page_number": r.page_number,
                    "section": r.section,
                    "content": r.content,
                    "document_title": r.document_title,
                    "canonical_url": r.canonical_url,
                    "document_type": r.document_type,
                    "period": r.period,
                    "is_verified_primary": bool(r.is_verified_primary),
                    "score": float(r.score),
                }
                for r in rows
            ]
    except Exception as exc:
        logger.debug(f"FTS5 query failed, trying fallback: {exc}")

    # 2. Fallback: SQL LIKE across top keywords
    top_term = fts_terms[0]
    fallback_records = (
        db.query(DocumentChunk, SourceDocument)
        .join(SourceDocument, SourceDocument.id == DocumentChunk.document_id)
        .filter(
            DocumentChunk.ticker == clean_ticker,
            DocumentChunk.content.ilike(f"%{top_term}%"),
        )
        .limit(limit)
        .all()
    )

    results: list[dict[str, Any]] = []
    for chunk, doc in fallback_records:
        results.append({
            "chunk_id": chunk.id,
            "document_id": doc.id,
            "ticker": chunk.ticker,
            "page_number": chunk.page_number,
            "section": chunk.section,
            "content": chunk.content,
            "document_title": doc.title,
            "canonical_url": doc.canonical_url,
            "document_type": doc.document_type,
            "period": doc.period,
            "is_verified_primary": doc.is_verified_primary,
            "score": 1.0,
        })

    return results
