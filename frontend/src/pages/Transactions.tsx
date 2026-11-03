import { useState } from 'react'
import { api } from '../api/client'
import { Empty, ErrorBanner, Notice, PageHeader, Pagination, Spinner, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import type { Page, Transaction } from '../types'
import { CURRENCIES, can, errorMessage, formatDate, formatMoney } from '../utils/format'

interface Preview { headers: string[]; suggested_mapping: Record<string, string>; sample_rows: Record<string, string>[]; row_count: number }
interface Result { imported: number; skipped_duplicates: number; error_count: number; errors: { row: number; message: string }[]; dry_run: boolean }
const FIELDS = [['date', 'Date'], ['description', 'Description'], ['amount', 'Amount (single column)'], ['debit', 'Debit / withdrawal'], ['credit', 'Credit / deposit'], ['currency', 'Currency'], ['reference', 'Reference'], ['account', 'Account']] as const

export default function Transactions() {
  const { org } = useAuth()
  const [q, setQ] = useState(''); const [status, setStatus] = useState(''); const [page, setPage] = useState(1)
  const { data, error, loading, reload } = useAsync(() => api.get<Page<Transaction>>('/transactions', { q, status, page, page_size: 20 }), [q, status, page])
  const [file, setFile] = useState<File | null>(null)
  const [prev, setPrev] = useState<Preview | null>(null)
  const [map, setMap] = useState<Record<string, string>>({})
  const [sign, setSign] = useState('negative_is_outflow'); const [dfmt, setDfmt] = useState(''); const [cur, setCur] = useState('')
  const [res, setRes] = useState<Result | null>(null); const [err, setErr] = useState<string | null>(null); const [open, setOpen] = useState(false)

  const form = (dry: boolean) => {
    const fd = new FormData()
    fd.append('file', file!); fd.append('mapping', JSON.stringify(Object.fromEntries(Object.entries(map).filter(([, v]) => v))))
    fd.append('sign_convention', sign); if (dfmt) fd.append('date_format', dfmt); if (cur) fd.append('default_currency', cur); fd.append('dry_run', String(dry))
    return fd
  }
  async function choose(f: File | null) {
    setFile(f); setRes(null); setErr(null); setPrev(null)
    if (!f) return
    try {
      const fd = new FormData(); fd.append('file', f)
      const p = await api.form<Preview>('/transactions/import/preview', fd); setPrev(p); setMap(p.suggested_mapping)
    } catch (e) { setErr(errorMessage(e)) }
  }
  async function run(dry: boolean) {
    setErr(null)
    try { const r = await api.form<Result>('/transactions/import', form(dry)); setRes(r); if (!dry) { reload(); setPage(1) } } catch (e) { setErr(errorMessage(e)) }
  }
  return (
    <>
      <PageHeader title="Bank transactions" subtitle="Import statements as CSV. Negative amounts mean money leaving the account (configurable below)."
        actions={can(org?.role, 'import') ? <button className="btn-primary" onClick={() => setOpen(!open)}>{open ? 'Close import' : 'Import CSV'}</button> : undefined} />
      {open && (
        <div className="card mb-5 space-y-4 p-4">
          <input type="file" accept=".csv,text/csv" aria-label="Bank CSV file" onChange={(e) => choose(e.target.files?.[0] ?? null)} />
          <ErrorBanner message={err} />
          {prev && (<>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {FIELDS.map(([k, label]) => (
                <label key={k}><span className="label">{label}</span>
                  <select className="input" value={map[k] ?? ''} onChange={(e) => setMap({ ...map, [k]: e.target.value })}><option value="">— none —</option>{prev.headers.map((h) => <option key={h}>{h}</option>)}</select></label>
              ))}
              <label><span className="label">Sign convention</span><select className="input" value={sign} onChange={(e) => setSign(e.target.value)}><option value="negative_is_outflow">Negative = money out</option><option value="positive_is_outflow">Positive = money out</option></select></label>
              <label><span className="label">Date format</span><select className="input" value={dfmt} onChange={(e) => setDfmt(e.target.value)}><option value="">Organization default ({org?.date_format})</option><option value="DMY">Day / Month / Year</option><option value="MDY">Month / Day / Year</option><option value="ISO">Year-Month-Day</option></select></label>
              <label><span className="label">Default currency</span><select className="input" value={cur} onChange={(e) => setCur(e.target.value)}><option value="">Organization default ({org?.default_currency})</option>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></label>
            </div>
            <div className="overflow-x-auto rounded border border-paper-rule"><table className="w-full"><thead><tr>{prev.headers.map((h) => <th key={h} className="th">{h}</th>)}</tr></thead><tbody>{prev.sample_rows.map((r, i) => <tr key={i}>{prev.headers.map((h) => <td key={h} className="td font-mono text-xs">{r[h]}</td>)}</tr>)}</tbody></table></div>
            <div className="flex items-center gap-2"><button className="btn-ghost" onClick={() => run(true)}>Validate (dry run)</button><button className="btn-primary" onClick={() => run(false)}>Import {prev.row_count} rows</button></div>
          </>)}
          {res && <Notice tone={res.error_count ? 'warn' : 'ok'}>{res.dry_run ? 'Dry run: ' : ''}{res.imported} {res.dry_run ? 'would be imported' : 'imported'} · {res.skipped_duplicates} already present (skipped) · {res.error_count} rejected{res.errors.slice(0, 3).map((e) => <div key={e.row} className="text-xs">Row {e.row}: {e.message}</div>)}</Notice>}
        </div>
      )}
      <ErrorBanner message={error} />
      <div className="card mb-3 flex flex-wrap gap-3 p-3">
        <input className="input !w-64" placeholder="Search description or reference" aria-label="Search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
        <select className="input !w-48" aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}><option value="">All</option><option value="UNMATCHED">Unmatched</option><option value="PARTIALLY_RECONCILED">Partially reconciled</option><option value="RECONCILED">Reconciled</option><option value="INFLOW">Inflows</option></select>
      </div>
      <div className="card overflow-x-auto">
        {loading && !data ? <Spinner /> : !data?.items.length ? <Empty>No transactions yet. Import a bank statement CSV to begin.</Empty> : (
          <table className="w-full"><thead><tr><th className="th">Date</th><th className="th">Description</th><th className="th">Reference</th><th className="th text-right">Amount</th><th className="th text-right">Allocated</th><th className="th">Status</th></tr></thead>
            <tbody>{data.items.map((t) => (
              <tr key={t.id}><td className="td whitespace-nowrap">{formatDate(t.transaction_date)}</td><td className="td">{t.description}</td><td className="td font-mono text-xs">{t.reference ?? '—'}</td>
                <td className={`td money ${Number(t.amount) < 0 ? '' : 'text-ok'}`}>{formatMoney(t.amount, t.currency)}</td><td className="td money text-ink-400">{Number(t.allocated) ? formatMoney(t.allocated, t.currency) : '—'}</td><td className="td"><StatusBadge status={t.status} /></td></tr>))}</tbody></table>
        )}
        {data && <Pagination page={page} total={data.total} size={20} onPage={setPage} />}
      </div>
    </>
  )
}
