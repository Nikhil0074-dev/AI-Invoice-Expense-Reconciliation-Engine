import { describe, expect, it } from 'vitest'
import { qs, parseError } from '../api/client'
import { can, formatDate, formatMoney, statusTone } from '../utils/format'
import { invoiceFormSchema, toPayload } from '../utils/validation'

const valid = { vendor_name: 'ABC Office Supplies', invoice_number: 'INV-1', invoice_date: '2026-10-12', due_date: '', currency: 'INR',
  subtotal: '5000', tax_amount: '900', discount_amount: '100', total_amount: '5800', tax_id: '', category: '', description: '' }

describe('formatting', () => {
  it('formats money per currency and keeps the sign', () => {
    expect(formatMoney('5800', 'INR')).toBe('₹5,800.00')
    expect(formatMoney('-1234.5', 'USD')).toBe('−$1,234.50')
    expect(formatMoney('1190', 'EUR')).toBe('€1,190.00')
    expect(formatMoney('1000', 'JPY')).toBe('¥1,000')
    expect(formatMoney(null, 'INR')).toBe('—')
    expect(formatMoney('12', 'CHF')).toBe('CHF 12.00')
  })
  it('formats dates', () => { expect(formatDate('2026-10-12')).toBe('12 Oct 2026'); expect(formatDate(null)).toBe('—') })
  it('maps statuses to tones', () => {
    expect(statusTone('RECONCILED')).toBe('ok'); expect(statusTone('FAILED')).toBe('bad'); expect(statusTone('REVIEW_REQUIRED')).toBe('warn')
  })
  it('mirrors role permissions', () => {
    expect(can('ADMIN', 'anything')).toBe(true); expect(can('VIEWER', 'upload')).toBe(false)
    expect(can('CONTRIBUTOR', 'edit')).toBe(true); expect(can('CONTRIBUTOR', 'verify')).toBe(false); expect(can('ACCOUNTANT', 'export')).toBe(true)
  })
})

describe('api helpers', () => {
  it('builds query strings without empty values', () => { expect(qs({ a: 1, b: '', c: undefined, d: 'x y' })).toBe('?a=1&d=x+y'); expect(qs()).toBe('') })
  it('parses the backend error shape', async () => {
    const res = new Response(JSON.stringify({ error: { code: 'OVER_ALLOCATION', message: 'Too much', details: { a: 1 } } }), { status: 409 })
    const e = await parseError(res)
    expect(e.code).toBe('OVER_ALLOCATION'); expect(e.status).toBe(409); expect(e.message).toBe('Too much')
    expect((await parseError(new Response('oops', { status: 500 }))).code).toBe('HTTP_500')
  })
})

describe('invoice form validation', () => {
  it('accepts a valid form and converts blanks to null', () => {
    const p = invoiceFormSchema.parse(valid)
    expect(toPayload(p)).toMatchObject({ vendor_name: 'ABC Office Supplies', due_date: null, tax_id: null, total_amount: '5800' })
  })
  it.each([
    ['vendor_name', ''], ['invoice_date', ''], ['currency', ''], ['total_amount', ''], ['total_amount', '-5'], ['total_amount', '12,5'], ['subtotal', 'abc'], ['invoice_date', '2026-13-45'], ['invoice_date', '2026-02-31'], ['due_date', '2025-02-29'],
  ])('rejects %s = %j', (field, value) => {
    expect(invoiceFormSchema.safeParse({ ...valid, [field]: value }).success).toBe(false)
  })
})
