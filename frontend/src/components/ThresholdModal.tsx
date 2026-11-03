import React, { useState } from "react"
import { X, Sliders } from "lucide-react"
import type { PortfolioCompany } from "../api/client"

interface ThresholdModalProps {
  company: PortfolioCompany | null
  onClose: () => void
  onSave: (ticker: string, thresholds: { vol_alert_mult: number; price_alert_pct: number }) => Promise<void>
}

export const ThresholdModal: React.FC<ThresholdModalProps> = ({ company, onClose, onSave }) => {
  if (!company) return null

  const [pricePct, setPricePct] = useState<number>(company.price_alert_pct || 5.0)
  const [volMult, setVolMult] = useState<number>(company.vol_alert_mult || 2.0)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSave(company.ticker, {
        price_alert_pct: Number(pricePct),
        vol_alert_mult: Number(volMult),
      })
      onClose()
    } catch (err: any) {
      setError(err?.message || "Failed to update thresholds.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-fade-in">
      <div className="relative w-full max-w-md bg-[#0d1527] border border-white/[0.1] rounded-2xl p-6 shadow-2xl text-slate-100">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-white/[0.08] pb-4 mb-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <Sliders className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-sans font-bold text-base text-white">
                  {company.name}
                </h3>
              </div>
              <p className="text-xs font-mono text-emerald-400 font-medium">{company.ticker} • {company.sector}</p>
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
          <div className="mb-4 p-3 rounded-xl bg-rose-950/40 border border-rose-800 text-rose-300 text-xs font-sans">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 font-sans">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              Daily Price Movement Threshold (±%)
            </label>
            <div className="flex items-center gap-3">
              <input
                type="number"
                step="0.5"
                min="0.5"
                max="50"
                value={pricePct}
                onChange={(e) => setPricePct(parseFloat(e.target.value) || 0)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-900 border border-white/[0.1] text-white font-mono font-semibold text-sm focus:outline-none focus:border-emerald-500"
              />
              <span className="text-xs text-slate-400 font-mono font-semibold">±%</span>
            </div>
            <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
              Triggers an alert when the closing price moves by more than ±{pricePct}% relative to the previous trading day.
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              Volume Surge Multiple (× 20-Day Rolling Average)
            </label>
            <div className="flex items-center gap-3">
              <input
                type="number"
                step="0.1"
                min="1.0"
                max="20"
                value={volMult}
                onChange={(e) => setVolMult(parseFloat(e.target.value) || 0)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-900 border border-white/[0.1] text-white font-mono font-semibold text-sm focus:outline-none focus:border-emerald-500"
              />
              <span className="text-xs text-slate-400 font-mono font-semibold whitespace-nowrap">× avg</span>
            </div>
            <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
              Triggers an alert when daily traded volume reaches or exceeds {volMult}× the rolling 20-day average.
            </p>
          </div>

          <div className="pt-4 border-t border-white/[0.08] flex items-center justify-end gap-2.5">
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
              {saving ? "Saving..." : "Save Thresholds"}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
