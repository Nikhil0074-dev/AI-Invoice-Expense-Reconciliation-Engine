import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../utils/format'

/** Run an async loader on mount/deps change; supports optional polling and manual reload. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[], pollMs?: (data: T | null) => number | null) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const seq = useRef(0)
  const load = useCallback(async (silent = false) => {
    const my = ++seq.current
    if (!silent) setLoading(true)
    try { const d = await loader(); if (my === seq.current) { setData(d); setError(null) } return d }
    catch (e) { if (my === seq.current) setError(errorMessage(e)) }
    finally { if (my === seq.current) setLoading(false) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { load() }, [load])
  useEffect(() => {
    const ms = pollMs ? pollMs(data) : null
    if (!ms) return
    const t = setTimeout(() => load(true), ms)
    return () => clearTimeout(t)
  }, [data, pollMs, load])
  return { data, error, loading, reload: () => load(true), setData }
}
