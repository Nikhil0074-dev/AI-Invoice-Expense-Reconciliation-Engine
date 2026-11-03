import { useState } from 'react'
import { api } from '../api/client'
import { Badge, Empty, ErrorBanner, PageHeader, Spinner, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import type { DuplicateFlag } from '../types'
import { can, errorMessage } from '../utils/format'

const CAT_TONE = { EXACT: 'bad', LIKELY: 'warn', POSSIBLE: 'info' } as const

export default function DuplicatesPage() {
  const { org } = useAuth()
  const [status, setStatus] = useState('OPEN'); const [err, setErr] = useState<string | null>(null)
  const { data, error, loading, reload } = useAsync(() => api.get<DuplicateFlag[]>('/duplicates', { status }), [status])
  async function review(id: string, decision: 'dismiss' | 'confirm_duplicate') {
    setErr(null)
    try { await api.post(`/duplicates/${id}/review`, { decision }); reload() } catch (e) { setErr(errorMessage(e)) }
  }
  return (
    <>
      <PageHeader title="Duplicate review" subtitle="Duplicates are flagged, never deleted. Confirming one archives the newer document (it stays viewable)."
        actions={<select className="input !w-44" aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="OPEN">Open</option><option value="DISMISSED">Dismissed</option><option value="CONFIRMED_DUPLICATE">Confirmed duplicates</option><option value="">All</option></select>} />
      <ErrorBanner message={err ?? error} onClose={() => setErr(null)} />
      {loading && !data ? <Spinner /> : !data?.length ? <div className="card"><Empty>No duplicate warnings in this view.</Empty></div> : (
        <div className="space-y-3">
          {data.map((f) => (
            <div key={f.id} className="card p-4">
              <div className="mb-2 flex flex-wrap items-center gap-2"><Badge tone={CAT_TONE[f.category as keyof typeof CAT_TONE]}>{f.category.toLowerCase()} duplicate</Badge><span className="font-mono text-xs text-ink-400">{f.detection_method.replace('_', ' ').toLowerCase()} · confidence {Math.round(f.confidence_score * 100)}%</span><StatusBadge status={f.review_status} /></div>
              <div className="grid gap-1 text-sm md:grid-cols-2"><div><span className="label">Uploaded document</span>{f.document_filename}</div><div><span className="label">Matches existing</span>{f.possible_duplicate_filename}</div></div>
              <p className="mt-2 rounded bg-paper-tint px-3 py-2 text-sm">{f.evidence}</p>
              {f.review_status === 'OPEN' && can(org?.role, 'duplicates') && (
                <div className="mt-3 flex gap-2"><button className="btn-ghost" onClick={() => review(f.id, 'dismiss')}>Not a duplicate</button><button className="btn-danger" onClick={() => confirm('Archive the newer document as a duplicate? It is kept, but excluded from totals and exports.') && review(f.id, 'confirm_duplicate')}>Confirm duplicate</button></div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  )
}
