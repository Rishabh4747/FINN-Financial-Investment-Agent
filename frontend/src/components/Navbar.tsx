import React from "react"
import { Bell, Settings } from "lucide-react"

interface NavbarProps {
  activeTab: string
  setActiveTab: (tab: string) => void
  unseenAlertsCount: number
  backendOnline: boolean
  onOpenSettings: () => void
}

const TABS = [
  { id: "today",     label: "Today's Feed" },
  { id: "portfolio", label: "Portfolio & Watchlist" },
  { id: "research",  label: "Equity Research" },
]

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  unseenAlertsCount,
  backendOnline,
  onOpenSettings,
}) => {
  return (
    <header className="sticky top-0 z-40 bg-[#090e17]/90 backdrop-blur-md border-b border-white/[0.07] transition-all">
      <div className="max-w-7xl mx-auto px-4 lg:px-8 h-16 flex items-center justify-between gap-4">

        {/* ── Brand Logo ─────────────────────────────────────── */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500/20 to-teal-500/10 border border-emerald-500/30 text-emerald-400 font-sans font-extrabold text-sm shadow-sm shadow-emerald-950/40">
            F
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="font-sans font-bold text-white text-base tracking-tight">
                FINN
              </span>
              <span className="hidden sm:inline-flex items-center text-[10px] font-sans font-medium px-1.5 py-0.5 rounded-md bg-slate-800/80 text-slate-300 border border-slate-700/60">
                Institutional
              </span>
            </div>
            <span className="hidden sm:block text-[11px] font-sans text-slate-400 -mt-0.5">
              Financial Investment Agent
            </span>
          </div>
        </div>

        {/* ── Segmented Navigation Tabs ────────────────────── */}
        <nav className="hidden md:flex items-center p-1 bg-slate-900/80 border border-white/[0.08] rounded-xl shadow-inner">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-1.5 rounded-lg text-xs font-sans font-medium transition-all ${
                  isActive
                    ? "bg-slate-800 text-white shadow-sm border border-white/10"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
                }`}
              >
                {tab.label}
              </button>
            )
          })}
        </nav>

        {/* ── Right Controls ─────────────────────────────────── */}
        <div className="flex items-center gap-2.5 shrink-0">

          {/* Connection status badge */}
          <div
            className={`flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-sans border transition-colors ${
              backendOnline
                ? "bg-emerald-950/30 text-emerald-300 border-emerald-500/30"
                : "bg-rose-950/30 text-rose-300 border-rose-500/30"
            }`}
            title={backendOnline ? "Backend API is online and responding" : "Backend API is unreachable"}
          >
            <span className={backendOnline ? "status-dot-active" : "status-dot-offline"} />
            <span className="hidden sm:inline text-[11px] font-medium">
              {backendOnline ? "Live Feed" : "Offline"}
            </span>
          </div>

          {/* Alerts Bell */}
          <button
            onClick={() => setActiveTab("alerts")}
            className={`relative p-2 rounded-lg border transition-all ${
              activeTab === "alerts"
                ? "bg-slate-800 text-amber-400 border-amber-500/40 shadow-sm"
                : "bg-slate-900/80 text-slate-400 border-white/[0.08] hover:text-slate-200 hover:bg-slate-800"
            }`}
            aria-label="View Triggered Alerts"
            title="View Triggered Alerts"
          >
            <Bell className="w-4 h-4" />
            {unseenAlertsCount > 0 && (
              <span className="absolute -top-1 -right-1 flex items-center justify-center min-w-[16px] h-[16px] px-1 text-[10px] font-mono font-bold bg-amber-500 text-slate-950 rounded-full shadow-sm animate-pulse">
                {unseenAlertsCount}
              </span>
            )}
          </button>

          {/* Settings Trigger */}
          <button
            onClick={onOpenSettings}
            className="p-2 rounded-lg bg-slate-900/80 text-slate-400 border border-white/[0.08] hover:text-slate-200 hover:bg-slate-800 transition-all"
            aria-label="Settings"
            title="Digest & Alert Preferences"
          >
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  )
}
