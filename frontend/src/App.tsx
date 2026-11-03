import { useState, useEffect } from "react"
import { Navbar } from "./components/Navbar"
import { BottomNav } from "./components/BottomNav"
import { SettingsModal } from "./components/SettingsModal"
import { TodayView } from "./views/TodayView"
import { PortfolioView } from "./views/PortfolioView"
import { ResearchView } from "./views/ResearchView"
import { AlertsView } from "./views/AlertsView"
import { api, type PushSettings } from "./api/client"

export function App() {
  const [activeTab, setActiveTabState] = useState<string>(() => {
    if (typeof window !== "undefined") {
      const param = new URLSearchParams(window.location.search).get("tab")
      if (param && ["today", "portfolio", "research", "alerts"].includes(param)) {
        return param
      }
    }
    return "today"
  })

  const setActiveTab = (tab: string) => {
    setActiveTabState(tab)
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href)
      url.searchParams.set("tab", tab)
      window.history.replaceState(null, "", url.toString())
    }
  }
  const [unseenAlertsCount, setUnseenAlertsCount] = useState<number>(0)
  const [backendOnline, setBackendOnline] = useState<boolean>(true)
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false)
  const [pushSettings, setPushSettings] = useState<PushSettings | null>(null)
  const [selectedResearchTicker, setSelectedResearchTicker] = useState<string>("RELIANCE")

  // Check backend health & push settings
  const checkHealthAndSettings = async () => {
    try {
      const health = await api.getHealth()
      setBackendOnline(health.status === "ok")
      const settings = await api.getPushSettings()
      setPushSettings(settings)
      const alerts = await api.getUnifiedAlerts(true)
      setUnseenAlertsCount(alerts.length)
    } catch (err) {
      console.warn("Backend connectivity check:", err)
      setBackendOnline(false)
    }
  }

  useEffect(() => {
    checkHealthAndSettings()
    const timer = setInterval(checkHealthAndSettings, 15000)
    return () => clearInterval(timer)
  }, [])

  const handleSelectTickerForResearch = (ticker: string) => {
    setSelectedResearchTicker(ticker)
    setActiveTab("research")
    window.scrollTo({ top: 0, behavior: "smooth" })
  }

  const handleSaveSettings = async (updated: Partial<PushSettings>) => {
    const saved = await api.updatePushSettings(updated)
    setPushSettings(saved)
  }

  return (
    <div className="min-h-screen bg-[#090e17] text-slate-100 flex flex-col font-sans selection:bg-emerald-500/20 selection:text-emerald-300">
      {/* Top Header Navbar */}
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        unseenAlertsCount={unseenAlertsCount}
        backendOnline={backendOnline}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 lg:px-8 py-7">
        {activeTab === "today" && (
          <TodayView onSelectTickerForResearch={handleSelectTickerForResearch} />
        )}
        {activeTab === "portfolio" && (
          <PortfolioView onSelectTickerForResearch={handleSelectTickerForResearch} />
        )}
        {activeTab === "research" && (
          <ResearchView initialTicker={selectedResearchTicker} />
        )}
        {activeTab === "alerts" && <AlertsView />}
      </main>

      {/* Institutional Desktop Footer */}
      <footer className="hidden md:flex items-center justify-between max-w-7xl w-full mx-auto px-4 lg:px-8 py-5 border-t border-white/[0.06] text-xs font-sans text-slate-500">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-slate-400">FINN</span>
          <span>•</span>
          <span>ENAM Holdings AI Engineer Challenge</span>
          <span>•</span>
          <span>Primary-Source Intelligence</span>
        </div>
        <div className="flex items-center gap-3">
          <span>SQLite FTS5 Retrieval</span>
          <span>•</span>
          <span>Yahoo Finance EOD Quotes</span>
          <span>•</span>
          <span className={backendOnline ? "text-emerald-400 font-medium" : "text-rose-400"}>
            ● {backendOnline ? "System Operational" : "System Offline"}
          </span>
        </div>
      </footer>

      {/* Mobile Fixed Bottom Navigation */}
      <BottomNav
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        unseenAlertsCount={unseenAlertsCount}
      />

      {/* Settings Modal */}
      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={pushSettings}
        onSave={handleSaveSettings}
      />
    </div>
  )
}

export default App
