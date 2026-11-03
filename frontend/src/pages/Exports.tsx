import { useState } from 'react'
import { api, saveBlob } from '../api/client'
import { Empty, ErrorBanner, Notice, PageHeader } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import type { ExportRec } from '../types'
import { can, errorMessage } from '../utils/format'

const TYPES: [string, string, string][] = [
  ['expense', 'Standard expense CSV', 'Verified invoices with totals, tax and reconciliation status'],
  ['invoice_register', 'Invoice register CSV', 'Full register including due dates, tax IDs and source files'],
  ['bank_reconciliation', 'Bank reconciliation CSV', 'Each allocation: invoice ↔ bank transaction'],
  ['line_items', 'Line-item CSV', 'One row per extracted line item'],
  ['duplicate_review', 'Duplicate-review CSV', 'All duplicate warnings and decisions'],
  ['unmatched_transactions', 'Unmatched transactions CSV', 'Outgoing transactions with money still unallocated'],
]

export default function ExportsPage() {
  const { org } = useAuth()
  const [type, setType] = useState('expense'); const [template, setTemplate] = useState('generic')
  const [from, setFrom] = useState(''); const [to, setTo] = useState(''); const [err, setErr] = useState<string | null>(null); const [msg, setMsg] = useState<string | null>(null)
  const hist = useAsync(() => api.get<ExportRec[]>('/exports'), [])
  async function create() {
    setErr(null); setMsg(null)
    try {
      const r = await api.post<ExportRec>('/exports/csv', { export_type: type, template, date_from: from || null, date_to: to || null })
      setMsg(`Export ready: ${r.row_count} row(s).`); hist.reload(); await download(r)
    } catch (e) { setErr(errorMessage(e)) }
  }
  async function download(r: ExportRec) { saveBlob(await api.blob(r.download_url), `${r.export_type}-${r.created_at.slice(0, 10)}.csv`) }
  return (
    <>
      <PageHeader title="Accounting exports" subtitle="Only verified invoices are exported. Text cells that start with = + - @ are neutralised against spreadsheet formula injection." />
      <ErrorBanner message={err} onClose={() => setErr(null)} />
      {msg && <Notice tone="ok">{msg}</Notice>}
      {can(org?.role, 'export') && (
        <div className="card mb-5 p-4">
          <div className="grid gap-2 md:grid-cols-2">
            {TYPES.map(([k, label, d]) => (
              <label key={k} className={`flex cursor-pointer gap-2 rounded border p-2.5 ${type === k ? 'border-info bg-info-soft' : 'border-paper-rule'}`}>
                <input type="radio" name="etype" checked={type === k} onChange={() => setType(k)} /><span><span className="block text-sm font-medium">{label}</span><span className="text-xs text-ink-400">{d}</span></span>
              </label>))}
          </div>
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <label><span className="label">From</span><input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
            <label><span className="label">To</span><input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} /></label>
            <label><span className="label">Column template</span><select className="input" value={template} onChange={(e) => setTemplate(e.target.value)}><option value="generic">Generic (field names)</option><option value="simple_ledger">Simple ledger headers</option></select></label>
            <button className="btn-primary" onClick={create}>Generate & download</button>
          </div>
          <p className="mt-3 text-xs text-ink-400">Templates are examples. Accounting products differ, so check the column layout against your software's import guide before importing.</p>
        </div>
      )}
      <div className="card overflow-x-auto">
        <h3 className="px-3 pt-3 text-sm font-semibold">Export history</h3>
        {!hist.data?.length ? <Empty>No exports yet.</Empty> : (
          <table className="w-full"><thead><tr><th className="th">When</th><th className="th">Type</th><th className="th text-right">Rows</th><th className="th">SHA-256</th><th className="th" /></tr></thead>
            <tbody>{hist.data.map((e) => <tr key={e.id}><td className="td whitespace-nowrap">{new Date(e.created_at).toLocaleString('en-GB')}</td><td className="td">{e.export_type.replace('_', ' ')}</td><td className="td money">{e.row_count}</td><td className="td font-mono text-[11px] text-ink-400">{e.content_sha256.slice(0, 16)}…</td><td className="td text-right"><button className="btn-ghost !py-0.5" onClick={() => download(e)}>Download</button></td></tr>)}</tbody></table>
        )}
      </div>
    </>
  )
}
