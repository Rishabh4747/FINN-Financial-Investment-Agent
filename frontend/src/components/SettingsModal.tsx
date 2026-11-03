import React, { useState, useEffect } from "react"
import { X, Settings, Check, RotateCcw } from "lucide-react"
import type { PushSettings } from "../api/client"

interface SettingsModalProps {
  isOpen: boolean
  onClose: () => void
  settings: PushSettings | null
  onSave: (updated: Partial<PushSettings>) => Promise<void>
}

const ALL_CATEGORIES = [
  { id: "results", label: "Quarterly Results", defaultScore: 10.0 },
  { id: "M&A", label: "M&A & Restructuring", defaultScore: 9.0 },
  { id: "fund_raise", label: "Capital Raise & NCDs", defaultScore: 8.5 },
  { id: "management_change", label: "Leadership Transition (CFO/CEO)", defaultScore: 8.0 },
  { id: "litigation", label: "Litigation & Regulatory Enforcement", defaultScore: 8.0 },
  { id: "bonus_split", label: "Bonus & Stock Split", defaultScore: 7.0 },
  { id: "capex", label: "Capex & Capacity Expansion", defaultScore: 7.0 },
  { id: "dividend", label: "Dividend Declarations", defaultScore: 6.5 },
  { id: "credit_rating", label: "Credit Ratings", defaultScore: 6.5 },
  { id: "insider_trading", label: "Insider Trading / PIT", defaultScore: 6.0 },
  { id: "press_release", label: "Commercial Orders & Wins", defaultScore: 5.0 },
  { id: "pledging", label: "Promoter Share Pledging", defaultScore: 4.5 },
  { id: "earnings_call", label: "Earnings Call Transcripts", defaultScore: 4.0 },
  { id: "investor_meetings", label: "Investor Meets & Presentations", defaultScore: 3.5 },
  { id: "agm_egm", label: "AGM / EGM Proceedings", defaultScore: 3.0 },
  { id: "postal_ballot", label: "Postal Ballot Notices", defaultScore: 2.5 },
]

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  settings,
  onSave,
}) => {
  if (!isOpen || !settings) return null

  const [windowHours, setWindowHours] = useState(settings.digest_window_hours || 24.0)
  const [minScore, setMinScore] = useState(settings.min_materiality_score || 7.0)
  const [categories, setCategories] = useState<string[]>(settings.enabled_categories || [])
  const [portfolioOnly, setPortfolioOnly] = useState(settings.portfolio_only ?? true)
  const [defaultPricePct, setDefaultPricePct] = useState(settings.default_price_alert_pct || 5.0)
  const [defaultVolMult, setDefaultVolMult] = useState(settings.default_vol_alert_mult || 2.0)
  const [saving, setSaving] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (settings) {
      setWindowHours(settings.digest_window_hours)
      setMinScore(settings.min_materiality_score)
      setCategories(settings.enabled_categories)
      setPortfolioOnly(settings.portfolio_only)
      setDefaultPricePct(settings.default_price_alert_pct)
      setDefaultVolMult(settings.default_vol_alert_mult)
    }
  }, [settings])

  const toggleCategory = (catId: string) => {
    if (categories.includes(catId)) {
      setCategories(categories.filter((c) => c !== catId))
    } else {
      setCategories([...categories, catId])
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSuccess(false)
    try {
      await onSave({
        digest_window_hours: Number(windowHours),
        min_materiality_score: Number(minScore),
        enabled_categories: categories,
        portfolio_only: portfolioOnly,
        default_price_alert_pct: Number(defaultPricePct),
        default_vol_alert_mult: Number(defaultVolMult),
      })
      setSuccess(true)
      setTimeout(() => {
        setSuccess(false)
        onClose()
      }, 700)
    } catch (err: any) {
      setError(err?.message || "Failed to update preferences.")
    } finally {
      setSaving(false)
    }
  }

  const handleResetDefaults = () => {
    setWindowHours(24.0)
    setMinScore(7.0)
    setCategories(["results", "M&A", "fund_raise", "management_change", "litigation", "capex", "dividend"])
    setPortfolioOnly(true)
    setDefaultPricePct(5.0)
    setDefaultVolMult(2.0)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-fade-in font-sans">
      <div className="relative w-full max-w-xl bg-[#0d1527] border border-white/[0.1] rounded-2xl p-6 shadow-2xl text-slate-100 max-h-[90vh] overflow-y-auto">
        <div className="flex items-start justify-between border-b border-white/[0.08] pb-4 mb-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <Settings className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-sans font-bold text-base text-white">
                Push Digest & Alert Preferences
              </h3>
              <p className="text-xs text-slate-400">
                Institutional monitoring parameters for corporate filings and market anomalies
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-rose-950/40 border border-rose-800 text-rose-300 text-xs">
            {error}
          </div>
        )}

        {success && (
          <div className="mb-4 p-3 rounded-xl bg-emerald-950/40 border border-emerald-800 text-emerald-300 text-xs flex items-center gap-2">
            <Check className="w-4 h-4 text-emerald-400" />
            Settings saved successfully!
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Digest Time Window */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-semibold text-slate-300">
                Default Digest Time Window
              </label>
              <span className="text-xs font-mono font-bold text-emerald-400">
                {windowHours} hours
              </span>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {[12, 24, 48, 72].map((h) => (
                <button
                  type="button"
                  key={h}
                  onClick={() => setWindowHours(h)}
                  className={`py-2 px-3 rounded-xl text-xs font-medium border transition-all ${
                    windowHours === h
                      ? "bg-slate-800 text-white border-white/20 font-semibold shadow-sm"
                      : "bg-slate-900/60 border-white/[0.06] text-slate-400 hover:text-white"
                  }`}
                >
                  {h} Hours
                </button>
              ))}
            </div>
          </div>

          {/* Minimum Materiality Score */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-semibold text-slate-300">
                Minimum Materiality Score for Alert Trigger
              </label>
              <span className="text-xs font-mono font-bold text-emerald-400">
                {minScore.toFixed(1)} / 10.0 {minScore >= 7.0 ? "(HIGH)" : minScore >= 4.0 ? "(MEDIUM)" : "(LOW)"}
              </span>
            </div>
            <input
              type="range"
              min="1.0"
              max="10.0"
              step="0.5"
              value={minScore}
              onChange={(e) => setMinScore(parseFloat(e.target.value))}
              className="w-full h-2 bg-slate-900 rounded-lg appearance-none cursor-pointer accent-emerald-500"
            />
            <div className="flex justify-between text-[11px] font-sans text-slate-400 mt-1.5">
              <span>1.0 (All Filings)</span>
              <span>7.0 (High Priority Only)</span>
              <span>10.0 (Results Only)</span>
            </div>
          </div>

          {/* Portfolio Only Filter */}
          <div className="p-3.5 rounded-xl bg-slate-900/60 border border-white/[0.06] flex items-center justify-between">
            <div>
              <span className="text-xs font-semibold text-white block">Watchlist / Coverage Scope</span>
              <span className="text-xs text-slate-400 block mt-0.5">
                Restrict push digest and corporate alerts to the 15 active watchlist companies
              </span>
            </div>
            <button
              type="button"
              onClick={() => setPortfolioOnly(!portfolioOnly)}
              className={`w-11 h-6 rounded-full transition-colors relative shrink-0 ${
                portfolioOnly ? "bg-emerald-600" : "bg-slate-800"
              }`}
            >
              <span
                className={`absolute top-1 left-1 bg-white w-4 h-4 rounded-full transition-transform ${
                  portfolioOnly ? "translate-x-5" : ""
                }`}
              />
            </button>
          </div>

          {/* Enabled Corporate Categories */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-2">
              Monitored Announcement Categories ({categories.length} of {ALL_CATEGORIES.length})
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-48 overflow-y-auto pr-1">
              {ALL_CATEGORIES.map((cat) => {
                const checked = categories.includes(cat.id)
                return (
                  <button
                    type="button"
                    key={cat.id}
                    onClick={() => toggleCategory(cat.id)}
                    className={`flex items-center justify-between p-2.5 rounded-xl text-left border transition-all ${
                      checked
                        ? "bg-slate-800/80 border-emerald-500/40 text-white"
                        : "bg-slate-900/40 border-white/[0.05] text-slate-400 hover:text-white"
                    }`}
                  >
                    <div className="flex items-center gap-2.5 truncate">
                      <div
                        className={`w-4 h-4 rounded flex items-center justify-center border shrink-0 ${
                          checked
                            ? "bg-emerald-600 border-emerald-500 text-white"
                            : "border-slate-700 bg-slate-900"
                        }`}
                      >
                        {checked && <Check className="w-3 h-3 stroke-[3]" />}
                      </div>
                      <span className="text-xs truncate font-medium">{cat.label}</span>
                    </div>
                    <span className="text-xs font-mono text-slate-400 ml-2 font-semibold">
                      {cat.defaultScore.toFixed(1)}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Market Anomalies Thresholds */}
          <div className="grid grid-cols-2 gap-3 pt-1">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                Default Price Move (±%)
              </label>
              <input
                type="number"
                step="0.5"
                min="0.5"
                max="30"
                value={defaultPricePct}
                onChange={(e) => setDefaultPricePct(parseFloat(e.target.value) || 0)}
                className="w-full px-3.5 py-2 rounded-xl bg-slate-900 border border-white/[0.1] text-white font-mono font-semibold text-xs focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                Default Volume Spike (× Avg)
              </label>
              <input
                type="number"
                step="0.1"
                min="1.0"
                max="10"
                value={defaultVolMult}
                onChange={(e) => setDefaultVolMult(parseFloat(e.target.value) || 0)}
                className="w-full px-3.5 py-2 rounded-xl bg-slate-900 border border-white/[0.1] text-white font-mono font-semibold text-xs focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          {/* Footer Controls */}
          <div className="pt-4 border-t border-white/[0.08] flex items-center justify-between">
            <button
              type="button"
              onClick={handleResetDefaults}
              className="flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-white transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reset Defaults</span>
            </button>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-md shadow-emerald-950 transition-colors disabled:opacity-50"
              >
                {saving ? "Saving..." : "Apply Settings"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
