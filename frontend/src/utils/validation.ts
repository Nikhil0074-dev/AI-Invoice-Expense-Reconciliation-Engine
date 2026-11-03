import { z } from 'zod'

const money = z.string().trim().refine((v) => v === '' || /^\d{1,12}(\.\d{1,4})?$/.test(v), 'Enter a positive amount such as 1250.00')
function isValidDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const parsed = new Date(Date.UTC(year, month - 1, day))
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day
}
const optDate = z.string().refine((v) => v === '' || isValidDate(v), 'Use a valid date')

export const invoiceFormSchema = z.object({
  vendor_name: z.string().trim().min(1, 'Vendor is required').max(255),
  invoice_number: z.string().trim().max(100),
  invoice_date: optDate.refine((v) => v !== '', 'Invoice date is required'),
  due_date: optDate,
  currency: z.string().regex(/^[A-Z]{3}$/, 'Select a currency'),
  subtotal: money, tax_amount: money, discount_amount: money,
  total_amount: money.refine((v) => v !== '', 'Total is required'),
  tax_id: z.string().max(50), category: z.string().max(80), description: z.string().max(500),
})
export type InvoiceForm = z.infer<typeof invoiceFormSchema>

/** Convert form strings to the PATCH payload (empty string -> null). */
export function toPayload(f: InvoiceForm) {
  const n = (v: string) => (v.trim() === '' ? null : v.trim())
  return {
    vendor_name: f.vendor_name.trim(), invoice_number: n(f.invoice_number), invoice_date: n(f.invoice_date), due_date: n(f.due_date),
    currency: f.currency, subtotal: n(f.subtotal), tax_amount: n(f.tax_amount), discount_amount: n(f.discount_amount),
    total_amount: n(f.total_amount), tax_id: n(f.tax_id), category: n(f.category), description: n(f.description),
  }
}
