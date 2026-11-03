import React, { useState, useEffect } from "react"
import {
  CheckCircle2,
  Sparkles,
  RefreshCw,
} from "lucide-react"
import { api, type UnifiedAlert } from "../api/client"
import { timeAgo } from "../lib/utils"

export const AlertsView: React.FC = () => {
  const [alerts, setAlerts] = useState<UnifiedAlert[]>([])
  const [loading, setLoading] = useState(true)
  const [unseenOnly, setUnseenOnly] = useState(true)
  const [evaluating, setEvaluating] = useState(false)
  const [evalMsg, setEvalMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadAlerts = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await api.getUnifiedAlerts(unseenOnly)
      setAlerts(data)
    } catch (err: any) {
      setError(err?.message || "Failed to load alerts feed.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAlerts()
  }, [unseenOnly])

  const handleMarkSeen = async (alertItem: UnifiedAlert) => {
    try {
      const type = alertItem.alert_source === "corporate_announcement" ? "announcement" : "market"
      await api.markAlertSeen(type, alertItem.id)
      setAlerts(alerts.map((a) => (a.id === alertItem.id ? { ...a, seen: true } : a)))
      if (unseenOnly) {
        setAlerts(alerts.filter((a) => a.id !== alertItem.id))
      }
    } catch (err: any) {
      window.alert(`Could not mark alert seen: ${err?.message}`)
    }
  }

  const handleEvaluateNow = async () => {
    setEvaluating(true)
    setEvalMsg(null)
    try {
      const res = await api.evaluateAlerts(48)
      setEvalMsg(res.message)
      await loadAlerts()
    } catch (err: any) {
      setEvalMsg(`Evaluation failed: ${err?.message}`)
    } finally {
      setEvaluating(false)
      setTimeout(() => setEvalMsg(null), 5000)
    }
  }

  const unacknowledgedCount = alerts.filter((a) => !a.seen).length

  return (
    <div className="space-y-6 pb-20">

      {/* ── Page Header ───────────────────────────────────────── */}
      <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-sans font-semibold text-amber-400 uppercase tracking-wider">
                Monitoring Center
              </span>
              <span className="text-slate-600">•</span>
              <span className="text-xs font-sans text-slate-400">
                Proactive Anomaly Detection
              </span>
            </div>
            <h1 className="text-2xl font-sans font-bold text-white tracking-tight">
              Market Anomalies & Material Disclosures
            </h1>
            <p className="text-sm font-sans text-slate-400 mt-1 max-w-2xl">
              Automated notifications for stock price swings beyond threshold bounds, volume surges, and high-impact exchange filings.
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={handleEvaluateNow}
              disabled={evaluating}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-xs font-sans font-semibold transition-all border border-white/[0.08] shadow-sm disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${evaluating ? "animate-spin text-amber-400" : ""}`} />
              <span>{evaluating ? "Evaluating..." : "Check Recent Anomalies"}</span>
            </button>
          </div>
        </div>

        {evalMsg && (
          <div className="p-3 rounded-xl bg-amber-950/30 border border-amber-500/30 text-amber-300 text-xs font-sans flex items-center gap-2 animate-fade-in">
            <Sparkles className="w-4 h-4 text-amber-400 shrink-0" />
            <span>{evalMsg}</span>
          </div>
        )}

        {/* Filter Controls Bar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center p-1 bg-slate-900/80 rounded-xl border border-white/[0.08]">
            <button
              onClick={() => setUnseenOnly(true)}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-sans font-medium transition-all ${
                unseenOnly
                  ? "bg-amber-500/15 text-amber-300 border border-amber-500/30 font-semibold"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Unacknowledged ({unacknowledgedCount})
            </button>
            <button
              onClick={() => setUnseenOnly(false)}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-sans font-medium transition-all ${
                !unseenOnly
                  ? "bg-slate-800 text-white border border-white/10 font-semibold"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              All Alerts
            </button>
          </div>

          <span className="text-xs font-sans text-slate-400 font-medium">
            {alerts.length} Total Registered
          </span>
        </div>
      </div>

      {/* ── Alerts Feed List ──────────────────────────────────── */}
      <div className="space-y-3">
        {loading ? (
          <div className="p-16 text-center text-slate-400 bg-[#0d1527] border border-white/[0.08] rounded-2xl flex flex-col items-center gap-3">
            <RefreshCw className="w-6 h-6 animate-spin text-amber-400" />
            <p className="text-sm font-sans font-medium text-slate-300">
              Loading anomaly feed...
            </p>
          </div>
        ) : error ? (
          <div className="p-10 text-center text-rose-300 text-sm font-sans bg-rose-950/20 border border-rose-800/40 rounded-2xl">
            {error}
          </div>
        ) : alerts.length === 0 ? (
          <div className="p-16 text-center text-slate-400 bg-[#0d1527] border border-white/[0.08] rounded-2xl flex flex-col items-center gap-3">
            <CheckCircle2 className="w-8 h-8 text-emerald-500" />
            <p className="text-base font-sans font-bold text-white">
              All Alerts Acknowledged
            </p>
            <p className="text-xs font-sans text-slate-400 max-w-sm">
              No pending price spikes, volume anomalies, or material corporate alerts.
            </p>
          </div>
        ) : (
          alerts.map((alert) => {
            const isPrice = alert.alert_source === "market_price"
            const isVolume = alert.alert_source === "market_volume"

            return (
              <div
                key={`${alert.alert_source}-${alert.id}`}
                className={`p-5 rounded-2xl border transition-all ${
                  alert.seen
                    ? "bg-[#090e17]/70 border-white/[0.05] opacity-75"
                    : "bg-[#0d1527] border-white/[0.09] shadow-lg"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="font-mono font-bold text-sm text-white px-2 py-0.5 rounded bg-slate-800 border border-slate-700">
                      {alert.symbol}
                    </span>
                    <span
                      className={`text-xs font-sans font-semibold px-2.5 py-0.5 rounded-full border ${
                        isPrice
                          ? "bg-rose-950/40 text-rose-300 border-rose-500/30"
                          : isVolume
                          ? "bg-amber-950/40 text-amber-300 border-amber-500/30"
                          : "bg-emerald-950/40 text-emerald-300 border-emerald-500/30"
                      }`}
                    >
                      {isPrice ? "Price Anomaly" : isVolume ? "Volume Surge" : "Corporate Filing"}
                    </span>
                    <span className="text-slate-600 text-xs">•</span>
                    <span className="text-xs font-sans text-slate-400">
                      {timeAgo(alert.created_at)}
                    </span>
                  </div>

                  {!alert.seen && (
                    <button
                      onClick={() => handleMarkSeen(alert)}
                      className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 hover:text-white border border-white/[0.08] text-xs font-sans font-semibold transition-colors flex items-center gap-1.5 shrink-0"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Acknowledge</span>
                    </button>
                  )}
                </div>

                <div className="mt-2.5 text-sm font-sans font-semibold text-slate-100">
                  {alert.headline_or_type}
                </div>

                {/* Metric Summary Comparison */}
                <div className="mt-3 p-3 rounded-xl bg-slate-900/70 border border-white/[0.06] flex items-center gap-6 text-xs font-sans">
                  <div>
                    <span className="text-slate-400 text-[11px] block font-medium">Observed Value:</span>
                    <span className="font-mono tabular-nums font-bold text-amber-400 text-sm mt-0.5 block">
                      {alert.value_or_category}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[11px] block font-medium">Threshold / Criterion:</span>
                    <span className="font-mono tabular-nums font-semibold text-slate-200 text-sm mt-0.5 block">
                      {alert.threshold_or_materiality}
                    </span>
                  </div>
                </div>

                {/* Financial Insights snippet */}
                {alert.financial_insights && (
                  <div className="mt-3 p-3 rounded-xl bg-slate-950/70 border border-white/[0.05] text-xs font-sans text-slate-300 space-y-1">
                    <span className="font-semibold text-emerald-400 block text-[11px]">
                      Financial Insight:
                    </span>
                    <p className="leading-relaxed">{alert.financial_insights.insight_summary}</p>
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
