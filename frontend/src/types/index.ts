export interface Org {
  id: string; name: string; default_currency: string; locale: string; date_format: 'DMY' | 'MDY' | 'ISO'
  max_upload_mb: number; match_high_threshold: number; match_review_threshold: number
  amount_tolerance_pct: number; date_window_days: number; retention_days: number | null; role: Role | null
}
export type Role = 'ADMIN' | 'ACCOUNTANT' | 'CONTRIBUTOR' | 'VIEWER'
export interface User { id: string; email: string; display_name: string }
export interface DocumentRow {
  id: string; original_filename: string; mime_type: string; processing_status: string; created_at: string
  extraction_method: string | null; ocr_confidence: number | null; language: string | null
  invoice_id: string | null; vendor_name: string | null; invoice_number: string | null; currency: string | null
  total_amount: string | null; invoice_date: string | null; open_duplicate_flags: number
}
export interface Warning { code: string; field: string; message: string; severity: 'error' | 'warning' | 'info' }
export interface LineItem { id?: string; description: string | null; quantity: string | null; unit_price: string | null; tax_amount: string | null; line_total: string | null }
export interface Invoice {
  id: string; document_id: string; vendor_name: string | null; invoice_number: string | null
  invoice_date: string | null; due_date: string | null; currency: string | null
  subtotal: string | null; tax_amount: string | null; discount_amount: string | null; total_amount: string | null
  tax_id: string | null; description: string | null; category: string | null; payment_status: string
  review_status: 'REVIEW_REQUIRED' | 'VERIFIED'; reconciliation_status: string
  field_confidence: Record<string, number> | null; uncertain_fields: string[] | null; warnings: Warning[] | null
  extraction_original: Record<string, any> | null; line_items: LineItem[]; review_reasons: string[]
  updated_at: string; document_status: string | null; original_filename: string | null; mime_type: string | null; allocated_amount: string | null
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface Transaction {
  id: string; transaction_date: string; description: string; amount: string; currency: string
  reference: string | null; allocated: string; remaining: string; status: string
}
export interface Match {
  id: string; invoice_id: string; kind: string; match_status: string; match_score: number | null
  match_explanation: string; signals: Record<string, any> | null; transactions: Transaction[]
}
export interface DuplicateFlag {
  id: string; document_id: string; possible_duplicate_document_id: string; detection_method: string; category: string
  confidence_score: number; evidence: string; review_status: string; document_filename: string | null; possible_duplicate_filename: string | null; created_at: string
}
export interface ExportRec { id: string; export_type: string; row_count: number; created_at: string; download_url: string; content_sha256: string }
export interface Member { id: string; user_id: string; email: string; display_name: string; role: Role }
export interface AuditRow { id: string; actor_name: string | null; entity_type: string; action: string; created_at: string; before_state: any; after_state: any }
export interface Dashboard {
  currency: string
  cards: { total_invoices: number; total_expenses: string; other_currency_expenses: Record<string, string>; awaiting_review: number
    reconciled_expenses: string; unmatched_transactions: number; potential_duplicates: number; ocr_failures: number }
  monthly_expenses: { month: string; total: number }[]
  spend_by_vendor: { vendor: string; total: number }[]
  spend_by_category: { category: string; total: number }[]
  reconciliation_split: { name: string; total: number }[]
  processing_trend: { month: string; uploaded: number; failed: number; needs_review: number }[]
}
