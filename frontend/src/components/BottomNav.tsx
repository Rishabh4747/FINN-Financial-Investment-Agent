import React from "react"
import { Newspaper, PieChart, Search, Bell } from "lucide-react"

interface BottomNavProps {
  activeTab: string
  setActiveTab: (tab: string) => void
  unseenAlertsCount: number
}

const TABS = [
  { id: "today",     label: "Feed",      icon: Newspaper },
  { id: "portfolio", label: "Portfolio", icon: PieChart  },
  { id: "research",  label: "Research",  icon: Search    },
  { id: "alerts",    label: "Alerts",    icon: Bell, isBell: true },
]

export const BottomNav: React.FC<BottomNavProps> = ({
  activeTab,
  setActiveTab,
  unseenAlertsCount,
}) => {
  return (
    <div className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-[#090e17]/95 backdrop-blur-md border-t border-white/[0.08] px-2 py-1 shadow-2xl">
      <div className="flex items-center justify-around">
        {TABS.map((tab) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          const badge = tab.isBell ? unseenAlertsCount : 0

          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`relative flex flex-col items-center justify-center py-2 px-3 rounded-xl transition-all ${
                isActive
                  ? "text-emerald-400 font-semibold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <div className="relative">
                <Icon className={`w-5 h-5 ${isActive ? "stroke-[2.2px]" : "stroke-1.5"}`} />
                {badge > 0 && (
                  <span className="absolute -top-1.5 -right-2 min-w-[15px] h-[15px] px-0.5 text-[9px] font-mono font-bold bg-amber-500 text-slate-950 rounded-full flex items-center justify-center">
                    {badge}
                  </span>
                )}
              </div>
              <span className="text-[10px] font-sans mt-1 tracking-tight">
                {tab.label}
              </span>
              {isActive && (
                <span className="absolute bottom-0.5 w-6 h-0.5 bg-emerald-400 rounded-full" />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
