"""
Synthetic Primary Document PDF Fixtures for Phase 3 Testing.

Provides valid binary PDF documents representing the three primary source types:
  1. Annual Report (Balance Sheet, Cash Flow, MD&A)
  2. Quarterly Financial Results (Headline figures: Revenue, EBITDA, PBT, PAT)
  3. Earnings-Call Transcript (Management remarks, guidance, Q&A)
  4. Edge cases: Scanned/image-only PDF and corrupted/empty PDF
"""
from __future__ import annotations

import fitz  # PyMuPDF


def create_synthetic_annual_report_pdf(ticker: str = "INFY", company: str = "Infosys Limited") -> bytes:
    doc = fitz.open()

    # Page 1: Business Snapshot & Operational Review
    p1 = doc.new_page()
    p1.insert_text(
        (50, 72),
        f"{company.upper()} — INTEGRATED ANNUAL REPORT FY26\n\n"
        "1. BUSINESS OVERVIEW & OPERATIONAL REVIEW\n"
        f"{company} is a global leader in next-generation digital services and consulting.\n"
        "Key business segments comprise Financial Services (28.4% of revenue), Retail (14.2%), "
        "Communication (12.1%), Energy & Utilities (13.5%), and Manufacturing (14.8%).\n"
        "The digital business now accounts for 63.8% of total enterprise revenues.\n"
        "Customer base expanded to 1,882 active clients with strong expansion across North America and Europe.",
    )

    # Page 2: Financial Snapshot & Multi-Year Trajectory
    p2 = doc.new_page()
    p2.insert_text(
        (50, 72),
        f"{company.upper()} — CONSOLIDATED FINANCIAL PERFORMANCE\n\n"
        "2. FINANCIAL HIGHLIGHTS & TRAJECTORY\n"
        "Consolidated revenue from operations for the full year reached INR 153,670 crore, "
        "representing a YoY growth of 4.7% in constant currency terms.\n"
        "Operating profit (EBITDA) stood at INR 34,200 crore with an operating margin of 22.2%.\n"
        "Profit Before Tax (PBT) reached INR 33,850 crore compared to INR 31,420 crore in the prior year.\n"
        "Profit After Tax (PAT) / Net Profit for the year was INR 26,248 crore, marking an increase of 8.9% YoY.\n"
        "Return on Equity (ROE) stood at 31.8% and Return on Capital Employed (ROCE) was 38.5%.",
    )

    # Page 3: Balance Sheet & Leverage Structure
    p3 = doc.new_page()
    p3.insert_text(
        (50, 72),
        f"{company.upper()} — BALANCE SHEET & CAPITAL STRUCTURE\n\n"
        "3. BALANCE SHEET OBSERVATIONS\n"
        "Total shareholders equity and reserves stood at INR 82,450 crore.\n"
        "Total debt and borrowings remained negligible with a Debt-to-Equity (D/E) ratio of 0.04.\n"
        "The working capital cycle was maintained at 68 days with trade receivables standing at INR 28,140 crore.\n"
        "Cash and cash equivalents plus current liquid investments aggregated to INR 18,340 crore.\n"
        "Contingent liabilities disclosed in the notes totaled INR 3,120 crore primarily regarding disputed direct taxes.",
    )

    # Page 4: Cash Flow Quality & Conversion
    p4 = doc.new_page()
    p4.insert_text(
        (50, 72),
        f"{company.upper()} — CASH FLOW STATEMENT & CONVERSION\n\n"
        "4. CASH FLOW QUALITY & CAPITAL ALLOCATION\n"
        "Cash generated from operations (CFO) was INR 27,650 crore, achieving a cash conversion "
        "ratio of 105.3% relative to net profit (PAT).\n"
        "Capital expenditure (capex) was INR 3,420 crore spent predominantly on technology infrastructure.\n"
        "Free cash flow (FCF) reached INR 24,230 crore, representing a 12.1% YoY increase.\n"
        "The company returned 85% of free cash flow to shareholders via dividends and share buybacks.",
    )

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_quarterly_results_pdf(ticker: str = "INFY", company: str = "Infosys Limited") -> bytes:
    doc = fitz.open()

    p1 = doc.new_page()
    p1.insert_text(
        (50, 72),
        f"{company.upper()} — UNAUDITED FINANCIAL RESULTS FOR Q2 FY27\n\n"
        "HEADLINE QUARTERLY NUMBERS (CONSOLIDATED):\n"
        "1. Revenue from operations: INR 40,986 crore (QoQ growth: +3.8%, YoY growth: +5.1%).\n"
        "2. EBITDA / Operating Profit: INR 9,120 crore; EBITDA Margin: 22.3% (flat QoQ, +20 bps YoY).\n"
        "3. Profit Before Tax (PBT): INR 8,940 crore (QoQ: +4.2%, YoY: +6.0%).\n"
        "4. Profit After Tax (PAT): INR 6,506 crore (QoQ: +4.7%, YoY: +4.7%).\n\n"
        "Large deal TCV (Total Contract Value) signed during the quarter was USD 2.4 billion with 52% net new deals.",
    )

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_concall_transcript_pdf(ticker: str = "INFY", company: str = "Infosys Limited") -> bytes:
    doc = fitz.open()

    # Page 1: Management Opening Remarks & Guidance
    p1 = doc.new_page()
    p1.insert_text(
        (50, 72),
        f"{company.upper()} — EARNINGS CONFERENCE CALL TRANSCRIPT (Q2 FY27)\n\n"
        "MANAGEMENT OPENING REMARKS:\n"
        "CEO Statement: 'We delivered broad-based revenue growth of 3.8% QoQ in constant currency. "
        "Our digital transformation programs and generative AI platforms saw accelerated client adoption.'\n\n"
        "OFFICIAL GUIDANCE:\n"
        "1. Revenue Guidance: Revised FY27 constant currency revenue growth target upward to 3.75% – 4.50% (from 3.0% – 4.0%).\n"
        "2. Operating Margin Guidance: Retained FY27 operating margin guidance range at 20.0% – 22.0%.\n"
        "3. Capex Guidance: Full-year FY27 capex guided between INR 3,500 crore to INR 4,000 crore.",
    )

    # Page 2: Analyst Q&A on Narrative vs Numbers & Risks
    p2 = doc.new_page()
    p2.insert_text(
        (50, 72),
        f"{company.upper()} — ANALYST QUESTION & ANSWER SESSION\n\n"
        "Analyst Question (Kotak Equities): 'How are you tracking delivery against the hiring and discretionary spending commentary?'\n"
        "CFO Response: 'Discretionary spend in banking and retail remained cautious, but our cost-optimization programs "
        "delivered 80 bps of margin expansion, offsetting wage hikes.'\n\n"
        "BULL CONSIDERATIONS:\n"
        "- Strong deal pipeline with large deal TCV at USD 2.4 billion.\n"
        "- High cash generation and robust balance sheet with zero net debt.\n\n"
        "BEAR CONSIDERATIONS:\n"
        "- Macroeconomic softness in European retail and telecommunications sectors.\n"
        "- Lengthening decision-making cycles on uncommitted advisory consulting contracts.",
    )

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_scanned_image_pdf() -> bytes:
    """Creates a PDF with zero text (simulating a scanned image document)."""
    doc = fitz.open()
    doc.new_page()  # Blank page with no text
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
