import React, { useState, useEffect } from "react"
import {
  RefreshCw,
  Search,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  FileText,
  Clock,
  Sparkles,
  Layers,
  Filter,
} from "lucide-react"
import { api, type PushDigestResponse, type CategoryInfo } from "../api/client"
import { timeAgo } from "../lib/utils"

interface TodayViewProps {
  onSelectTickerForResearch?: (ticker: string) => void
}

export const TodayView: React.FC<TodayViewProps> = ({ onSelectTickerForResearch }) => {
  const [digest, setDigest] = useState<PushDigestResponse | null>(null)
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshStatus, setRefreshStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [hours, setHours] = useState<number>(() => {
    if (typeof window !== "undefined") {
      const param = new URLSearchParams(window.location.search).get("hours")
      if (param !== null) {
        const parsed = parseInt(param, 10)
        if (!isNaN(parsed)) return parsed
      }
    }
    return 24
  })
  const [portfolioOnly, setPortfolioOnly] = useState<boolean>(false)
  const [selectedCategory, setSelectedCategory] = useState<string>("all")
  const [searchQuery, setSearchQuery] = useState<string>("")
  const [expandedItemIds, setExpandedItemIds] = useState<Set<number>>(new Set())
  const [showRoutine, setShowRoutine] = useState<boolean>(false)

  // Developer mode for fixtures
  const [devMode, setDevMode] = useState<boolean>(() => {
    if (typeof window !== "undefined") {
      return (
        window.location.search.includes("dev=1") ||
        window.location.search.includes("fixtures=1") ||
        window.localStorage.getItem("finn_dev") === "1"
      )
    }
    return false
  })
  const [badgeClicks, setBadgeClicks] = useState<number>(0)

  const handleBadgeClick = () => {
    const next = badgeClicks + 1
    if (next >= 3) {
      const toggled = !devMode
      setDevMode(toggled)
      if (typeof window !== "undefined") {
        if (toggled) window.localStorage.setItem("finn_dev", "1")
        else window.localStorage.removeItem("finn_dev")
      }
      setBadgeClicks(0)
    } else {
      setBadgeClicks(next)
      setTimeout(() => setBadgeClicks(0), 1200)
    }
  }

  // Fetch Digest
  const loadDigest = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await api.getPushDigest({
        hours,
        portfolio_only: portfolioOnly,
        category: selectedCategory !== "all" ? selectedCategory : undefined,
      })
      setDigest(data)
    } catch (err: any) {
      setError(err?.message || "Failed to load push digest.")
    } finally {
      setLoading(false)
    }
  }

  // Load Categories metadata once
  useEffect(() => {
    api.getCategories()
      .then(setCategories)
      .catch((err) => console.warn("Failed to load category metadata:", err))
  }, [])

  // Refetch when filters change
  useEffect(() => {
    loadDigest()
  }, [hours, portfolioOnly, selectedCategory])

  // Handle Manual Refresh
  const handleRefresh = async (useFixtures = false) => {
    setRefreshing(true)
    setRefreshStatus(null)
    try {
      const res = await api.refreshAnnouncements(useFixtures)
      setRefreshStatus(res.message)
      await loadDigest()
    } catch (err: any) {
      setRefreshStatus(`Refresh failed: ${err?.message || "Upstream network error"}`)
    } finally {
      setRefreshing(false)
      setTimeout(() => setRefreshStatus(null), 5000)
    }
  }

  const toggleExpand = (id: number) => {
    const next = new Set(expandedItemIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setExpandedItemIds(next)
  }

  // Filter items by search query
  const filteredAnnouncements = (digest?.prioritized_announcements || []).filter((item) => {
    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase()
    return (
      item.symbol.toLowerCase().includes(q) ||
      item.company.toLowerCase().includes(q) ||
      item.headline.toLowerCase().includes(q) ||
      (item.category && item.category.toLowerCase().includes(q))
    )
  })

  return (
    <div className="space-y-6 pb-20">

      {/* ── Page Header & Digest Stats ───────────────────────── */}
      <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span
                onClick={handleBadgeClick}
                className="text-xs font-sans font-semibold text-emerald-400 uppercase tracking-wider cursor-pointer select-none"
                title="Triple-click to toggle developer fixtures"
              >
                Push Intelligence Feed {devMode && <span className="text-amber-400 font-mono">[DEV]</span>}
              </span>
              <span className="text-slate-600">•</span>
              <span className="text-xs font-sans text-slate-400">
                As of {digest?.as_of ? new Date(digest.as_of).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
              </span>
            </div>
            <h1 className="text-2xl font-sans font-bold text-white tracking-tight">
              Today's Market & Corporate Filings
            </h1>
            <p className="text-sm font-sans text-slate-400 mt-1 max-w-2xl">
              Exchange disclosures ranked by explainable SEBI materiality criteria with extracted financial takeaways.
            </p>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => handleRefresh(false)}
              disabled={refreshing}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-sans font-semibold transition-all shadow-sm shadow-emerald-950/50 disabled:opacity-50"
              title="Fetch live disclosures from NSE feed"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
              <span>{refreshing ? "Ingesting..." : "Refresh Feed"}</span>
            </button>
            {devMode && (
              <button
                onClick={() => handleRefresh(true)}
                disabled={refreshing}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-900 border border-amber-500/40 text-amber-400 hover:bg-slate-800 text-xs font-mono transition-all animate-fade-in"
                title="Load verified offline synthetic fixtures (Developer Mode)"
              >
                <Layers className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Fixtures (Dev)</span>
              </button>
            )}
          </div>
        </div>

        {/* Refresh Status Toast */}
        {refreshStatus && (
          <div className="p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/30 text-emerald-300 text-xs font-sans flex items-center gap-2 animate-fade-in">
            <Sparkles className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{refreshStatus}</span>
          </div>
        )}

        {/* Integrated Digest Stats Strip */}
        <div className="p-4 rounded-2xl bg-slate-900/60 border border-white/[0.08] grid grid-cols-2 sm:grid-cols-4 gap-4 divide-y sm:divide-y-0 sm:divide-x divide-white/[0.06]">
          <div className="pt-2 sm:pt-0 sm:px-2">
            <span className="text-xs font-sans text-slate-400 block">Total Filings ({hours}h)</span>
            <span className="text-xl font-sans font-bold text-white mt-0.5 block">
              {digest?.summary.total_announcements ?? "—"}
            </span>
          </div>
          <div className="pt-2 sm:pt-0 sm:px-4">
            <span className="text-xs font-sans text-emerald-400 font-medium block">Prioritized Signals</span>
            <span className="text-xl font-sans font-bold text-emerald-400 mt-0.5 block">
              {digest?.summary.prioritized_count ?? "—"}
            </span>
          </div>
          <div className="pt-2 sm:pt-0 sm:px-4">
            <span className="text-xs font-sans text-slate-400 block">Routine Collapsed</span>
            <span className="text-xl font-sans font-bold text-slate-300 mt-0.5 block">
              {digest?.summary.collapsed_routine_count ?? "—"}
            </span>
          </div>
          <div className="pt-2 sm:pt-0 sm:px-4">
            <span className="text-xs font-sans text-amber-400 font-medium block">Market Anomalies</span>
            <span className="text-xl font-sans font-bold text-amber-400 mt-0.5 block">
              {digest?.summary.triggered_price_alerts_count ?? "—"}
            </span>
          </div>
        </div>
      </div>

      {/* ── Triggered Market Anomalies Ticker (if present) ───── */}
      {digest?.triggered_market_alerts && digest.triggered_market_alerts.length > 0 && (
        <div className="p-4 rounded-2xl bg-amber-950/20 border border-amber-500/30 space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
            <span className="text-xs font-sans font-bold text-amber-300 uppercase tracking-wider">
              Triggered Market Anomalies ({digest.triggered_market_alerts.length})
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
            {digest.triggered_market_alerts.map((alert) => (
              <div
                key={alert.id}
                className="p-3 rounded-xl bg-slate-900/80 border border-amber-500/20 flex items-center justify-between text-xs font-sans"
              >
                <div>
                  <span className="font-mono font-bold text-white text-sm">{alert.ticker}</span>
                  <span className="text-xs text-slate-300 block mt-0.5">
                    {alert.message ||
                      (alert.alert_type === "price_move"
                        ? `${alert.ticker} moved ${alert.value > 0 ? "+" : ""}${alert.value}% (threshold ±${alert.threshold}%)`
                        : `${alert.ticker} volume surged to ${alert.value}× (threshold ${alert.threshold}×)`)}
                  </span>
                </div>
                {alert.alert_type === "price_move" ? (
                  alert.value > 0 ? (
                    <TrendingUp className="w-4 h-4 text-emerald-400 shrink-0 ml-2" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-rose-400 shrink-0 ml-2" />
                  )
                ) : (
                  <Clock className="w-4 h-4 text-amber-400 shrink-0 ml-2" />
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Filter Controls Row ───────────────────────────────── */}
      <div className="p-4 rounded-2xl bg-slate-900/60 border border-white/[0.08] space-y-3">
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
          {/* Horizon toggle pills */}
          <div className="flex items-center p-1 bg-slate-950/70 rounded-xl border border-white/[0.06] shrink-0">
            {[
              { val: 24, label: "24h Window" },
              { val: 48, label: "48h Window" },
              { val: 168, label: "7 Days" },
              { val: 0, label: "All Time" },
            ].map((w) => (
              <button
                key={w.val}
                onClick={() => setHours(w.val)}
                className={`px-3 py-1.5 rounded-lg text-xs font-sans font-medium transition-all ${
                  hours === w.val
                    ? "bg-slate-800 text-white shadow-sm border border-white/10 font-semibold"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>

          {/* Scope Toggle & Search */}
          <div className="flex items-center gap-2 flex-1 max-w-md justify-end">
            <button
              onClick={() => setPortfolioOnly(!portfolioOnly)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-sans font-medium border transition-all shrink-0 ${
                portfolioOnly
                  ? "bg-emerald-600/20 text-emerald-300 border-emerald-500/40"
                  : "bg-slate-950/70 text-slate-400 border-white/[0.06] hover:text-white"
              }`}
            >
              <Filter className="w-3.5 h-3.5" />
              <span>{portfolioOnly ? "Watchlist Only" : "All Coverage"}</span>
            </button>

            <div className="relative flex-1">
              <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search symbol, headline..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-3 py-2 bg-slate-950/70 border border-white/[0.06] rounded-xl text-xs font-sans text-white placeholder-slate-400 transition-colors"
              />
            </div>
          </div>
        </div>

        {/* Category Horizontal Filter Chips */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none pt-1">
          <button
            onClick={() => setSelectedCategory("all")}
            className={`px-3 py-1.5 rounded-lg text-xs font-sans whitespace-nowrap transition-all border ${
              selectedCategory === "all"
                ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40 font-semibold"
                : "bg-slate-950/50 text-slate-400 border-white/[0.06] hover:text-white"
            }`}
          >
            All Categories
          </button>
          {categories.map((c) => (
            <button
              key={c.category}
              onClick={() => setSelectedCategory(c.category)}
              className={`px-3 py-1.5 rounded-lg text-xs font-sans whitespace-nowrap transition-all border flex items-center gap-1.5 ${
                selectedCategory === c.category
                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40 font-semibold"
                  : "bg-slate-950/50 text-slate-400 border-white/[0.06] hover:text-white"
              }`}
            >
              <span>{c.category.replace(/_/g, " ")}</span>
              <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 font-semibold">
                {c.count}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Main Announcement Feed ────────────────────────────── */}
      <div className="space-y-4">
        {loading ? (
          <div className="p-16 text-center text-slate-400 bg-[#0d1527] border border-white/[0.08] rounded-2xl flex flex-col items-center gap-3">
            <RefreshCw className="w-6 h-6 animate-spin text-emerald-400" />
            <p className="text-sm font-sans font-medium text-slate-300">
              Loading prioritized disclosures...
            </p>
          </div>
        ) : error ? (
          <div className="p-10 text-center bg-rose-950/20 border border-rose-800/40 rounded-2xl text-rose-300 text-sm font-sans">
            <AlertTriangle className="w-6 h-6 mx-auto mb-2 text-rose-400" />
            <p className="font-semibold">{error}</p>
            <button
              onClick={loadDigest}
              className="mt-3 px-4 py-1.5 rounded-xl bg-rose-900/40 border border-rose-700 text-rose-200 text-xs font-sans font-medium"
            >
              Retry
            </button>
          </div>
        ) : filteredAnnouncements.length === 0 ? (
          <div className="p-16 text-center text-slate-400 bg-[#0d1527] border border-white/[0.08] rounded-2xl">
            <FileText className="w-8 h-8 mx-auto text-slate-600 mb-2" />
            <p className="text-sm font-sans font-semibold text-slate-200">No filings in selected {hours > 0 ? `${hours}h window` : "filter"}</p>
            <p className="text-xs font-sans text-slate-400 mt-1 max-w-md mx-auto">
              Live corporate disclosures from past days are safely stored in the database.
            </p>
            {hours > 0 && (
              <button
                onClick={() => setHours(0)}
                className="mt-3 px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-emerald-400 font-medium transition-colors"
              >
                Expand to All Time Filings
              </button>
            )}
          </div>
        ) : (
          filteredAnnouncements.map((item) => {
            const isExpanded = expandedItemIds.has(item.id)
            const score = item.materiality_score || 1.0
            const isHigh = score >= 7.0
            const isMedium = score >= 4.0 && score < 7.0
            const insights = item.financial_insights

            return (
              <div
                key={item.id}
                className="bg-[#0d1527] border border-white/[0.08] hover:border-white/[0.14] rounded-2xl p-5 transition-all shadow-md group"
              >
                {/* Header Row: Company, Symbol, Time, Badges */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <button
                      onClick={() => onSelectTickerForResearch?.(item.symbol)}
                      className="font-sans font-bold text-white hover:text-emerald-400 transition-colors text-sm"
                      title="Open in Equity Research Workspace"
                    >
                      {item.company}
                    </button>
                    <span className="font-mono text-xs text-emerald-400 font-semibold px-2 py-0.5 rounded bg-emerald-950/40 border border-emerald-500/20">
                      {item.symbol}
                    </span>
                    <span className="text-slate-600 text-xs">•</span>
                    <span className="text-xs font-sans text-slate-400">
                      {timeAgo(item.filing_datetime)}
                    </span>
                  </div>

                  {/* Priority & Category Badges */}
                  <div className="flex items-center gap-2 shrink-0">
                    <span
                      className={`text-xs font-sans font-semibold px-2.5 py-0.5 rounded-full border ${
                        isHigh
                          ? "bg-rose-950/40 text-rose-300 border-rose-500/30"
                          : isMedium
                          ? "bg-amber-950/40 text-amber-300 border-amber-500/30"
                          : "bg-slate-800 text-slate-300 border-slate-700/60"
                      }`}
                    >
                      {item.materiality || "LOW"} • {score.toFixed(1)}
                    </span>
                    <span className="text-xs font-sans px-2.5 py-0.5 rounded-full bg-slate-800/80 text-slate-300 border border-slate-700/50">
                      {item.category?.replace(/_/g, " ") || "unclassified"}
                    </span>
                  </div>
                </div>

                {/* Announcement Headline */}
                <h3 className="text-base font-sans font-semibold text-slate-100 mt-2.5 leading-snug">
                  {item.headline}
                </h3>

                {/* Financial Insights Card (First-cut numbers / bio) */}
                {insights && (
                  <div className="mt-3.5 p-3.5 rounded-xl bg-slate-900/80 border border-white/[0.06] space-y-2.5">
                    <div className="flex items-center justify-between text-xs font-sans text-emerald-400 font-semibold border-b border-white/[0.06] pb-2">
                      <div className="flex items-center gap-1.5">
                        <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
                        <span>First-Cut Financial Takeaway</span>
                      </div>
                      {insights.scope && (
                        <span className="text-slate-400 font-normal text-[11px]">{insights.scope}</span>
                      )}
                    </div>

                    <p className="text-xs font-sans text-slate-200 leading-relaxed">
                      {insights.insight_summary}
                    </p>

                    {/* Headline Numbers Grid */}
                    {insights.headline_metrics && Object.keys(insights.headline_metrics).length > 0 && (
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
                        {Object.entries(insights.headline_metrics).map(([k, v]) => (
                          <div key={k} className="p-2 rounded-lg bg-slate-950/60 border border-white/[0.05]">
                            <span className="text-[10px] font-sans text-slate-400 uppercase tracking-wider block font-semibold">{k}</span>
                            <span className="text-xs font-mono tabular-nums font-bold text-white mt-0.5 block">{v as string}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Leadership Profile */}
                    {insights.insight_type === "management_change" && insights.background_bio && (
                      <div className="text-xs font-sans text-slate-300 bg-slate-950/50 p-2.5 rounded-lg border border-white/[0.05]">
                        <span className="font-semibold text-slate-400 block mb-1">Executive Background:</span>
                        {insights.background_bio}
                      </div>
                    )}
                  </div>
                )}

                {/* Footer: PDF link & expandable rationale */}
                <div className="mt-3.5 pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs font-sans">
                  <button
                    onClick={() => toggleExpand(item.id)}
                    className="flex items-center gap-1 text-slate-400 hover:text-slate-200 transition-colors"
                  >
                    <span>{isExpanded ? "Hide Materiality Rationale" : "Why this matters (Classification & Materiality)"}</span>
                    {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                  </button>

                  {item.pdf_url ? (
                    <a
                      href={item.pdf_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1.5 text-emerald-400 hover:text-emerald-300 font-medium"
                    >
                      <span>Official PDF Filing</span>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  ) : (
                    <span className="text-slate-500 text-[11px]">Exchange Text Disclosure</span>
                  )}
                </div>

                {/* Expandable Rationale Details */}
                {isExpanded && (
                  <div className="mt-3 p-3.5 rounded-xl bg-slate-950/70 border border-white/[0.06] text-xs font-sans text-slate-300 space-y-2 animate-fade-in">
                    <div>
                      <span className="text-slate-400 font-semibold block text-[11px] mb-0.5">SEBI Materiality Rationale:</span>
                      <p className="text-slate-200 leading-relaxed">{item.materiality_rationale || "Categorized based on SEBI disclosure framework."}</p>
                    </div>
                  </div>
                )}
              </div>
            )
          })
        )}

        {/* Collapsed Routine Filings Section */}
        {digest && digest.summary.collapsed_routine_count > 0 && (
          <div className="p-4 rounded-2xl bg-slate-900/40 border border-white/[0.06] text-center">
            <button
              onClick={() => setShowRoutine(!showRoutine)}
              className="flex items-center justify-center gap-2 mx-auto text-xs font-sans text-slate-400 hover:text-slate-200 transition-colors"
            >
              <FileText className="w-4 h-4 text-slate-500" />
              <span>
                {digest.summary.collapsed_routine_count} routine compliance filings collapsed (loss of certificates, statutory intimation)
              </span>
              {showRoutine ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
            {showRoutine && (
              <p className="text-xs font-sans text-slate-400 mt-2 max-w-xl mx-auto leading-relaxed">
                Routine administrative filings are retained in the database and can be queried anytime with the Materiality filter set to "All" or "LOW".
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
