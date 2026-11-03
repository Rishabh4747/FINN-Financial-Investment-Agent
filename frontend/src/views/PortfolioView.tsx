import React, { useState, useEffect } from "react"
import {
  RefreshCw,
  Search,
  Sliders,
  TrendingUp,
  TrendingDown,
  ArrowUpDown,
  ExternalLink,
  Sparkles,
  ChevronUp,
  ChevronDown,
  Building2,
  Activity,
  Layers,
} from "lucide-react"
import {
  api,
  type PortfolioCompany,
  type PriceSnapshot,
} from "../api/client"
import { formatCurrency, formatNumber, formatPercent } from "../lib/utils"
import { ThresholdModal } from "../components/ThresholdModal"

interface PortfolioViewProps {
  onSelectTickerForResearch?: (ticker: string) => void
}

type SortField = "name" | "ticker" | "close" | "pct_change" | "volume"

export const PortfolioView: React.FC<PortfolioViewProps> = ({ onSelectTickerForResearch }) => {
  const [companies, setCompanies] = useState<PortfolioCompany[]>([])
  const [prices, setPrices] = useState<PriceSnapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [search, setSearch] = useState("")
  const [selectedSector, setSelectedSector] = useState("all")
  const [sortField, setSortField] = useState<SortField>("name")
  const [sortAsc, setSortAsc] = useState(true)

  const [selectedCompanyForThreshold, setSelectedCompanyForThreshold] = useState<PortfolioCompany | null>(null)

  const loadData = async () => {
    try {
      setLoading(true)
      setError(null)
      const [comps, prs] = await Promise.all([api.getCompanies(), api.getPrices()])
      setCompanies(comps)
      setPrices(prs)
    } catch (err: any) {
      setError(err?.message || "Failed to load portfolio coverage data.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleRefreshPrices = async () => {
    setRefreshing(true)
    setRefreshMsg(null)
    try {
      const res = await api.refreshPrices()
      setRefreshMsg(res.message)
      await loadData()
    } catch (err: any) {
      setRefreshMsg(`Refresh failed: ${err?.message || "Yahoo Finance fetch error"}`)
    } finally {
      setRefreshing(false)
      setTimeout(() => setRefreshMsg(null), 6000)
    }
  }

  const handleSaveThreshold = async (
    ticker: string,
    thresholds: { vol_alert_mult: number; price_alert_pct: number }
  ) => {
    await api.updateCompanyThresholds(ticker, thresholds)
    const updated = await api.getCompanies()
    setCompanies(updated)
  }

  const mergedData = companies.map((comp) => {
    const snap = prices.find((p) => p.ticker === comp.ticker)
    return {
      ...comp,
      close: snap?.close ?? null,
      pct_change: snap?.pct_change ?? null,
      volume: snap?.volume ?? null,
      avg_vol_20d: snap?.avg_vol_20d ?? null,
      date: snap?.date ?? null,
      data_status: snap?.data_status ?? "no_data",
    }
  })

  const sectors = Array.from(new Set(companies.map((c) => c.sector))).sort()

  const filtered = mergedData
    .filter((item) => {
      if (selectedSector !== "all" && item.sector !== selectedSector) return false
      if (!search.trim()) return true
      const q = search.toLowerCase()
      return (
        item.ticker.toLowerCase().includes(q) ||
        item.name.toLowerCase().includes(q) ||
        item.sector.toLowerCase().includes(q)
      )
    })
    .sort((a, b) => {
      let vA = (a as any)[sortField] ?? 0
      let vB = (b as any)[sortField] ?? 0
      if (typeof vA === "string") vA = vA.toLowerCase()
      if (typeof vB === "string") vB = vB.toLowerCase()
      if (vA < vB) return sortAsc ? -1 : 1
      if (vA > vB) return sortAsc ? 1 : -1
      return 0
    })

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortAsc(!sortAsc)
    } else {
      setSortField(field)
      setSortAsc(field === "name" || field === "ticker")
    }
  }

  const SortIcon: React.FC<{ field: SortField }> = ({ field }) => {
    if (sortField !== field) {
      return <ArrowUpDown className="w-3.5 h-3.5 text-slate-500 opacity-60" />
    }
    return sortAsc ? (
      <ChevronUp className="w-3.5 h-3.5 text-emerald-400" />
    ) : (
      <ChevronDown className="w-3.5 h-3.5 text-emerald-400" />
    )
  }

  return (
    <div className="space-y-6 pb-20">

      {/* ── Page Header & Integrated Portfolio Stats ─────────── */}
      <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-sans font-semibold text-emerald-400 uppercase tracking-wider">
                Coverage Universe
              </span>
              <span className="text-slate-600">•</span>
              <span className="text-xs font-sans text-slate-400">
                15 NSE / BSE Equities
              </span>
            </div>
            <h1 className="text-2xl font-sans font-bold text-white tracking-tight">
              Portfolio Coverage & Market Activity
            </h1>
            <p className="text-sm font-sans text-slate-400 mt-1 max-w-2xl">
              Real-time daily closing quotes, 20-day volume surge detection, and automated threshold alerts.
            </p>
          </div>

          {/* Action button */}
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={handleRefreshPrices}
              disabled={refreshing}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-sans font-semibold transition-all shadow-sm shadow-emerald-950/50 disabled:opacity-50"
              title="Fetch latest end-of-day quotes via yfinance"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
              <span>{refreshing ? "Updating Quotes..." : "Refresh EOD Quotes"}</span>
            </button>
          </div>
        </div>

        {/* Refresh notification */}
        {refreshMsg && (
          <div className="p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/30 text-emerald-300 text-xs font-sans flex items-center gap-2 animate-fade-in">
            <Sparkles className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{refreshMsg}</span>
          </div>
        )}

        {/* ── Sleek Integrated Summary Bar ── */}
        <div className="p-4 rounded-2xl bg-slate-900/60 border border-white/[0.08] grid grid-cols-2 sm:grid-cols-4 gap-4 divide-y sm:divide-y-0 sm:divide-x divide-white/[0.06]">
          <div className="flex items-center gap-3 pt-2 sm:pt-0 sm:px-2">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0">
              <Building2 className="w-4 h-4" />
            </div>
            <div>
              <span className="text-xs font-sans text-slate-400 block">Monitored Equities</span>
              <span className="text-base font-sans font-bold text-white">{companies.length} Companies</span>
            </div>
          </div>

          <div className="flex items-center gap-3 pt-2 sm:pt-0 sm:px-4">
            <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 shrink-0">
              <Layers className="w-4 h-4" />
            </div>
            <div>
              <span className="text-xs font-sans text-slate-400 block">Industry Sectors</span>
              <span className="text-base font-sans font-bold text-white">{sectors.length} Sectors</span>
            </div>
          </div>

          <div className="flex items-center gap-3 pt-2 sm:pt-0 sm:px-4">
            <div className="w-9 h-9 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400 shrink-0">
              <Activity className="w-4 h-4" />
            </div>
            <div>
              <span className="text-xs font-sans text-slate-400 block">Pricing Source</span>
              <span className="text-base font-sans font-semibold text-slate-200">Yahoo Finance EOD</span>
            </div>
          </div>

          <div className="flex items-center gap-3 pt-2 sm:pt-0 sm:px-4">
            <div className="w-9 h-9 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 shrink-0">
              <TrendingUp className="w-4 h-4" />
            </div>
            <div>
              <span className="text-xs font-sans text-slate-400 block">Volume Baseline</span>
              <span className="text-base font-sans font-semibold text-slate-200">20-Day Rolling Avg</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Search & Filter Controls ─────────────────────────── */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search company name, ticker or sector..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-slate-900/70 border border-white/[0.08] rounded-xl text-xs font-sans text-white placeholder-slate-400 transition-colors"
          />
        </div>

        {/* Sector Filter & Count */}
        <div className="flex items-center gap-3">
          <span className="text-xs font-sans text-slate-400 hidden sm:inline">
            Sector:
          </span>
          <select
            value={selectedSector}
            onChange={(e) => setSelectedSector(e.target.value)}
            className="px-3 py-2 bg-slate-900/70 border border-white/[0.08] rounded-xl text-xs font-sans text-slate-200"
          >
            <option value="all">All Sectors ({companies.length})</option>
            {sectors.map((s) => (
              <option key={s} value={s}>
                {s} ({companies.filter((c) => c.sector === s).length})
              </option>
            ))}
          </select>
          <span className="text-xs font-sans text-slate-400 hidden md:inline font-medium">
            Showing {filtered.length} of {companies.length}
          </span>
        </div>
      </div>

      {/* ── Institutional Stock Table ─────────────────────────── */}
      <div className="bg-[#0d1527] border border-white/[0.08] rounded-2xl overflow-hidden shadow-xl">
        {loading ? (
          <div className="p-16 text-center text-slate-400 flex flex-col items-center gap-3">
            <RefreshCw className="w-6 h-6 animate-spin text-emerald-400" />
            <p className="text-sm font-sans font-medium text-slate-300">
              Loading portfolio quotes...
            </p>
          </div>
        ) : error ? (
          <div className="p-10 text-center text-rose-300 text-sm font-sans">
            <p className="font-semibold">{error}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-900/80 border-b border-white/[0.08] text-xs font-sans font-semibold text-slate-400 uppercase tracking-wider">
                  <th
                    onClick={() => toggleSort("name")}
                    className="py-3.5 px-5 cursor-pointer hover:text-white transition-colors"
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Company / Symbol</span>
                      <SortIcon field="name" />
                    </div>
                  </th>

                  <th className="py-3.5 px-4">
                    Sector
                  </th>

                  <th
                    onClick={() => toggleSort("close")}
                    className="py-3.5 px-4 text-right cursor-pointer hover:text-white transition-colors"
                  >
                    <div className="flex items-center justify-end gap-1.5">
                      <span>Last Close</span>
                      <SortIcon field="close" />
                    </div>
                  </th>

                  <th
                    onClick={() => toggleSort("pct_change")}
                    className="py-3.5 px-4 text-right cursor-pointer hover:text-white transition-colors"
                  >
                    <div className="flex items-center justify-end gap-1.5">
                      <span>Day Change</span>
                      <SortIcon field="pct_change" />
                    </div>
                  </th>

                  <th
                    onClick={() => toggleSort("volume")}
                    className="py-3.5 px-4 text-right cursor-pointer hover:text-white transition-colors"
                  >
                    <div className="flex items-center justify-end gap-1.5">
                      <span>Volume / 20d Multiple</span>
                      <SortIcon field="volume" />
                    </div>
                  </th>

                  <th className="py-3.5 px-4 text-center">
                    Alert Bounds
                  </th>

                  <th className="py-3.5 px-5 text-right">
                    Actions
                  </th>
                </tr>
              </thead>

              <tbody className="divide-y divide-white/[0.05] text-sm">
                {filtered.map((item) => {
                  const hasPrice = item.close !== null
                  const isPositive = (item.pct_change || 0) > 0
                  const isNegative = (item.pct_change || 0) < 0
                  const volRatio =
                    item.volume && item.avg_vol_20d && item.avg_vol_20d > 0
                      ? item.volume / item.avg_vol_20d
                      : null
                  const isVolumeSpike = volRatio !== null && volRatio >= item.vol_alert_mult

                  return (
                    <tr
                      key={item.id}
                      className="hover:bg-slate-800/40 transition-colors group"
                    >
                      {/* Company Name & Ticker */}
                      <td className="py-4 px-5">
                        <div className="flex flex-col">
                          <button
                            onClick={() => onSelectTickerForResearch?.(item.ticker.replace(".NS", "").replace(".BO", ""))}
                            className="font-sans font-semibold text-slate-100 hover:text-emerald-400 transition-colors text-left text-sm"
                            title="Open in Equity Research Workspace"
                          >
                            {item.name}
                          </button>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="font-mono text-xs text-slate-400 font-medium">
                              {item.ticker}
                            </span>
                            <span className="text-slate-600 text-xs">•</span>
                            <span className="text-[10px] font-sans px-1.5 py-0.5 rounded bg-slate-800/80 text-slate-400 border border-slate-700/50">
                              {item.exchange}
                            </span>
                            {item.data_status && (
                              <span
                                className={`text-[10px] font-sans font-medium px-1.5 py-0.5 rounded border ${
                                  item.data_status === "ok"
                                    ? "bg-emerald-950/40 text-emerald-400 border-emerald-500/20"
                                    : item.data_status === "stale"
                                    ? "bg-amber-950/40 text-amber-400 border-amber-500/20"
                                    : "bg-slate-800 text-slate-400 border-slate-700"
                                }`}
                              >
                                {item.data_status === "ok" ? "Synced" : item.data_status}
                              </span>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Sector */}
                      <td className="py-4 px-4">
                        <span className="text-xs font-sans text-slate-300 bg-slate-800/70 px-2.5 py-1 rounded-md border border-slate-700/40 inline-block">
                          {item.sector}
                        </span>
                      </td>

                      {/* Close Price */}
                      <td className="py-4 px-4 text-right">
                        <span className="font-mono tabular-nums font-semibold text-white text-sm">
                          {hasPrice ? formatCurrency(item.close) : "—"}
                        </span>
                        {item.date && (
                          <span className="block text-[11px] font-sans text-slate-500 mt-0.5">
                            {item.date}
                          </span>
                        )}
                      </td>

                      {/* Day % Change */}
                      <td className="py-4 px-4 text-right">
                        {item.pct_change !== null ? (
                          <span
                            className={`inline-flex items-center gap-1 font-mono tabular-nums text-xs font-semibold px-2.5 py-1 rounded-lg border ${
                              isPositive
                                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                                : isNegative
                                ? "bg-rose-500/10 text-rose-400 border-rose-500/20"
                                : "bg-slate-800 text-slate-400 border-slate-700"
                            }`}
                          >
                            {isPositive && <TrendingUp className="w-3.5 h-3.5" />}
                            {isNegative && <TrendingDown className="w-3.5 h-3.5" />}
                            {formatPercent(item.pct_change)}
                          </span>
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                      </td>

                      {/* Volume & 20d Multiple */}
                      <td className="py-4 px-4 text-right">
                        <span className="font-mono tabular-nums text-slate-200 text-xs font-medium block">
                          {item.volume ? formatNumber(item.volume) : "—"}
                        </span>
                        {volRatio !== null && (
                          <span
                            className={`font-mono text-[11px] mt-0.5 inline-block ${
                              isVolumeSpike
                                ? "text-amber-400 font-semibold"
                                : "text-slate-400"
                            }`}
                          >
                            {volRatio.toFixed(1)}× 20d avg
                          </span>
                        )}
                      </td>

                      {/* Alert Bounds */}
                      <td className="py-4 px-4 text-center">
                        <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-900/80 border border-white/[0.08] text-xs font-mono text-slate-300">
                          <span>±{item.price_alert_pct}%</span>
                          <span className="text-slate-600">•</span>
                          <span>{item.vol_alert_mult}×</span>
                        </div>
                      </td>

                      {/* Action buttons */}
                      <td className="py-4 px-5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => setSelectedCompanyForThreshold(item)}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                            title="Edit Alert Thresholds"
                            aria-label="Edit Alert Thresholds"
                          >
                            <Sliders className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => onSelectTickerForResearch?.(item.ticker.replace(".NS", "").replace(".BO", ""))}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-400 hover:bg-slate-800 transition-colors"
                            title="Deep Research & Citations"
                            aria-label="Deep Research & Citations"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Threshold Modal */}
      {selectedCompanyForThreshold && (
        <ThresholdModal
          company={selectedCompanyForThreshold}
          onClose={() => setSelectedCompanyForThreshold(null)}
          onSave={handleSaveThreshold}
        />
      )}
    </div>
  )
}
