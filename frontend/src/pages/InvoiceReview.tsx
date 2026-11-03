import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import DocumentPreview from '../components/documents/DocumentPreview'
import LineItemsEditor from '../components/invoice-review/LineItemsEditor'
import { Badge, ErrorBanner, Field, Notice, PageHeader, Spinner, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import type { AuditRow, Invoice, LineItem } from '../types'
import { CURRENCIES, can, errorMessage, formatDate } from '../utils/format'
import { invoiceFormSchema, toPayload, type InvoiceForm } from '../utils/validation'

const toForm = (i: Invoice): InvoiceForm => ({
  vendor_name: i.vendor_name ?? '', invoice_number: i.invoice_number ?? '', invoice_date: i.invoice_date ?? '', due_date: i.due_date ?? '',
  currency: i.currency ?? '', subtotal: i.subtotal ? String(Number(i.subtotal)) : '', tax_amount: i.tax_amount ? String(Number(i.tax_amount)) : '',
  discount_amount: i.discount_amount ? String(Number(i.discount_amount)) : '', total_amount: i.total_amount ? String(Number(i.total_amount)) : '',
  tax_id: i.tax_id ?? '', category: i.category ?? '', description: i.description ?? '',
})
const trim = (s: string | null) => (s === null ? null : String(Number(s)))
const norm = (s: string | null) => (s === null ? '' : String(Number(s)))

export default function InvoiceReview() {
  const { id } = useParams()
  const { org } = useAuth()
  const { data: inv, error, reload, setData } = useAsync(() => api.get<Invoice>(`/invoices/${id}`), [id])
  const audit = useAsync(() => (can(org?.role, 'audit') ? api.get<AuditRow[]>('/audit-logs', { entity_type: 'invoice', entity_id: id }) : Promise.resolve([])), [id, inv?.updated_at])
  const [form, setForm] = useState<InvoiceForm | null>(null)
  const [items, setItems] = useState<LineItem[]>([])
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const [ack, setAck] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (inv) { setForm(toForm(inv)); setItems(inv.line_items.map((li) => ({ ...li, quantity: trim(li.quantity), unit_price: trim(li.unit_price), tax_amount: trim(li.tax_amount), line_total: trim(li.line_total) }))); setErrs({}) } }, [inv?.id, inv?.updated_at])
  if (error) return <ErrorBanner message={error} />
  if (!inv || !form) return <Spinner />
  const editable = can(org?.role, 'edit')
  const uncertain = new Set(inv.uncertain_fields ?? [])
  const set = (k: keyof InvoiceForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value })
  const original = inv.extraction_original ?? {}
  const changed = (k: keyof InvoiceForm) => k in original && original[k] !== null && (k.endsWith('_amount') || k === 'subtotal' ? norm(original[k]) : (original[k] ?? '')) !== (form[k] ?? '')
  const flag = (k: string) => (errs[k] ? 'error' as const : uncertain.has(k) ? 'uncertain' as const : undefined)
  const hint = (k: keyof InvoiceForm) => errs[k] ?? (changed(k) ? `OCR read: ${original[k]}` : (original.notes?.[k] as string | undefined))
  const cls = (k: string) => `input ${errs[k] ? '!border-bad' : uncertain.has(k) ? '!border-warn bg-warn-soft/40' : ''}`

  async function save(): Promise<boolean> {
    const parsed = invoiceFormSchema.safeParse(form)
    if (!parsed.success) {
      const e: Record<string, string> = {}
      parsed.error.issues.forEach((i) => { e[String(i.path[0])] = i.message })
      setErrs(e); setMsg({ tone: 'bad', text: 'Fix the highlighted fields first.' }); return false
    }
    setErrs({}); setBusy(true)
    try {
      const updated = await api.patch<Invoice>(`/invoices/${inv!.id}`, { ...toPayload(parsed.data), line_items: items.map((i) => ({ description: i.description, quantity: i.quantity, unit_price: i.unit_price, tax_amount: i.tax_amount, line_total: i.line_total })) })
      setData(updated); setMsg({ tone: 'ok', text: 'Corrections saved and recorded in the audit trail.' }); return true
    } catch (e) { setMsg({ tone: 'bad', text: errorMessage(e) }); return false } finally { setBusy(false) }
  }
  async function verify() {
    if (!(await save())) return
    setBusy(true)
    try { setData(await api.post<Invoice>(`/invoices/${inv!.id}/verify`, { acknowledge_warnings: ack })); setMsg({ tone: 'ok', text: 'Invoice verified — it can now be reconciled and exported.' }) }
    catch (e) { setMsg({ tone: 'bad', text: errorMessage(e) }) } finally { setBusy(false); reload() }
  }
  async function reprocess() {
    if (!confirm('Re-run extraction? Unsaved and saved corrections on this invoice will be replaced by a fresh extraction.')) return
    try { await api.post(`/documents/${inv!.document_id}/process`); setMsg({ tone: 'ok', text: 'Reprocessing queued…' }); setTimeout(reload, 1500) } catch (e) { setMsg({ tone: 'bad', text: errorMessage(e) }) }
  }
  const warnings = (inv.warnings ?? []).filter((w) => w.severity !== 'info' || w.code === 'MISSING_INVOICE_NUMBER')
  const needsAck = warnings.some((w) => w.severity === 'warning')
  const verified = inv.review_status === 'VERIFIED'

  return (
    <>
      <PageHeader title={inv.original_filename ?? 'Invoice'} subtitle={`Review extracted data against the original document`}
        actions={<><Link to="/review" className="btn-ghost">← Review queue</Link><StatusBadge status={inv.document_status ?? inv.review_status} />{inv.reconciliation_status !== 'UNMATCHED' && <StatusBadge status={inv.reconciliation_status} />}</>} />
      {msg && <Notice tone={msg.tone === 'ok' ? 'ok' : 'bad'}>{msg.text}</Notice>}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        <DocumentPreview documentId={inv.document_id} mime={inv.mime_type} />
        <div className="space-y-4">
          {inv.review_reasons.length > 0 && !verified && <div className="flex flex-wrap items-center gap-1.5 text-xs"><span className="text-ink-400">Needs attention:</span>{inv.review_reasons.map((r) => <Badge key={r} tone="warn">{r}</Badge>)}</div>}
          <fieldset disabled={!editable || busy} className="card grid grid-cols-2 gap-3 p-4">
            <div className="col-span-2"><Field label="Vendor" flag={flag('vendor_name')} hint={hint('vendor_name')}><input className={cls('vendor_name')} value={form.vendor_name} onChange={set('vendor_name')} /></Field></div>
            <Field label="Invoice number" flag={flag('invoice_number')} hint={hint('invoice_number')}><input className={`${cls('invoice_number')} font-mono`} value={form.invoice_number} onChange={set('invoice_number')} placeholder="Missing" /></Field>
            <Field label="Currency" flag={flag('currency')} hint={hint('currency')}>
              <select className={cls('currency')} value={form.currency} onChange={set('currency')}><option value="">Unknown — select</option>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
            <Field label="Invoice date" flag={flag('invoice_date')} hint={hint('invoice_date') ?? (form.invoice_date ? formatDate(form.invoice_date) : undefined)}><input type="date" className={cls('invoice_date')} value={form.invoice_date} onChange={set('invoice_date')} /></Field>
            <Field label="Due date" flag={flag('due_date')} hint={hint('due_date')}><input type="date" className={cls('due_date')} value={form.due_date} onChange={set('due_date')} /></Field>
            {(['subtotal', 'tax_amount', 'discount_amount', 'total_amount'] as const).map((k) => (
              <Field key={k} label={k.replace('_amount', '').replace('_', ' ')} flag={flag(k)} hint={hint(k)}>
                <input inputMode="decimal" className={`${cls(k)} text-right font-mono ${k === 'total_amount' ? 'font-semibold' : ''}`} value={form[k]} onChange={set(k)} /></Field>
            ))}
            <Field label="Tax ID" hint={hint('tax_id')}><input className={`${cls('tax_id')} font-mono`} value={form.tax_id} onChange={set('tax_id')} /></Field>
            <Field label="Category"><input className={cls('category')} list="cats" value={form.category} onChange={set('category')} placeholder="e.g. Office supplies" /></Field>
            <datalist id="cats">{['Office supplies', 'Software', 'Travel', 'Utilities', 'Meals', 'Hardware'].map((c) => <option key={c} value={c} />)}</datalist>
          </fieldset>
          <LineItemsEditor items={items} onChange={setItems} readOnly={!editable} />
          {warnings.length > 0 && (
            <div className="card divide-y divide-paper-rule" aria-label="Validation warnings">
              {warnings.map((w, i) => <div key={i} className="flex items-start gap-2 px-3 py-2 text-sm"><Badge tone={w.severity === 'error' ? 'bad' : w.severity === 'warning' ? 'warn' : 'neutral'}>{w.severity}</Badge><span>{w.message}</span></div>)}
            </div>
          )}
          {editable && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <button className="btn-ghost" onClick={() => save()} disabled={busy}>Save corrections</button>
                <button className="btn-ghost" onClick={reprocess} disabled={busy}>Reprocess</button>
              </div>
              {can(org?.role, 'verify') ? (
                <div className="flex items-center gap-3">
                  {needsAck && !verified && <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />I have checked the warnings</label>}
                  <button className="btn-ok" onClick={verify} disabled={busy || verified}>{verified ? 'Verified ✓' : 'Verify & mark ready'}</button>
                </div>
              ) : <span className="text-xs text-ink-400">An accountant or admin must verify this invoice.</span>}
            </div>
          )}
          {(audit.data?.length ?? 0) > 0 && (
            <div className="card p-3">
              <h3 className="mb-2 text-sm font-semibold">History</h3>
              <ul className="space-y-1 text-xs text-ink-600">
                {audit.data!.slice(0, 8).map((a) => <li key={a.id}><span className="font-mono text-ink-400">{new Date(a.created_at).toLocaleString('en-GB')}</span> · {a.actor_name ?? 'System'} · {a.action.replace('invoice.', '')}{a.action === 'invoice.correct' && a.after_state ? ` (${Object.keys(a.after_state).join(', ')})` : ''}</li>)}
              </ul>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
