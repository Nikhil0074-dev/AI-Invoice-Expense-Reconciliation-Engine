import { useState, type FormEvent } from 'react'
import { ErrorBanner } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { errorMessage } from '../utils/format'

export default function Login() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [f, setF] = useState({ email: '', password: '', name: '', org: '' })
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value })

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null)
    try { mode === 'login' ? await login(f.email, f.password) : await register(f.email, f.password, f.name, f.org) }
    catch (x) { setErr(errorMessage(x)) } finally { setBusy(false) }
  }
  return (
    <div className="grid min-h-screen md:grid-cols-[1.1fr_1fr]">
      <div className="hidden bg-ink p-12 text-ink-200 md:flex md:flex-col md:justify-between">
        <div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded bg-white/10 font-mono text-[#29C4A3]">Rx</div><span className="text-lg font-semibold text-white">Reconcile</span></div>
        <div>
          <h2 className="max-w-md text-3xl font-semibold leading-tight text-white">Every invoice read, checked and matched — with a human in the loop.</h2>
          <ul className="mt-6 space-y-2 text-sm">
            <li>· OCR and native PDF extraction with per-field confidence</li>
            <li>· Explainable bank-transaction matching, split and partial payments</li>
            <li>· Duplicate detection that never deletes anything on its own</li>
            <li>· Audited corrections and validated accounting exports</li>
          </ul>
        </div>
        <p className="font-mono text-xs text-ink-300">extracted → suggested → confirmed → exported</p>
      </div>
      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-4">
          <h1 className="text-xl font-semibold">{mode === 'login' ? 'Sign in' : 'Create your workspace'}</h1>
          <ErrorBanner message={err} />
          {mode === 'register' && (<>
            <label className="block"><span className="label">Your name</span><input className="input" required value={f.name} onChange={set('name')} /></label>
            <label className="block"><span className="label">Organization</span><input className="input" value={f.org} onChange={set('org')} placeholder="Acme Ltd" /></label>
          </>)}
          <label className="block"><span className="label">Email</span><input className="input" type="email" required autoComplete="email" value={f.email} onChange={set('email')} /></label>
          <label className="block"><span className="label">Password</span><input className="input" type="password" required minLength={8} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={f.password} onChange={set('password')} /></label>
          <button className="btn-primary w-full" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}</button>
          <button type="button" className="w-full text-center text-sm text-info hover:underline" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setErr(null) }}>
            {mode === 'login' ? 'New here? Create an account' : 'Have an account? Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
