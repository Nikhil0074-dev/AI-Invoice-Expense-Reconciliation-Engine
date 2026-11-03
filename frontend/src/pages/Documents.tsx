import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, saveBlob } from '../api/client'
import Dropzone from '../components/upload/Dropzone'
import { Badge, Empty, ErrorBanner, PageHeader, Pagination, Spinner, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import type { DocumentRow, Page } from '../types'
import { CURRENCIES, can, errorMessage, formatDate, formatMoney } from '../utils/format'

const STATUSES = ['QUEUED', 'PROCESSING', 'REVIEW_REQUIRED', 'DUPLICATE_REVIEW', 'READY_FOR_RECONCILIATION', 'RECONCILED', 'FAILED', 'ARCHIVED']

export default function Documents() {
  const { org } = useAuth()
  const [f, setF] = useState({ q: '', status: '', currency: '', date_from: '', date_to: '', min_amount: '', max_amount: '' })
  const [sort, setSort] = useState({ sort: 'created_at', direction: 'desc' })
  const [page, setPage] = useState(1)
  const [err, setErr] = useState<string | null>(null)
  const size = 15
  const { data, error, loading, reload } = useAsync(
    () => api.get<Page<DocumentRow>>('/documents', { ...f, ...sort, page, page_size: size }),
    [f, sort, page],
    (d) => (d?.items.some((x) => ['QUEUED', 'PROCESSING'].includes(x.processing_status)) ? 1500 : null),
  )
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setF({ ...f, [k]: e.target.value }); setPage(1) }
  const th = (label: string, key?: string) => (
    <th className="th" onClick={key ? () => setSort({ sort: key, direction: sort.sort === key && sort.direction === 'asc' ? 'desc' : 'asc' }) : undefined} style={{ cursor: key ? 'pointer' : 'default' }}>
      {label}{key && sort.sort === key ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ''}
    </th>
  )
  async function act(fn: () => Promise<unknown>) { try { setErr(null); await fn(); reload() } catch (e) { setErr(errorMessage(e)) } }

  return (
    <>
      <PageHeader title="Documents" subtitle="Upload invoices and receipts; extraction runs in the background." />
      {can(org?.role, 'upload') && <Dropzone maxMb={org?.max_upload_mb ?? 15} onUploaded={reload} />}
      <ErrorBanner message={err ?? error} onClose={() => setErr(null)} />
      <div className="card mb-4 grid grid-cols-2 gap-3 p-3 md:grid-cols-7">
        <input className="input col-span-2" placeholder="Search vendor, invoice no, file…" aria-label="Search" value={f.q} onChange={set('q')} />
        <select className="input" aria-label="Status" value={f.status} onChange={set('status')}><option value="">All statuses</option>{STATUSES.map((s) => <option key={s} value={s}>{s.replaceAll('_', ' ').toLowerCase()}</option>)}</select>
        <select className="input" aria-label="Currency" value={f.currency} onChange={set('currency')}><option value="">Any currency</option>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select>
        <input className="input" type="date" aria-label="From date" value={f.date_from} onChange={set('date_from')} />
        <input className="input" type="date" aria-label="To date" value={f.date_to} onChange={set('date_to')} />
        <div className="flex gap-1"><input className="input" placeholder="Min" inputMode="decimal" value={f.min_amount} onChange={set('min_amount')} /><input className="input" placeholder="Max" inputMode="decimal" value={f.max_amount} onChange={set('max_amount')} /></div>
      </div>
      <div className="card overflow-x-auto">
        {loading && !data ? <Spinner /> : !data?.items.length ? <Empty>No documents match. Upload your first invoice above.</Empty> : (
          <table className="w-full">
            <thead><tr>{th('Document', 'filename')}{th('Vendor', 'vendor')}{th('Invoice no.')}{th('Date', 'invoice_date')}<th className="th text-right">Total</th>{th('Status', 'status')}{th('')}</tr></thead>
            <tbody>
              {data.items.map((d) => (
                <tr key={d.id} className="hover:bg-paper-tint/60">
                  <td className="td max-w-[220px]"><div className="truncate font-medium">{d.original_filename}</div><div className="text-[11px] text-ink-400">{d.extraction_method ? `${d.extraction_method === 'NATIVE_PDF' ? 'Native text' : d.extraction_method === 'OCR' ? `OCR ${Math.round((d.ocr_confidence ?? 0) * 100)}%` : 'Mixed'}` : ''}</div></td>
                  <td className="td">{d.vendor_name ?? '—'}</td>
                  <td className="td font-mono text-xs">{d.invoice_number ?? '—'}</td>
                  <td className="td whitespace-nowrap">{formatDate(d.invoice_date)}</td>
                  <td className="td money">{formatMoney(d.total_amount, d.currency)}</td>
                  <td className="td"><div className="flex flex-wrap gap-1"><StatusBadge status={d.processing_status} />{d.open_duplicate_flags > 0 && <Badge tone="warn">dup ×{d.open_duplicate_flags}</Badge>}</div></td>
                  <td className="td whitespace-nowrap text-right">
                    {d.invoice_id && <Link className="btn-ghost !py-0.5" to={`/invoices/${d.invoice_id}`}>{d.processing_status === 'REVIEW_REQUIRED' || d.processing_status === 'DUPLICATE_REVIEW' ? 'Review' : 'Open'}</Link>}{' '}
                    {d.processing_status === 'FAILED' && can(org?.role, 'process') && <button className="btn-ghost !py-0.5" onClick={() => act(() => api.post(`/documents/${d.id}/process`))}>Retry</button>}{' '}
                    <button className="btn-ghost !py-0.5" onClick={() => act(async () => saveBlob(await api.blob(`/documents/${d.id}/download`), d.original_filename))}>Download</button>{' '}
                    {can(org?.role, 'delete') && <button className="btn-danger !py-0.5" onClick={() => confirm(`Delete ${d.original_filename}?`) && act(() => api.del(`/documents/${d.id}`))}>Delete</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && <Pagination page={page} total={data.total} size={size} onPage={setPage} />}
      </div>
    </>
  )
}
