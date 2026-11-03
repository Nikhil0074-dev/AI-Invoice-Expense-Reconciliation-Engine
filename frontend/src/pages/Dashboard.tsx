import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { ErrorBanner, PageHeader, Spinner } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import type { Dashboard as D } from '../types'
import { formatMoney } from '../utils/format'

const C = { ink: '#1B2A41', ok: '#0E7C66', warn: '#C98A1B', bad: '#B42318', info: '#2457C5', mute: '#C9D3E3' }
const PIE = [C.ok, C.warn, C.mute]

function Card({ label, value, tone, to, sub }: { label: string; value: string | number; tone?: string; to?: string; sub?: string }) {
  const body = (
    <div className="card h-full px-4 py-3 transition-colors hover:border-ink-300">
      <div className="label !mb-1.5">{label}</div>
      <div className={`font-mono text-2xl font-medium tabular-nums ${tone ?? ''}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-ink-400">{sub}</div>}
    </div>
  )
  return to ? <Link to={to}>{body}</Link> : body
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="card p-4"><h3 className="mb-3 text-sm font-semibold">{title}</h3><div className="h-60">{children}</div></div>
}

export default function Dashboard() {
  const [range, setRange] = useState({ date_from: '', date_to: '' })
  const { data, error, loading } = useAsync(() => api.get<D>('/dashboard', range), [range])
  if (loading && !data) return <Spinner />
  if (!data) return <ErrorBanner message={error} />
  const c = data.cards, cur = data.currency
  const money = (v: number) => formatMoney(v, cur)
  const others = Object.entries(c.other_currency_expenses)
  const empty = <p className="grid h-full place-items-center text-sm text-ink-400">No verified invoices in this range yet.</p>
  return (
    <>
      <PageHeader title="Dashboard" subtitle={`Figures cover verified invoices in ${cur}; other currencies are never silently converted.`}
        actions={<><input aria-label="From" type="date" className="input !w-36" value={range.date_from} onChange={(e) => setRange({ ...range, date_from: e.target.value })} />
          <input aria-label="To" type="date" className="input !w-36" value={range.date_to} onChange={(e) => setRange({ ...range, date_to: e.target.value })} /></>} />
      <ErrorBanner message={error} />
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Card label="Invoices uploaded" value={c.total_invoices} to="/documents" />
        <Card label="Expenses processed" value={formatMoney(c.total_expenses, cur)} sub={others.length ? `+ ${others.map(([k, v]) => formatMoney(v, k)).join(', ')}` : 'verified invoices'} />
        <Card label="Awaiting review" value={c.awaiting_review} tone={c.awaiting_review ? 'text-warn' : ''} to="/review" />
        <Card label="Reconciled expenses" value={formatMoney(c.reconciled_expenses, cur)} tone="text-ok" to="/reconciliation" />
        <Card label="Unmatched transactions" value={c.unmatched_transactions} to="/transactions" />
        <Card label="Potential duplicates" value={c.potential_duplicates} tone={c.potential_duplicates ? 'text-warn' : ''} to="/duplicates" />
        <Card label="OCR failures" value={c.ocr_failures} tone={c.ocr_failures ? 'text-bad' : ''} to="/documents" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Monthly expenses">{data.monthly_expenses.length ? <ResponsiveContainer><BarChart data={data.monthly_expenses}><CartesianGrid stroke="#E2E6EC" vertical={false} /><XAxis dataKey="month" fontSize={11} /><YAxis fontSize={11} tickFormatter={(v) => Intl.NumberFormat('en', { notation: 'compact' }).format(v)} /><Tooltip formatter={(v: number) => money(v)} /><Bar dataKey="total" fill={C.ink} radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer> : empty}</Panel>
        <Panel title="Reconciled vs unreconciled">{data.reconciliation_split.some((s) => s.total) ? <ResponsiveContainer><PieChart><Pie data={data.reconciliation_split} dataKey="total" nameKey="name" innerRadius={50} outerRadius={80} paddingAngle={2}>{data.reconciliation_split.map((_, i) => <Cell key={i} fill={PIE[i]} />)}</Pie><Tooltip formatter={(v: number) => money(v)} /><Legend iconType="square" wrapperStyle={{ fontSize: 12 }} /></PieChart></ResponsiveContainer> : empty}</Panel>
        <Panel title="Spending by vendor">{data.spend_by_vendor.length ? <ResponsiveContainer><BarChart data={data.spend_by_vendor} layout="vertical" margin={{ left: 40 }}><CartesianGrid stroke="#E2E6EC" horizontal={false} /><XAxis type="number" fontSize={11} tickFormatter={(v) => Intl.NumberFormat('en', { notation: 'compact' }).format(v)} /><YAxis type="category" dataKey="vendor" fontSize={11} width={110} /><Tooltip formatter={(v: number) => money(v)} /><Bar dataKey="total" fill={C.info} radius={[0, 3, 3, 0]} /></BarChart></ResponsiveContainer> : empty}</Panel>
        <Panel title="Spending by category">{data.spend_by_category.length ? <ResponsiveContainer><BarChart data={data.spend_by_category}><CartesianGrid stroke="#E2E6EC" vertical={false} /><XAxis dataKey="category" fontSize={11} /><YAxis fontSize={11} tickFormatter={(v) => Intl.NumberFormat('en', { notation: 'compact' }).format(v)} /><Tooltip formatter={(v: number) => money(v)} /><Bar dataKey="total" fill={C.ok} radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer> : empty}</Panel>
        <div className="lg:col-span-2"><Panel title="Processing and review trend">{data.processing_trend.length ? <ResponsiveContainer><BarChart data={data.processing_trend}><CartesianGrid stroke="#E2E6EC" vertical={false} /><XAxis dataKey="month" fontSize={11} /><YAxis allowDecimals={false} fontSize={11} /><Tooltip /><Legend wrapperStyle={{ fontSize: 12 }} /><Bar dataKey="uploaded" fill={C.ink} /><Bar dataKey="needs_review" name="needs review" fill={C.warn} /><Bar dataKey="failed" fill={C.bad} /></BarChart></ResponsiveContainer> : empty}</Panel></div>
      </div>
    </>
  )
}
