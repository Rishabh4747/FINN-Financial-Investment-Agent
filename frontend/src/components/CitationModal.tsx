import React from "react"
import { X, ExternalLink, ShieldCheck, Bookmark } from "lucide-react"
import type { Citation } from "../api/client"

interface CitationModalProps {
  citation: Citation | null
  onClose: () => void
}

export const CitationModal: React.FC<CitationModalProps> = ({ citation, onClose }) => {
  if (!citation) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-fade-in">
      <div className="relative w-full max-w-xl bg-[#0d1527] border border-white/[0.1] rounded-2xl p-6 shadow-2xl text-slate-100 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-white/[0.08] pb-4 mb-4">
          <div className="flex items-start gap-3">
            <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0 mt-0.5">
              <Bookmark className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-sans font-semibold px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700/60 uppercase">
                  {citation.document_type.replace(/_/g, " ")}
                </span>
                {citation.page_number && (
                  <span className="text-xs font-mono font-semibold px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-400 border border-emerald-500/30">
                    Page {citation.page_number}
                  </span>
                )}
              </div>
              <h3 className="font-sans font-bold text-base text-white line-clamp-2">
                {citation.document_title}
              </h3>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Verification Origin Status */}
        <div className="mb-4 p-3.5 rounded-xl bg-slate-900/80 border border-white/[0.06] flex items-center justify-between text-xs font-sans">
          <div className="flex items-center gap-2">
            <ShieldCheck className={`w-4 h-4 ${citation.is_verified_primary ? "text-emerald-400" : "text-amber-400"}`} />
            <span className="text-slate-200 font-medium">
              {citation.is_verified_primary ? "Verified Official Primary Filing" : "Third-Party Document Origin"}
            </span>
          </div>
          <a
            href={citation.canonical_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-emerald-400 hover:text-emerald-300 font-medium"
          >
            <span>Open Source PDF</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>

        {/* Document Section */}
        {citation.section && (
          <div className="mb-4">
            <span className="text-xs font-sans text-slate-400 block mb-1 font-medium">Filing Section</span>
            <span className="inline-block px-3 py-1 rounded-lg bg-slate-900 text-slate-200 text-xs font-sans font-medium border border-white/[0.06]">
              {citation.section}
            </span>
          </div>
        )}

        {/* Verbatim Ingested Passage */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-sans font-semibold text-slate-400">Verbatim Passage Snippet</span>
            <span className="text-[11px] font-sans text-slate-500">Indexed via SQLite FTS5 BM25</span>
          </div>
          <blockquote className="p-4 rounded-xl bg-slate-950/80 border border-white/[0.06] text-xs font-mono text-slate-200 leading-relaxed whitespace-pre-wrap border-l-2 border-l-emerald-500">
            "{citation.passage_snippet}"
          </blockquote>
        </div>

        {/* Footer */}
        <div className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-xs font-sans font-semibold transition-colors"
          >
            Close Provenance
          </button>
        </div>
      </div>
    </div>
  )
}
