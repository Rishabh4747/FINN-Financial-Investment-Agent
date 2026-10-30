"""
Announcement Classification & Materiality Scoring Service.

Implements deterministic classification based on the ENAM Build Challenge
Announcement Categories & Financial Glossary document.

Rules are prioritized and explainable:
  - Classification rationale details exactly which pattern matched.
  - Materiality ranking (HIGH, MEDIUM, LOW) and numerical priority score (1.0-10.0)
    reflect structural importance without claiming to predict stock movements.
  - Zero LLM dependency required for basic ingestion.
  - Fallback cleanly to 'unclassified' for routine compliance paperwork.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CategoryRule:
    category: str
    materiality: str       # 'HIGH' | 'MEDIUM' | 'LOW'
    materiality_score: float # 1.0 to 10.0
    materiality_rationale: str
    patterns: tuple[re.Pattern, ...]


# Order matters: more specific categories take precedence over broader ones
# (e.g. "earnings call transcript" matches earnings_call before press_release;
# "board meeting to consider financial results" matches results before agm_egm)
CATEGORY_RULES: list[CategoryRule] = [
    CategoryRule(
        category="results",
        materiality="HIGH",
        materiality_score=10.0,
        materiality_rationale="Quarterly or annual financial results directly reveal top-line revenue, EBITDA margins, and net profitability.",
        patterns=(
            re.compile(r"financial results|quarterly results|annual results|audited results|unaudited results", re.IGNORECASE),
            re.compile(r"financial statement|outcome of board meeting.*results|board meeting.*financial results", re.IGNORECASE),
            re.compile(r"results deck|shareholder letter.*results|unaudited standalone.*results|unaudited consolidated.*results", re.IGNORECASE),
            re.compile(r"period ended.*(financial results|unaudited|audited)", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="M&A",
        materiality="HIGH",
        materiality_score=9.0,
        materiality_rationale="M&A, demerger, or joint venture activities represent structural changes to corporate boundaries and asset portfolio.",
        patterns=(
            re.compile(r"\bacquisition\b|\bmerger\b|\bdemerger\b|\bjoint venture\b|\bamalgamation\b", re.IGNORECASE),
            re.compile(r"slump sale|stake sale|divestment|\btakeover\b|scheme of arrangement", re.IGNORECASE),
            re.compile(r"sale of (shares|stake) in subsidiary|investing in (a )?subsidiary|acquisition of (shares|equity)", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="fund_raise",
        materiality="HIGH",
        materiality_score=8.5,
        materiality_rationale="Capital raising alters equity dilution, balance-sheet leverage, or capital availability.",
        patterns=(
            re.compile(r"fund\s*rais|raising of funds|rights issue|\bqip\b|qualified institutions placement", re.IGNORECASE),
            re.compile(r"preferential allotment|\bbuyback\b|commercial paper|non-convertible debenture|\bncd\b", re.IGNORECASE),
            re.compile(r"issuance of (equity|securities|shares|debentures)|allotment of equity shares.*(qip|rights)", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="management_change",
        materiality="HIGH",
        materiality_score=8.0,
        materiality_rationale="Key leadership transitions (CEO/CFO/MD/Director) directly impact governance and strategic execution.",
        patterns=(
            re.compile(r"(resignation|appointment|cessation|retirement|re-appointment)\s+of.*(ceo|cfo|md|managing director|director|kmp|key managerial)", re.IGNORECASE),
            re.compile(r"change in (management|directorate|kmp|key managerial personnel)", re.IGNORECASE),
            re.compile(r"(ceo|cfo|managing director|executive director|independent director)\s+(resigns|appointed|resigned|step down|retires)", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="litigation",
        materiality="HIGH",
        materiality_score=8.0,
        materiality_rationale="Litigation, regulatory enforcement, or insolvency matters introduce legal liabilities or operational constraints.",
        patterns=(
            re.compile(r"\blitigation\b|regulatory order|penalty imposed|fine imposed|warning letter", re.IGNORECASE),
            re.compile(r"\bnclt\b|\binsolvency\b|\bcirp\b|\barbitration\b|show cause notice|adjudication order", re.IGNORECASE),
            re.compile(r"tax demand|order passed by|summons|search and seizure", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="bonus_split",
        materiality="MEDIUM",
        materiality_score=7.0,
        materiality_rationale="Corporate actions altering share base without direct cash inflow or outflow.",
        patterns=(
            re.compile(r"bonus issue|bonus shares|stock split|sub-division of (equity )?shares|subdivision of shares", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="capex",
        materiality="MEDIUM",
        materiality_score=7.0,
        materiality_rationale="Capital expenditures signal capacity additions and long-term asset investments.",
        patterns=(
            re.compile(r"capital expenditure|\bcapex\b|capacity expansion|setting up of plant", re.IGNORECASE),
            re.compile(r"manufacturing facility|commissioning of plant|commercial production|expansion project|greenfield project", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="dividend",
        materiality="MEDIUM",
        materiality_score=6.5,
        materiality_rationale="Cash dividend declarations determine yield and shareholder return cut-off dates.",
        patterns=(
            re.compile(r"\bdividend\b|interim dividend|final dividend|special dividend|record date for (payment of )?dividend", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="credit_rating",
        materiality="MEDIUM",
        materiality_score=6.5,
        materiality_rationale="Credit ratings reflect institutional assessment of debt service ability and borrowing costs.",
        patterns=(
            re.compile(r"credit rating|rating upgraded|rating downgraded|rating reaffirmed|reaffirmation of rating", re.IGNORECASE),
            re.compile(r"\bcrisil\b|\bicra\b|care ratings?|india ratings|\bcare\b rating|\bind-ra\b", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="insider_trading",
        materiality="MEDIUM",
        materiality_score=6.0,
        materiality_rationale="Promoter and key insider equity transactions provide observable signals on insider ownership.",
        patterns=(
            re.compile(r"insider trading|regulation 7\(2\)|pit regulations|sebi \(pit\)|disclosures under.*pit", re.IGNORECASE),
            re.compile(r"promoter.*(acquisition|disposal|purchase|sale) of shares", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="earnings_call",
        materiality="LOW",
        materiality_score=4.0,
        materiality_rationale="Investor conference call notifications, audio recordings, or transcript publications.",
        patterns=(
            re.compile(r"earnings call|conference call|\bconcall\b|transcript of (the )?(earnings|conference) call", re.IGNORECASE),
            re.compile(r"audio (recording|link).*conference call|investor call transcript", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="investor_meetings",
        materiality="LOW",
        materiality_score=3.5,
        materiality_rationale="Meetings and presentations to institutional investors without selective non-public disclosures.",
        patterns=(
            re.compile(r"investor meet|analyst meet|institutional investor meeting|analysts/institutional investors", re.IGNORECASE),
            re.compile(r"schedule of (analysts|investor)|investor conference|one-on-one meeting", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="pledging",
        materiality="LOW",
        materiality_score=4.5,
        materiality_rationale="Promoter share encumbrance, creation, or release of pledge disclosures.",
        patterns=(
            re.compile(r"\bpledge\b|release of pledge|encumbrance|regulation 31\(1\)|regulation 31\(2\)|sast regulations.*pledge", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="agm_egm",
        materiality="LOW",
        materiality_score=3.0,
        materiality_rationale="Notices, proceedings, and scrutinizer voting results for general meetings of shareholders.",
        patterns=(
            re.compile(r"annual general meeting|extraordinary general meeting|\bagm\b notice|\begm\b notice", re.IGNORECASE),
            re.compile(r"proceedings of (the )?(agm|egm|annual general meeting)|scrutinizer('s)? report.*agm", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="postal_ballot",
        materiality="LOW",
        materiality_score=2.5,
        materiality_rationale="Formal voting through postal ballot and remote e-voting result notifications.",
        patterns=(
            re.compile(r"postal ballot|voting results.*postal ballot|notice of postal ballot", re.IGNORECASE),
        ),
    ),
    CategoryRule(
        category="press_release",
        materiality="MEDIUM",
        materiality_score=5.0,
        materiality_rationale="General news releases, order wins, commercial milestones, or rumor clarifications.",
        patterns=(
            re.compile(r"press release|media release|order win|bagged order|contract awarded|commercial launch", re.IGNORECASE),
            re.compile(r"strategic partnership|rumour clarification|clarification on news", re.IGNORECASE),
        ),
    ),
]


@dataclass
class ClassificationResult:
    category: str
    materiality: str
    materiality_score: float
    materiality_rationale: str
    classification_rationale: str
    classification_confidence: str
    summary: str


def classify_announcement(
    headline: str,
    description: Optional[str] = None,
    company: Optional[str] = None,
) -> ClassificationResult:
    """
    Deterministically classify an announcement based on headline and description.
    Produces full explainability and confidence metadata.
    """
    clean_headline = (headline or "").strip()
    clean_desc = (description or "").strip()
    combined_text = f"{clean_headline} {clean_desc}"

    # Iterate prioritized rules
    for rule in CATEGORY_RULES:
        for pattern in rule.patterns:
            match = pattern.search(combined_text)
            if match:
                matched_kw = match.group(0)
                rationale = f"Matched keyword/phrase '{matched_kw}' in filing text."
                summary = generate_concise_summary(rule.category, clean_headline, clean_desc, company)
                return ClassificationResult(
                    category=rule.category,
                    materiality=rule.materiality,
                    materiality_score=rule.materiality_score,
                    materiality_rationale=rule.materiality_rationale,
                    classification_rationale=rationale,
                    classification_confidence="HIGH",
                    summary=summary,
                )

    # Fallback: unclassified routine compliance
    return ClassificationResult(
        category="unclassified",
        materiality="LOW",
        materiality_score=1.5,
        materiality_rationale="Routine compliance filings, statutory certificates, or standard administrative paperwork.",
        classification_rationale="No high-materiality operational or financial patterns detected; treated as routine exchange compliance.",
        classification_confidence="LOW",
        summary=generate_concise_summary("unclassified", clean_headline, clean_desc, company),
    )


def generate_concise_summary(
    category: str,
    headline: str,
    description: str,
    company: Optional[str] = None,
) -> str:
    """
    Synthesizes a tight, factual 1-line summary strictly from available filing text.
    Never invents undisclosed figures or external information.
    """
    company_name = company or "Company"

    if category == "results":
        if "standalone" in description.lower() and "consolidated" in description.lower():
            return f"{company_name}: Board approved Standalone and Consolidated financial results."
        elif "consolidated" in description.lower():
            return f"{company_name}: Board approved Consolidated financial results."
        elif "standalone" in description.lower():
            return f"{company_name}: Board approved Standalone financial results."
        return f"{company_name}: Financial results filed with the exchange."

    if category == "management_change":
        match = re.search(r"(resignation|appointment|cessation)\s+of\s+([A-Za-z\.\s]+?)(?:,|\sas|\swith)", f"{headline} {description}", re.IGNORECASE)
        if match:
            action, name = match.group(1).title(), match.group(2).strip()
            return f"{company_name}: {action} of {name} notified to the exchange."
        return f"{company_name}: Leadership/Management change notified."

    if category == "dividend":
        return f"{company_name}: Dividend declaration / record date notification."

    if category == "fund_raise":
        return f"{company_name}: Capital raising / securities allotment notification."

    if category == "M&A":
        return f"{company_name}: M&A, acquisition, or corporate restructuring notification."

    if category == "litigation":
        return f"{company_name}: Litigation or regulatory order disclosure."

    # General fallback: clean headline or first 120 chars of description
    if description and len(description) > 10:
        cleaned = " ".join(description.split())
        return cleaned[:140] + ("…" if len(cleaned) > 140 else "")

    cleaned_hl = " ".join(headline.split())
    return cleaned_hl[:140] + ("…" if len(cleaned_hl) > 140 else "")
