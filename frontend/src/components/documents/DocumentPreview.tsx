import { useEffect, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api } from '../../api/client'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

/** Authenticated preview: fetches the file with the bearer token (never a public URL) and renders PDFs with PDF.js. */
export default function DocumentPreview({ documentId, mime, height = 640 }: { documentId: string; mime: string | null; height?: number }) {
  const holder = useRef<HTMLDivElement>(null)
  const [img, setImg] = useState<string | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [pages, setPages] = useState(0)

  useEffect(() => {
    let dead = false, url: string | null = null
    setState('loading'); setImg(null)
    ;(async () => {
      try {
        const blob = await api.blob(`/documents/${documentId}/preview`)
        if (dead) return
        if (mime === 'application/pdf') {
          const pdf = await pdfjs.getDocument({ data: await blob.arrayBuffer() }).promise
          if (dead || !holder.current) return
          holder.current.innerHTML = ''
          setPages(pdf.numPages)
          const width = holder.current.clientWidth - 16
          for (let n = 1; n <= pdf.numPages; n++) {
            const page = await pdf.getPage(n)
            const base = page.getViewport({ scale: 1 })
            const vp = page.getViewport({ scale: Math.max(0.5, width / base.width) * 1.5 })
            const canvas = document.createElement('canvas')
            canvas.width = vp.width; canvas.height = vp.height
            canvas.style.width = '100%'; canvas.className = 'mb-2 border border-paper-rule bg-white'
            holder.current.appendChild(canvas)
            await page.render({ canvasContext: canvas.getContext('2d')!, viewport: vp }).promise
          }
        } else { url = URL.createObjectURL(blob); setImg(url) }
        if (!dead) setState('ready')
      } catch { if (!dead) setState('error') }
    })()
    return () => { dead = true; if (url) URL.revokeObjectURL(url) }
  }, [documentId, mime])

  return (
    <div className="card overflow-auto bg-paper-tint p-2" style={{ height }} aria-label="Document preview">
      {state === 'loading' && <p className="p-6 text-center text-sm text-ink-400">Loading preview…</p>}
      {state === 'error' && <p className="p-6 text-center text-sm text-bad">The preview could not be loaded.</p>}
      {img && <img src={img} alt="Uploaded document" className="mx-auto max-w-full border border-paper-rule bg-white" />}
      <div ref={holder} data-pages={pages} />
    </div>
  )
}
