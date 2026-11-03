import type { LineItem } from '../../types'

const COLS: { key: keyof LineItem; label: string; num?: boolean }[] = [
  { key: 'description', label: 'Description' }, { key: 'quantity', label: 'Qty', num: true },
  { key: 'unit_price', label: 'Unit price', num: true }, { key: 'tax_amount', label: 'Tax', num: true }, { key: 'line_total', label: 'Line total', num: true },
]

export default function LineItemsEditor({ items, onChange, readOnly }: { items: LineItem[]; onChange: (i: LineItem[]) => void; readOnly?: boolean }) {
  const set = (i: number, k: keyof LineItem, v: string) => onChange(items.map((it, n) => (n === i ? { ...it, [k]: v === '' ? null : v } : it)))
  return (
    <div className="card overflow-x-auto">
      <div className="flex items-center justify-between px-3 py-2">
        <h3 className="text-sm font-semibold">Line items <span className="font-normal text-ink-400">({items.length})</span></h3>
        {!readOnly && <button className="btn-ghost !py-0.5" onClick={() => onChange([...items, { description: '', quantity: null, unit_price: null, tax_amount: null, line_total: null }])}>+ Add line</button>}
      </div>
      {items.length === 0 ? <p className="px-3 pb-3 text-xs text-ink-400">No line items were extracted. They are optional — many receipts cannot be split reliably.</p> : (
        <table className="w-full">
          <thead><tr>{COLS.map((c) => <th key={c.key} className={`th ${c.num ? 'text-right' : ''}`}>{c.label}</th>)}<th className="th" /></tr></thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i}>
                {COLS.map((c) => (
                  <td key={c.key} className="border-b border-paper-rule px-1.5 py-1">
                    <input aria-label={`${c.label} line ${i + 1}`} className={`input !py-1 ${c.num ? 'text-right font-mono' : ''}`} disabled={readOnly}
                      inputMode={c.num ? 'decimal' : undefined} value={(it[c.key] as string | null) ?? ''} onChange={(e) => set(i, c.key, e.target.value)} />
                  </td>
                ))}
                <td className="border-b border-paper-rule px-1.5">{!readOnly && <button aria-label={`Delete line ${i + 1}`} className="text-bad" onClick={() => onChange(items.filter((_, n) => n !== i))}>✕</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
