const SYMBOLS: Record<string, string> = { INR: '₹', USD: '$', EUR: '€', GBP: '£', JPY: '¥' }

export function formatMoney(value: string | number | null | undefined, currency?: string | null): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return String(value)
  const digits = currency === 'JPY' ? 0 : 2
  const body = new Intl.NumberFormat(currency === 'INR' ? 'en-IN' : 'en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Math.abs(n))
  const sym = currency ? (SYMBOLS[currency] ?? currency + ' ') : ''
  return `${n < 0 ? '−' : ''}${sym}${body}`
}

export function formatDate(d: string | null | undefined): string {
  if (!d) return '—'
  const dt = new Date(d.length <= 10 ? d + 'T00:00:00' : d)
  return dt.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

export const STATUS_LABEL: Record<string, string> = {
  UPLOADED: 'Uploaded', QUEUED: 'Queued', PROCESSING: 'Processing', REVIEW_REQUIRED: 'Review required',
  READY_FOR_RECONCILIATION: 'Ready to reconcile', RECONCILED: 'Reconciled', FAILED: 'Failed',
  DUPLICATE_REVIEW: 'Duplicate review', ARCHIVED: 'Archived', UNMATCHED: 'Unmatched', SUGGESTED: 'Suggested',
  CONFIRMED: 'Confirmed', PARTIALLY_RECONCILED: 'Partial', REJECTED: 'Rejected', NEEDS_REVIEW: 'Needs review',
  VERIFIED: 'Verified', INFLOW: 'Inflow', OPEN: 'Open', DISMISSED: 'Dismissed', CONFIRMED_DUPLICATE: 'Confirmed duplicate',
}

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'neutral'
export function statusTone(s: string): Tone {
  if (['RECONCILED', 'CONFIRMED', 'VERIFIED', 'READY_FOR_RECONCILIATION'].includes(s)) return 'ok'
  if (['REVIEW_REQUIRED', 'DUPLICATE_REVIEW', 'NEEDS_REVIEW', 'PARTIALLY_RECONCILED', 'OPEN'].includes(s)) return 'warn'
  if (['FAILED', 'REJECTED', 'EXACT', 'CONFIRMED_DUPLICATE'].includes(s)) return 'bad'
  if (['QUEUED', 'PROCESSING', 'SUGGESTED', 'LIKELY'].includes(s)) return 'info'
  return 'neutral'
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong'
}

export const CURRENCIES = ['INR', 'USD', 'EUR', 'GBP', 'AUD', 'CAD', 'SGD', 'AED', 'JPY', 'CHF', 'CNY']

const PERMS: Record<string, string[]> = {
  ADMIN: ['*'],
  ACCOUNTANT: ['upload', 'process', 'edit', 'verify', 'import', 'reconcile', 'duplicates', 'export', 'delete', 'audit'],
  CONTRIBUTOR: ['upload', 'process', 'edit'],
  VIEWER: [],
}
export function can(role: string | null | undefined, perm: string): boolean {
  const p = PERMS[role ?? ''] ?? []
  return p.includes('*') || p.includes(perm)
}
