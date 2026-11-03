import type { ReactNode } from 'react'
import { STATUS_LABEL, statusTone, type Tone } from '../../utils/format'

const TONES: Record<Tone, string> = {
  ok: 'bg-ok-soft text-ok border-ok/20', warn: 'bg-warn-soft text-warn border-warn/20', bad: 'bg-bad-soft text-bad border-bad/20',
  info: 'bg-info-soft text-info border-info/20', neutral: 'bg-paper-tint text-ink-600 border-paper-rule',
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium ${TONES[tone]}`}>{children}</span>
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{STATUS_LABEL[status] ?? status}</Badge>
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3 rule-title pb-3">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-ink-400">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  )
}

export function ErrorBanner({ message, onClose }: { message: string | null; onClose?: () => void }) {
  if (!message) return null
  return (
    <div role="alert" className="mb-4 flex items-start justify-between gap-3 rounded border border-bad/30 bg-bad-soft px-3 py-2 text-sm text-bad">
      <span>{message}</span>
      {onClose && <button onClick={onClose} className="text-bad/70 hover:text-bad" aria-label="Dismiss">✕</button>}
    </div>
  )
}

export function Notice({ tone = 'info', children }: { tone?: Tone; children: ReactNode }) {
  return <div className={`mb-4 rounded border px-3 py-2 text-sm ${TONES[tone]}`}>{children}</div>
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-10 text-center text-sm text-ink-400">{children}</div>
}

export function Spinner() {
  return <div className="px-4 py-10 text-center text-sm text-ink-400" role="status">Loading…</div>
}

export function Field({ label, hint, flag, children }: { label: string; hint?: string; flag?: 'uncertain' | 'error'; children: ReactNode }) {
  return (
    <label className="block">
      <span className="label flex items-center gap-1.5">{label}
        {flag === 'uncertain' && <span className="rounded bg-warn-soft px-1 text-[10px] normal-case tracking-normal text-warn">verify</span>}
      </span>
      {children}
      {hint && <span className={`mt-1 block text-xs ${flag === 'error' ? 'text-bad' : 'text-ink-400'}`}>{hint}</span>}
    </label>
  )
}

export function Pagination({ page, total, size, onPage }: { page: number; total: number; size: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size))
  return (
    <div className="flex items-center justify-between border-t border-paper-rule px-3 py-2 text-xs text-ink-400">
      <span>{total} record{total === 1 ? '' : 's'}</span>
      <div className="flex items-center gap-2">
        <button className="btn-ghost !py-0.5" disabled={page <= 1} onClick={() => onPage(page - 1)}>Prev</button>
        <span>Page {page} of {pages}</span>
        <button className="btn-ghost !py-0.5" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </div>
  )
}

export function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = score >= 0.8 ? 'bg-ok' : score >= 0.55 ? 'bg-warn' : 'bg-bad'
  return (
    <div className="flex items-center gap-2" title={`Match score ${pct}%`}>
      <div className="h-1.5 w-20 overflow-hidden rounded bg-paper-tint"><div className={`h-full ${color}`} style={{ width: `${pct}%` }} /></div>
      <span className="font-mono text-xs tabular-nums">{pct}%</span>
    </div>
  )
}
