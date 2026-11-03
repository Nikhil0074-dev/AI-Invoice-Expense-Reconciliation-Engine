import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Badge, Empty, ErrorBanner, PageHeader, Pagination, Spinner, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import type { Invoice, Page } from '../types'
import { formatDate, formatMoney } from '../utils/format'

export default function ReviewQueue() {
  const [page, setPage] = useState(1)
  const { data, error, loading } = useAsync(() => api.get<Page<Invoice>>('/invoices', { needs_review: true, page, page_size: 15 }), [page])
  return (
    <>
      <PageHeader title="Review queue" subtitle="Nothing is final until a person has checked it. Items with warnings are listed with the reasons." />
      <ErrorBanner message={error} />
      <div className="card overflow-x-auto">
        {loading && !data ? <Spinner /> : !data?.items.length ? <Empty>The queue is empty — every extracted invoice has been verified.</Empty> : (
          <table className="w-full">
            <thead><tr><th className="th">Document</th><th className="th">Vendor</th><th className="th">Date</th><th className="th text-right">Total</th><th className="th">Why it needs attention</th><th className="th" /></tr></thead>
            <tbody>
              {data.items.map((i) => (
                <tr key={i.id}>
                  <td className="td max-w-[200px] truncate">{i.original_filename}</td>
                  <td className="td">{i.vendor_name ?? '—'}</td>
                  <td className="td whitespace-nowrap">{formatDate(i.invoice_date)}</td>
                  <td className="td money">{formatMoney(i.total_amount, i.currency)}</td>
                  <td className="td"><div className="flex flex-wrap gap-1">{i.review_reasons.length ? i.review_reasons.map((r) => <Badge key={r} tone="warn">{r}</Badge>) : <Badge tone="info">Awaiting verification</Badge>}{i.document_status === 'DUPLICATE_REVIEW' && <StatusBadge status="DUPLICATE_REVIEW" />}</div></td>
                  <td className="td text-right"><Link className="btn-primary !py-0.5" to={`/invoices/${i.id}`}>Review</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && <Pagination page={page} total={data.total} size={15} onPage={setPage} />}
      </div>
    </>
  )
}
