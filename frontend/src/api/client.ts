export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number, public details: any = {}) { super(message) }
}

const BASE = '/api/v1'
const store = {
  get token() { return localStorage.getItem('token') },
  set token(v: string | null) { v ? localStorage.setItem('token', v) : localStorage.removeItem('token') },
  get orgId() { return localStorage.getItem('orgId') },
  set orgId(v: string | null) { v ? localStorage.setItem('orgId', v) : localStorage.removeItem('orgId') },
}
export const session = store

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const h: Record<string, string> = { ...extra }
  if (store.token) h.Authorization = `Bearer ${store.token}`
  if (store.orgId) h['X-Organization-Id'] = store.orgId
  return h
}

export function qs(params?: Record<string, any>): string {
  if (!params) return ''
  const u = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') u.set(k, String(v)) })
  const s = u.toString()
  return s ? `?${s}` : ''
}

export async function parseError(res: Response): Promise<ApiError> {
  try {
    const b = await res.json()
    if (b?.error) return new ApiError(b.error.code, b.error.message, res.status, b.error.details)
  } catch { /* not json */ }
  return new ApiError('HTTP_' + res.status, res.statusText || 'Request failed', res.status)
}

async function request<T>(method: string, path: string, opts: { json?: unknown; form?: FormData; params?: Record<string, any> } = {}): Promise<T> {
  const init: RequestInit = { method, headers: headers(opts.json !== undefined ? { 'Content-Type': 'application/json' } : {}) }
  if (opts.json !== undefined) init.body = JSON.stringify(opts.json)
  if (opts.form) init.body = opts.form
  const res = await fetch(BASE + path + qs(opts.params), init)
  if (res.status === 401 && store.token) { store.token = null; window.dispatchEvent(new Event('auth:expired')) }
  if (!res.ok) throw await parseError(res)
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  get: <T>(p: string, params?: Record<string, any>) => request<T>('GET', p, { params }),
  post: <T>(p: string, json?: unknown) => request<T>('POST', p, { json: json ?? {} }),
  patch: <T>(p: string, json: unknown) => request<T>('PATCH', p, { json }),
  del: (p: string) => request<void>('DELETE', p),
  form: <T>(p: string, form: FormData) => request<T>('POST', p, { form }),
  async blob(path: string): Promise<Blob> {
    const res = await fetch(path.startsWith('/api') ? path : BASE + path, { headers: headers() })
    if (!res.ok) throw await parseError(res)
    return res.blob()
  },
  /** Upload with progress (fetch cannot report upload progress). */
  upload(file: File, onProgress: (pct: number) => void): Promise<{ document_id: string; job_id: string }> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', BASE + '/documents')
      Object.entries(headers()).forEach(([k, v]) => xhr.setRequestHeader(k, v))
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100))
      xhr.onload = () => {
        try {
          const body = JSON.parse(xhr.responseText)
          if (xhr.status >= 200 && xhr.status < 300) resolve(body)
          else reject(new ApiError(body?.error?.code ?? 'UPLOAD_FAILED', body?.error?.message ?? 'Upload failed', xhr.status))
        } catch { reject(new ApiError('UPLOAD_FAILED', 'Upload failed', xhr.status)) }
      }
      xhr.onerror = () => reject(new ApiError('NETWORK', 'Network error during upload', 0))
      const fd = new FormData()
      fd.append('file', file)
      xhr.send(fd)
    })
  },
}

export async function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
