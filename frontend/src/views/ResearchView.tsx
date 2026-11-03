import React, { useState, useEffect } from "react"
import {
  Search,
  RefreshCw,
  FileText,
  ShieldCheck,
  AlertTriangle,
  ExternalLink,
  Database,
  Bookmark,
} from "lucide-react"
import {
  api,
  type ResearchReport,
  type DocumentListResponse,
  type CandidateDocument,
  type Citation,
} from "../api/client"
import { CitationModal } from "../components/CitationModal"

interface ResearchViewProps {
  initialTicker?: string
}

const SECTION_KEYS = [
  { id: "business_snapshot",    label: "Business Snapshot",      num: "1" },
  { id: "financial_snapshot",   label: "Financial Snapshot",     num: "2" },
  { id: "trajectory",           label: "Growth Trajectory",      num: "3" },
  { id: "balance_sheet",        label: "Capital Structure",      num: "4" },
  { id: "cash_flow_quality",    label: "Cash Flow Quality",      num: "5" },
  { id: "narrative_vs_numbers", label: "Narrative vs Numbers",   num: "6" },
  { id: "guidance",             label: "Guidance & Outlook",     num: "7" },
  { id: "bull_bear",            label: "Bull vs. Bear Cases",    num: "8" },
]

const POPULAR_TICKERS = ["RELIANCE", "INFY", "TCS", "HDFCBANK", "BAJFINANCE", "TATAMOTORS"]

export const ResearchView: React.FC<ResearchViewProps> = ({ initialTicker }) => {
  const [tickerInput, setTickerInput] = useState(initialTicker || "RELIANCE")
  const [activeTicker, setActiveTicker] = useState(initialTicker || "RELIANCE")
  const [report, setReport] = useState<ResearchReport | null>(null)
  const [docList, setDocList] = useState<DocumentListResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [ingestingUrl, setIngestingUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeSection, setActiveSection] = useState<string>("business_snapshot")

  // Citation Modal state
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)

  // Load existing report & documents for activeTicker
  const loadCompanyResearch = async (ticker: string) => {
    setLoading(true)
    setError(null)
    try {
      // 1. Instantly load local ingested filings and cached report
      const [localDocs, rep] = await Promise.all([
        api.getDocuments(ticker, false).catch(() => null),
        api.getReport(ticker).catch(() => null),
      ])
      if (localDocs) setDocList(localDocs)
      if (rep) setReport(rep)
      setLoading(false)

      // 2. Discover additional candidates in background
      api.getDocuments(ticker, true)
        .then((fullDocs) => {
          if (fullDocs) setDocList(fullDocs)
        })
        .catch(() => null)
    } catch (err: any) {
      setError(err?.message || "Failed to load research data.")
      setLoading(false)
    }
  }

  useEffect(() => {
    if (initialTicker) {
      setTickerInput(initialTicker)
      setActiveTicker(initialTicker)
    }
  }, [initialTicker])

  useEffect(() => {
    loadCompanyResearch(activeTicker)
  }, [activeTicker])

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const clean = tickerInput.trim().toUpperCase().replace(".NS", "").replace(".BO", "")
    if (clean) {
      setActiveTicker(clean)
    }
  }

  const handleGenerateReport = async (forceRefresh = false) => {
    setGenerating(true)
    setError(null)
    try {
      const rep = await api.generateReport(activeTicker, forceRefresh)
      setReport(rep)
      const docs = await api.getDocuments(activeTicker, false)
      setDocList(docs)
    } catch (err: any) {
      setError(err?.message || "Report generation failed. Please ingest at least one primary document first.")
    } finally {
      setGenerating(false)
    }
  }

  const handleIngestCandidate = async (candidate: CandidateDocument) => {
    setIngestingUrl(candidate.canonical_url)
    try {
      await api.ingestDocument({
        ticker: activeTicker,
        document_type: candidate.document_type,
        title: candidate.title,
        canonical_url: candidate.canonical_url,
        period: candidate.period,
      })
      const docs = await api.getDocuments(activeTicker, false)
      setDocList(docs)
      await handleGenerateReport(true)
    } catch (err: any) {
      alert(`Ingestion failed: ${err?.message || "Could not extract PDF."}`)
    } finally {
      setIngestingUrl(null)
    }
  }

  const activeSectionObj = SECTION_KEYS.find((s) => s.id === activeSection) || SECTION_KEYS[0]

  return (
    <div className="space-y-6 pb-20">

      {/* ── Page Header / Search & Command ───────────────────── */}
      <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-sans font-semibold text-emerald-400 uppercase tracking-wider">
                Primary-Source Research (Pull)
              </span>
              <span className="text-slate-600">•</span>
              <span className="text-xs font-sans text-slate-400">
                Zero Hallucinations Engine
              </span>
            </div>
            <h1 className="text-2xl font-sans font-bold text-white tracking-tight">
              Company Research Dossier: {activeTicker}
            </h1>
            <p className="text-sm font-sans text-slate-400 mt-1 max-w-2xl">
              Evidence-grounded analysis strictly synthesized from official Annual Reports, Financial Results, and Earnings Concall Transcripts.
            </p>
          </div>

          {/* Search Form */}
          <form onSubmit={handleSearchSubmit} className="flex items-center gap-2 shrink-0">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Enter NSE Ticker..."
                value={tickerInput}
                onChange={(e) => setTickerInput(e.target.value)}
                className="w-48 sm:w-56 pl-10 pr-3 py-2 bg-slate-900/80 border border-white/[0.08] rounded-xl text-xs font-mono font-semibold text-white uppercase placeholder-slate-400"
              />
            </div>
            <button
              type="submit"
              className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-sans font-semibold transition-all shadow-sm shadow-emerald-950/50"
            >
              Analyze
            </button>
          </form>
        </div>

        {/* Quick Picks Tickers Bar */}
        <div className="flex items-center gap-2 pt-1 flex-wrap">
          <span className="text-xs font-sans text-slate-400 font-medium">
            Quick Coverage:
          </span>
          {POPULAR_TICKERS.map((t) => (
            <button
              key={t}
              onClick={() => {
                setTickerInput(t)
                setActiveTicker(t)
              }}
              className={`px-3 py-1 rounded-lg text-xs font-mono font-medium transition-all border ${
                activeTicker === t
                  ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40 font-bold"
                  : "bg-slate-900/60 border-white/[0.06] text-slate-400 hover:text-white"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* ── Primary Source Filings Repository Drawer ─────────── */}
      <div className="p-5 rounded-2xl bg-[#0d1527] border border-white/[0.08] space-y-4 shadow-xl">
        <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0">
              <Database className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-sans font-bold text-white">
                Primary Source Filings Repository
              </h2>
              <p className="text-xs font-sans text-slate-400">
                Official corporate disclosures indexed into SQLite FTS5 for page-level citation backing
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs font-sans px-2.5 py-1 rounded-full bg-emerald-950/40 text-emerald-400 border border-emerald-500/20 font-medium">
              {docList?.ingested_count ?? 0} Ingested
            </span>
          </div>
        </div>

        {/* Ingested Documents Grid */}
        <div>
          {docList?.ingested_documents && docList.ingested_documents.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {docList.ingested_documents.map((doc) => (
                <div
                  key={doc.id}
                  className="p-3.5 rounded-xl bg-slate-900/70 border border-white/[0.06] flex items-start justify-between gap-3 text-xs"
                >
                  <div className="space-y-1 min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-sans font-semibold px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700/60 uppercase">
                        {doc.document_type.replace(/_/g, " ")}
                      </span>
                      <span className="text-[11px] font-mono text-emerald-400 font-semibold">
                        {doc.total_pages ? `${doc.total_pages} Pages Indexed` : "Indexed"}
                      </span>
                    </div>
                    <h4 className="font-sans font-semibold text-slate-200 line-clamp-1" title={doc.title}>
                      {doc.title}
                    </h4>
                    <div className="flex items-center gap-1.5 text-xs text-emerald-400 font-sans font-medium">
                      <ShieldCheck className="w-3.5 h-3.5" />
                      <span>Verified Official Primary Filing</span>
                    </div>
                  </div>

                  <a
                    href={doc.canonical_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-2 rounded-lg bg-slate-800/80 text-slate-400 hover:text-white border border-slate-700/60 transition-colors shrink-0"
                    title="Open Source PDF Document"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-4 rounded-xl bg-slate-900/30 border border-dashed border-white/[0.08] text-center text-xs font-sans text-slate-400">
              No primary documents ingested yet for {activeTicker}. Select a candidate disclosure below to index.
            </div>
          )}
        </div>

        {/* Discovered Candidate Filings */}
        {docList?.discovered_candidates && docList.discovered_candidates.length > 0 && (
          <div className="pt-2 border-t border-white/[0.06]">
            <span className="text-xs font-sans font-semibold text-slate-400 block mb-2">
              Discovered Candidate Filings ({docList.discovered_candidates.length}):
            </span>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-48 overflow-y-auto pr-1">
              {docList.discovered_candidates.slice(0, 6).map((c, i) => (
                <div
                  key={i}
                  className="p-2.5 rounded-xl bg-slate-900/50 border border-white/[0.05] flex items-center justify-between gap-3 text-xs"
                >
                  <div className="truncate min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-sans px-1.5 py-0.2 rounded bg-slate-800 text-slate-300">
                        {c.document_type.replace(/_/g, " ")}
                      </span>
                      {c.is_verified_primary && (
                        <span className="text-[10px] font-sans text-emerald-400 flex items-center gap-1 font-medium">
                          <ShieldCheck className="w-3 h-3" /> Official
                        </span>
                      )}
                    </div>
                    <span className="text-slate-300 text-xs truncate block mt-0.5 font-sans" title={c.title}>
                      {c.title}
                    </span>
                  </div>

                  <button
                    onClick={() => handleIngestCandidate(c)}
                    disabled={ingestingUrl === c.canonical_url}
                    className="px-3 py-1 rounded-lg bg-emerald-600/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-600/30 text-xs font-sans font-medium shrink-0 transition-colors disabled:opacity-50"
                  >
                    {ingestingUrl === c.canonical_url ? "Extracting..." : "Ingest & Index"}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Research Dossier Report Section ───────────────────── */}
      <div className="p-6 rounded-2xl bg-[#0d1527] border border-white/[0.08] space-y-5 shadow-xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/[0.06] pb-4">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="text-lg font-sans font-bold text-white">
                {activeTicker} Research Dossier
              </span>
              {report?.mode && (
                <span className="text-xs font-sans font-semibold px-2.5 py-0.5 rounded-full bg-emerald-950/40 text-emerald-400 border border-emerald-500/30">
                  {report.mode === "extractive_only" ? "Extractive Evidence Mode" : "LLM Synthesized"}
                </span>
              )}
            </div>
            {report?.generated_at && (
              <p className="text-xs font-sans text-slate-400 mt-1">
                Synthesized at {new Date(report.generated_at).toLocaleString()} • {report.citations?.length || 0} Verifiable Citations
              </p>
            )}
          </div>

          <button
            onClick={() => handleGenerateReport(true)}
            disabled={generating}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-xs font-sans font-medium transition-all border border-white/[0.08] shadow-sm disabled:opacity-50 shrink-0"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${generating ? "animate-spin text-emerald-400" : ""}`} />
            <span>{generating ? "Synthesizing Evidence..." : "Regenerate Dossier"}</span>
          </button>
        </div>

        {/* Error Alert Box */}
        {error && (
          <div className="p-3.5 rounded-xl bg-rose-950/30 border border-rose-500/30 text-xs text-rose-300 font-sans flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Evidence Gaps Honest Disclosure Banner */}
        {report?.evidence_gaps && (
          <div className="p-4 rounded-xl bg-amber-950/20 border border-amber-500/30 text-xs font-sans space-y-1.5">
            <div className="flex items-center gap-2 font-bold text-amber-300 uppercase tracking-wider text-[11px]">
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>Transparent Evidence Coverage & Limitations</span>
            </div>
            <p className="text-amber-200/90 leading-relaxed font-sans">
              {report.evidence_gaps}
            </p>
          </div>
        )}

        {/* Report Sections Navigation Tabs & Reader */}
        {report && report.sections && Object.keys(report.sections).length > 0 ? (
          <div className="space-y-4">
            {/* Section tabs */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {SECTION_KEYS.map((sec) => (
                <button
                  key={sec.id}
                  onClick={() => setActiveSection(sec.id)}
                  className={`p-3 rounded-xl text-left border transition-all text-xs font-sans ${
                    activeSection === sec.id
                      ? "bg-slate-800 border-white/20 text-white font-semibold shadow-sm"
                      : "bg-slate-900/50 border-white/[0.05] text-slate-400 hover:text-white hover:bg-slate-800/40"
                  }`}
                >
                  <span className="text-[10px] text-emerald-400 font-bold block mb-0.5">
                    SECTION {sec.num}
                  </span>
                  <span className="block truncate">{sec.label}</span>
                </button>
              ))}
            </div>

            {/* Active Section Content Viewer */}
            <div className="p-6 rounded-2xl bg-slate-900/70 border border-white/[0.06] space-y-4">
              <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
                <h3 className="font-sans font-bold text-base text-white">
                  {activeSectionObj.num}. {activeSectionObj.label}
                </h3>
                <span className="text-xs font-sans text-slate-400">
                  Click any citation badge to inspect primary filing passage
                </span>
              </div>

              {/* Prose Content */}
              <div className="text-sm text-slate-200 leading-relaxed font-sans whitespace-pre-wrap">
                {report.sections[activeSection] || "No evidence recorded for this section in the ingested filings."}
              </div>

              {/* Citations Bar */}
              <div className="pt-4 border-t border-white/[0.06]">
                <span className="text-xs font-sans font-semibold text-slate-400 block mb-2">
                  Auditable Primary Citations ({report.citations.length} Verified Sources):
                </span>
                <div className="flex items-center gap-2 flex-wrap">
                  {report.citations.map((c, i) => (
                    <button
                      key={i}
                      onClick={() => setSelectedCitation(c)}
                      className="px-2.5 py-1 rounded-lg bg-slate-800/90 border border-white/[0.08] hover:border-emerald-500/50 hover:bg-slate-800 text-emerald-400 text-xs font-mono font-medium flex items-center gap-1.5 transition-colors"
                      title="Inspect Original Document Snippet"
                    >
                      <Bookmark className="w-3 h-3 text-emerald-400" />
                      <span>
                        [Doc #{c.document_id}{c.page_number ? `, p.${c.page_number}` : ""}]
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : loading || generating ? (
          <div className="p-16 text-center text-slate-400 flex flex-col items-center gap-3">
            <RefreshCw className="w-8 h-8 animate-spin text-emerald-400" />
            <p className="text-base font-sans font-semibold text-white">
              Synthesizing Primary Evidence...
            </p>
            <p className="text-xs font-sans text-slate-400">
              Extracting tables, operational guidance, and verifying citation bounds.
            </p>
          </div>
        ) : (
          <div className="p-14 text-center text-slate-400 bg-slate-900/40 rounded-2xl border border-white/[0.06]">
            <FileText className="w-8 h-8 mx-auto text-slate-600 mb-2" />
            <h4 className="text-base font-sans font-bold text-white">
              No Research Dossier Generated Yet
            </h4>
            <p className="text-xs font-sans text-slate-400 max-w-md mx-auto mt-1">
              Ingest an official Annual Report, Quarterly Results presentation, or Concall Transcript above, then click Generate.
            </p>
            <button
              onClick={() => handleGenerateReport(false)}
              className="mt-4 px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-sans font-semibold transition-all shadow-md shadow-emerald-950"
            >
              Generate Research Dossier Now
            </button>
          </div>
        )}
      </div>

      {/* Inspectable Citation Modal */}
      <CitationModal
        citation={selectedCitation}
        onClose={() => setSelectedCitation(null)}
      />
    </div>
  )
}
