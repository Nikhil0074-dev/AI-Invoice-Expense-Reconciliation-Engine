import { useEffect, useState } from 'react'
import { api } from '../api/client'
import DocumentPreview from '../components/documents/DocumentPreview'
import { Badge, Empty, ErrorBanner, Notice, PageHeader, ScoreBar, Spinner, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import type { Invoice, Match, Page, Transaction } from '../types'
import { can, errorMessage, formatDate, formatMoney } from '../utils/format'

export default function Reconciliation() {
  const { org } = useAuth()
  const writable = can(org?.role, 'reconcile')
  const invoices = useAsync(() => api.get<Page<Invoice>>('/invoices', { review_status: 'VERIFIED', page_size: 100 }), [])
  const [sel, setSel] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null); const [err, setErr] = useState<string | null>(null)
  const list = invoices.data?.items ?? []
  useEffect(() => { if (!sel && list.length) setSel((list.find((i) => i.reconciliation_status !== 'CONFIRMED') ?? list[0]).id) }, [list.length])
  const inv = list.find((i) => i.id === sel) ?? null
  const matches = useAsync(() => (sel ? api.get<Match[]>('/reconciliation/matches', { invoice_id: sel }) : Promise.resolve([])), [sel, inv?.reconciliation_status, inv?.allocated_amount])
  const sugg = useAsync(() => (sel && writable ? api.get<Match[]>('/reconciliation/suggestions', { invoice_id: sel }) : sel ? api.get<Match[]>('/reconciliation/suggestions', { invoice_id: sel, refresh: false }) : Promise.resolve([])), [sel])
  const [search, setSearch] = useState('')
  const txs = useAsync(() => (sel ? api.get<Page<Transaction>>('/transactions', { q: search, status: 'UNMATCHED', page_size: 8 }) : Promise.resolve(null)), [sel, search, inv?.allocated_amount])
  const [amt, setAmt] = useState<Record<string, string>>({})

  async function act(fn: () => Promise<unknown>, ok: string) {
    setErr(null); setMsg(null)
    try { await fn(); setMsg(ok); await invoices.reload(); await sugg.reload(); await matches.reload() } catch (e) { setErr(errorMessage(e)) }
  }
  const remaining = inv ? Number(inv.total_amount) - Number(inv.allocated_amount ?? 0) : 0
  const confirmed = (matches.data ?? []).filter((m) => ['CONFIRMED', 'PARTIALLY_RECONCILED'].includes(m.match_status))
  const open = sugg.data ?? []

  return (
    <>
      <PageHeader title="Reconciliation workspace" subtitle="Suggestions are never applied automatically. Confirm, reject or link transactions yourself."
        actions={writable ? <button className="btn-ghost" onClick={() => act(() => api.post('/reconciliation/run'), 'Suggestions refreshed for all verified invoices.')}>Re-run for all</button> : undefined} />
      <ErrorBanner message={err ?? invoices.error} onClose={() => setErr(null)} />
      {msg && <Notice tone="ok">{msg}</Notice>}
      {invoices.loading && !invoices.data ? <Spinner /> : !list.length ? <Empty>No verified invoices yet. Verify an invoice in the review queue to reconcile it.</Empty> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <div className="space-y-3">
            <div className="card max-h-44 overflow-y-auto">
              {list.map((i) => (
                <button key={i.id} onClick={() => setSel(i.id)} className={`flex w-full items-center justify-between gap-2 border-b border-paper-rule px-3 py-2 text-left text-sm ${i.id === sel ? 'bg-info-soft' : 'hover:bg-paper-tint'}`}>
                  <span className="min-w-0"><span className="block truncate font-medium">{i.vendor_name}</span><span className="font-mono text-[11px] text-ink-400">{i.invoice_number ?? 'no number'} · {formatDate(i.invoice_date)}</span></span>
                  <span className="flex shrink-0 items-center gap-2"><span className="font-mono text-xs">{formatMoney(i.total_amount, i.currency)}</span><StatusBadge status={i.reconciliation_status} /></span>
                </button>
              ))}
            </div>
            {inv && <>
              <div className="card grid grid-cols-3 gap-3 p-3 text-sm">
                <div><div className="label">Invoice total</div><div className="font-mono">{formatMoney(inv.total_amount, inv.currency)}</div></div>
                <div><div className="label">Reconciled</div><div className="font-mono text-ok">{formatMoney(inv.allocated_amount, inv.currency)}</div></div>
                <div><div className="label">Remaining</div><div className="font-mono">{formatMoney(remaining, inv.currency)}</div></div>
              </div>
              <DocumentPreview documentId={inv.document_id} mime={inv.mime_type} height={420} />
            </>}
          </div>
          <div className="space-y-3">
            {confirmed.length > 0 && (
              <div className="card"><h3 className="px-3 pt-3 text-sm font-semibold">Confirmed links</h3>
                {confirmed.map((m) => (
                  <div key={m.id} className="flex items-center justify-between gap-2 border-b border-paper-rule px-3 py-2 text-sm last:border-0">
                    <div className="min-w-0">{m.transactions.map((t) => <div key={t.id} className="truncate">{formatDate(t.transaction_date)} · {t.description} · <span className="font-mono">{formatMoney(t.amount, t.currency)}</span></div>)}<div className="text-xs text-ink-400">{m.kind === 'MANUAL' ? 'Linked manually' : m.match_explanation}</div></div>
                    {writable && <button className="btn-danger !py-0.5" onClick={() => act(() => api.patch(`/reconciliation/matches/${m.id}`, { action: 'unlink' }), 'Match unlinked.')}>Unlink</button>}
                  </div>))}
              </div>
            )}
            <div className="card">
              <h3 className="px-3 pt-3 text-sm font-semibold">Suggested transactions</h3>
              {sugg.loading && !sugg.data ? <Spinner /> : !open.length ? <Empty>{inv?.reconciliation_status === 'CONFIRMED' ? 'This invoice is fully reconciled.' : 'No likely transactions found. Import more statements or link one manually below.'}</Empty> : open.map((m) => (
                <div key={m.id} className="border-b border-paper-rule px-3 py-3 last:border-0">
                  <div className="mb-1.5 flex items-center justify-between gap-2"><div className="flex items-center gap-2"><ScoreBar score={m.match_score ?? 0} /><StatusBadge status={m.match_status} />{m.kind !== 'SINGLE' && <Badge tone="info">{m.kind === 'SPLIT' ? 'split payment' : 'partial payment'}</Badge>}</div></div>
                  {m.transactions.map((t) => <div key={t.id} className="flex justify-between gap-3 text-sm"><span className="truncate">{formatDate(t.transaction_date)} · {t.description}</span><span className="font-mono">{formatMoney(t.amount, t.currency)}</span></div>)}
                  <p className="mt-1.5 text-xs text-ink-600">{m.match_explanation}</p>
                  <div className="mt-1 flex gap-3 font-mono text-[10px] text-ink-400">{(['amount', 'vendor', 'date', 'reference'] as const).map((k) => <span key={k}>{k[0].toUpperCase()}={Number(m.signals?.[k] ?? 0).toFixed(2)}</span>)}</div>
                  {writable && <div className="mt-2 flex gap-2"><button className="btn-ok !py-0.5" onClick={() => act(() => api.post('/reconciliation/matches', { match_id: m.id }), 'Match confirmed.')}>Confirm match</button><button className="btn-ghost !py-0.5" onClick={() => act(() => api.post(`/reconciliation/matches/${m.id}/reject`), 'Suggestion rejected.')}>Reject</button></div>}
                </div>))}
            </div>
            {writable && inv && inv.reconciliation_status !== 'CONFIRMED' && (
              <div className="card p-3">
                <h3 className="mb-2 text-sm font-semibold">Link a transaction manually</h3>
                <input className="input mb-2" placeholder="Search unmatched transactions…" aria-label="Search transactions" value={search} onChange={(e) => setSearch(e.target.value)} />
                {(txs.data?.items ?? []).map((t) => {
                  const room = Math.min(Number(t.remaining), remaining)
                  return (
                    <div key={t.id} className="flex items-center gap-2 border-t border-paper-rule py-1.5 text-sm">
                      <span className="min-w-0 flex-1 truncate">{formatDate(t.transaction_date)} · {t.description}</span>
                      <span className="font-mono text-xs">{formatMoney(t.remaining, t.currency)}</span>
                      <input className="input !w-24 text-right font-mono" aria-label="Amount to allocate" inputMode="decimal" value={amt[t.id] ?? room.toFixed(2)} onChange={(e) => setAmt({ ...amt, [t.id]: e.target.value })} />
                      <button className="btn-ghost !py-0.5" onClick={() => act(() => api.post('/reconciliation/matches', { invoice_id: inv.id, allocations: [{ transaction_id: t.id, amount: amt[t.id] ?? room.toFixed(2) }] }), 'Transaction linked.')}>Link</button>
                    </div>)
                })}
                {txs.data && !txs.data.items.length && <p className="text-xs text-ink-400">No unmatched transactions found.</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
