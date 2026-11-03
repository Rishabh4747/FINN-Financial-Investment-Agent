/**
 * FINN API Client — Typed bindings for all backend routes.
 * Supports configurable VITE_API_BASE_URL (defaults to /api with Vite dev proxy).
 */

function getBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL
  if (!envUrl) return "/api"
  const trimmed = envUrl.trim().replace(/\/$/, "")
  return trimmed.endsWith("/api") ? trimmed : `${trimmed}/api`
}

const BASE_URL = getBaseUrl()

// ============================================================================
// Types
// ============================================================================

export interface HealthResponse {
  status: string
  service: string
  version: string
  phases: Record<string, string>
}

export interface PortfolioCompany {
  id: number
  ticker: string
  name: string
  exchange: string
  sector: string
  is_active: boolean
  vol_alert_mult: number
  price_alert_pct: number
}

export interface PriceSnapshot {
  ticker: string
  name: string
  sector: string
  date: string | null
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
  avg_vol_20d: number | null
  pct_change: number | null
  data_source: string
  data_status: "ok" | "no_data" | "stale"
}

export interface Announcement {
  id: number
  exchange: string
  symbol: string
  company: string | null
  headline: string
  description: string | null
  category: string | null
  classification_rationale: string | null
  classification_confidence: string | null
  materiality: "HIGH" | "MEDIUM" | "LOW" | null
  materiality_score: number | null
  materiality_rationale: string | null
  summary: string | null
  filing_dt: string | null
  filing_datetime: string | null
  pdf_url: string | null
  created_at: string
}

export interface CategoryInfo {
  category: string
  materiality: string
  default_score: number
  description: string
  count: number
}

export interface TodaySummary {
  window_hours: number | null
  total_announcements: number
  high_materiality: number
  medium_materiality: number
  low_materiality: number
  active_alerts: number
  categories_breakdown: Record<string, number>
}

export interface FinancialInsights {
  insight_type: string
  scope?: string
  headline_metrics?: Record<string, string>
  growth?: Record<string, string>
  role?: string
  action?: string
  executive_name?: string
  background_bio?: string
  deal_value?: string
  stake?: string
  target?: string
  instrument?: string
  amount?: string
  dividend_rate?: string
  record_date?: string
  outlay?: string
  insight_summary: string
}

export interface PushDigestItem {
  id: number
  symbol: string
  company: string
  category: string
  headline: string
  summary: string | null
  materiality: string
  materiality_score: number
  materiality_rationale: string | null
  filing_datetime: string | null
  pdf_url: string | null
  financial_insights?: FinancialInsights
}

export interface PushMarketAlert {
  id: number
  ticker: string
  alert_type: string
  value: number
  threshold: number
  seen: boolean
  created_at: string | null
  message?: string
}

export interface PriceAlert {
  id: number
  ticker: string
  date: string
  alert_type: string
  value: number
  threshold: number
  seen: boolean
}

export interface PushDigestResponse {
  digest_window_hours: number
  as_of: string
  summary: {
    total_announcements: number
    prioritized_count: number
    collapsed_routine_count: number
    triggered_price_alerts_count: number
    category_breakdown: Record<string, number>
  }
  config_applied: {
    min_materiality_score: number
    portfolio_only: boolean
    enabled_categories: string[]
  }
  triggered_market_alerts: PushMarketAlert[]
  prioritized_announcements: PushDigestItem[]
}

export interface PushSettings {
  digest_window_hours: number
  min_materiality_score: number
  enabled_categories: string[]
  default_price_alert_pct: number
  default_vol_alert_mult: number
  portfolio_only: boolean
  auto_insights: boolean
}

export interface UnifiedAlert {
  id: number
  alert_source: "market_price" | "market_volume" | "corporate_announcement"
  symbol: string
  headline_or_type: string
  value_or_category: string
  threshold_or_materiality: string
  financial_insights?: FinancialInsights | null
  seen: boolean
  created_at: string | null
}

export interface SourceDocument {
  id: number
  title: string
  document_type: "annual_report" | "quarterly_result" | "earnings_call"
  period: string | null
  canonical_url: string
  source_origin: string
  is_verified_primary: boolean
  extraction_status: string
  total_pages: number | null
}

export interface CandidateDocument {
  ticker: string
  document_type: string
  title: string
  period?: string
  canonical_url: string
  source_origin: string
  is_verified_primary: boolean
  verification_notes?: string
}

export interface DocumentListResponse {
  ticker: string
  ingested_count: number
  ingested_documents: SourceDocument[]
  discovered_candidates: CandidateDocument[]
}

export interface Citation {
  document_id: number
  document_title: string
  document_type: string
  canonical_url: string
  page_number: number | null
  section: string | null
  passage_snippet: string
  is_verified_primary: boolean
}

export interface ResearchReport {
  status: string
  ticker: string
  report_version?: string
  mode?: string
  generated_at?: string
  sections: Record<string, string>
  evidence_gaps?: string | null
  sources_used: SourceDocument[]
  citations: Citation[]
  message?: string
}

// ============================================================================
// Fetch Helper
// ============================================================================

async function apiFetch<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${endpoint}`
  const headers = {
    "Content-Type": "application/json",
    ...(options?.headers || {}),
  }

  const res = await fetch(url, { ...options, headers })
  if (!res.ok) {
    let errorDetail = `HTTP ${res.status}: ${res.statusText}`
    try {
      const errJson = await res.json()
      if (errJson.detail) {
        errorDetail = typeof errJson.detail === "string" ? errJson.detail : JSON.stringify(errJson.detail)
      }
    } catch {
      // Fallback to status text
    }
    throw new Error(errorDetail)
  }
  return res.json()
}

// ============================================================================
// API Endpoints
// ============================================================================

export const api = {
  // Health
  getHealth: () => apiFetch<HealthResponse>("/health"),

  // Portfolio
  getCompanies: () => apiFetch<PortfolioCompany[]>("/portfolio/companies"),
  getPrices: () => apiFetch<PriceSnapshot[]>("/portfolio/prices"),
  refreshPrices: () => apiFetch<{ success: string[]; no_data: string[]; alerts_generated: number; snapshots_upserted: number; message: string }>("/portfolio/prices/refresh", { method: "POST" }),
  getPortfolioAlerts: (unseenOnly = true) =>
    apiFetch<PriceAlert[]>(`/portfolio/alerts?unseen_only=${unseenOnly}`),
  updateCompanyThresholds: (ticker: string, data: { vol_alert_mult?: number; price_alert_pct?: number; is_active?: boolean }) =>
    apiFetch<PortfolioCompany>(`/portfolio/companies/${encodeURIComponent(ticker)}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // Today
  getAnnouncements: (params?: {
    hours?: number
    tickers?: string
    categories?: string
    materiality?: string
    search?: string
    portfolio_only?: boolean
    limit?: number
  }) => {
    const q = new URLSearchParams()
    if (params?.hours !== undefined) q.append("hours", params.hours.toString())
    if (params?.tickers) q.append("tickers", params.tickers)
    if (params?.categories) q.append("categories", params.categories)
    if (params?.materiality) q.append("materiality", params.materiality)
    if (params?.search) q.append("search", params.search)
    if (params?.portfolio_only) q.append("portfolio_only", "true")
    if (params?.limit) q.append("limit", params.limit.toString())
    const qs = q.toString() ? `?${q.toString()}` : ""
    return apiFetch<Announcement[]>(`/today/announcements${qs}`)
  },
  refreshAnnouncements: (useFixtures = false) =>
    apiFetch<{ status: string; fetched: number; inserted: number; duplicates_skipped: number; source: string; message: string }>(
      `/today/refresh?use_fixtures=${useFixtures}`,
      { method: "POST" }
    ),
  getCategories: () => apiFetch<CategoryInfo[]>("/today/categories"),
  getTodaySummary: (hours = 24) => apiFetch<TodaySummary>(`/today/summary?hours=${hours}`),
  getTodayAlerts: (unseenOnly = true) => apiFetch<PriceAlert[]>(`/today/alerts?unseen_only=${unseenOnly}`),

  // Push
  getPushDigest: (params?: { hours?: number; min_materiality?: number; portfolio_only?: boolean; category?: string }) => {
    const q = new URLSearchParams()
    if (params?.hours !== undefined) q.append("hours", params.hours.toString())
    if (params?.min_materiality !== undefined) q.append("min_materiality", params.min_materiality.toString())
    if (params?.portfolio_only !== undefined) q.append("portfolio_only", params.portfolio_only.toString())
    if (params?.category) q.append("category", params.category)
    const qs = q.toString() ? `?${q.toString()}` : ""
    return apiFetch<PushDigestResponse>(`/push/digest${qs}`)
  },
  getPushSettings: () => apiFetch<PushSettings>("/push/settings"),
  updatePushSettings: (settings: Partial<PushSettings>) =>
    apiFetch<PushSettings>("/push/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  getUnifiedAlerts: (unseenOnly = false) => apiFetch<UnifiedAlert[]>(`/push/alerts?unseen_only=${unseenOnly}`),
  markAlertSeen: (type: "market" | "announcement", id: number) =>
    apiFetch<{ status: string; seen: boolean }>(`/push/alerts/${type}/${id}/seen`, { method: "PATCH" }),
  evaluateAlerts: (hours = 48) =>
    apiFetch<{ status: string; new_announcement_alerts: number; message: string }>(`/push/evaluate?hours=${hours}`, { method: "POST" }),

  // Research
  getDocuments: (ticker: string, discover = true) =>
    apiFetch<DocumentListResponse>(`/research/documents/${encodeURIComponent(ticker)}?discover=${discover}`),
  ingestDocument: (data: { ticker: string; document_type: string; title: string; canonical_url: string; period?: string }) =>
    apiFetch<SourceDocument>("/research/documents/ingest", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getReport: (ticker: string) => apiFetch<ResearchReport>(`/research/report/${encodeURIComponent(ticker)}`),
  generateReport: (ticker: string, forceRefresh = false) =>
    apiFetch<ResearchReport>("/research/report", {
      method: "POST",
      body: JSON.stringify({ ticker, force_refresh: forceRefresh }),
    }),
}
