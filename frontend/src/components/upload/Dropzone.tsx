import { useRef, useState } from 'react'
import { api } from '../../api/client'
import { errorMessage } from '../../utils/format'

const OK = ['application/pdf', 'image/jpeg', 'image/png']
interface Item { name: string; pct: number; state: 'uploading' | 'done' | 'error'; error?: string }

export default function Dropzone({ maxMb, onUploaded }: { maxMb: number; onUploaded: () => void }) {
  const [items, setItems] = useState<Item[]>([])
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  async function handle(files: FileList | File[]) {
    const list = Array.from(files)
    const base = items.length
    setItems((p) => [...p, ...list.map((f) => ({ name: f.name, pct: 0, state: 'uploading' as const }))])
    const patch = (i: number, v: Partial<Item>) => setItems((p) => p.map((x, k) => (k === base + i ? { ...x, ...v } : x)))
    for (let i = 0; i < list.length; i++) {
      const f = list[i]
      if (f.name.toLowerCase().endsWith('.csv')) { patch(i, { state: 'error', error: 'Bank CSV files are imported on the Transactions page.' }); continue }
      if (!OK.includes(f.type) && !/\.(pdf|jpe?g|png)$/i.test(f.name)) { patch(i, { state: 'error', error: 'Only PDF, JPEG and PNG files are supported.' }); continue }
      if (f.size > maxMb * 1024 * 1024) { patch(i, { state: 'error', error: `Larger than the ${maxMb} MB limit.` }); continue }
      try { await api.upload(f, (pct) => patch(i, { pct })); patch(i, { pct: 100, state: 'done' }); onUploaded() }
      catch (e) { patch(i, { state: 'error', error: errorMessage(e) }) }
    }
  }
  return (
    <div className="mb-5">
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); handle(e.dataTransfer.files) }}
        onClick={() => input.current?.click()} role="button" tabIndex={0} aria-label="Upload documents"
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
        className={`cursor-pointer rounded-md border-2 border-dashed px-6 py-7 text-center transition-colors ${over ? 'border-info bg-info-soft' : 'border-ink-200 bg-white hover:bg-paper-tint'}`}>
        <p className="text-sm font-medium">Drop invoices or receipts here, or click to browse</p>
        <p className="mt-1 text-xs text-ink-400">PDF, JPEG or PNG · up to {maxMb} MB each · multiple files allowed</p>
        <input ref={input} type="file" multiple hidden accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
          onChange={(e) => { if (e.target.files) handle(e.target.files); e.target.value = '' }} />
      </div>
      {items.length > 0 && (
        <ul className="mt-2 space-y-1">
          {items.slice(-6).map((it, i) => (
            <li key={i} className="flex items-center gap-3 text-xs">
              <span className="w-56 truncate">{it.name}</span>
              {it.state === 'error' ? <span className="text-bad">{it.error}</span> : (
                <><div className="h-1.5 w-40 overflow-hidden rounded bg-paper-tint"><div className={`h-full ${it.state === 'done' ? 'bg-ok' : 'bg-info'}`} style={{ width: `${it.pct}%` }} /></div>
                  <span className="text-ink-400">{it.state === 'done' ? 'Uploaded — processing' : `${it.pct}%`}</span></>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
