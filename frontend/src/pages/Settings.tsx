import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ErrorBanner, Field, Notice, PageHeader } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import type { AuditRow, Member, Org, Role } from '../types'
import { CURRENCIES, can, errorMessage } from '../utils/format'

const ROLES: Role[] = ['ADMIN', 'ACCOUNTANT', 'CONTRIBUTOR', 'VIEWER']

export default function Settings() {
  const { org, refreshOrgs, user } = useAuth()
  const admin = can(org?.role, 'settings')
  const [f, setF] = useState<Org | null>(org)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const members = useAsync(() => api.get<Member[]>(`/organizations/${org!.id}/members`), [org?.id])
  const audit = useAsync(() => (can(org?.role, 'audit') ? api.get<AuditRow[]>('/audit-logs', { limit: 15 }) : Promise.resolve([])), [org?.id])
  const [invite, setInvite] = useState({ email: '', role: 'CONTRIBUTOR' as Role })
  useEffect(() => setF(org), [org])
  if (!f || !org) return null
  const num = (k: keyof Org) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value === '' ? null : Number(e.target.value) } as Org)
  const txt = (k: keyof Org) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value } as Org)

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null)
    try { await fn(); setMsg({ tone: 'ok', text: ok }); await refreshOrgs(); members.reload() } catch (e) { setMsg({ tone: 'bad', text: errorMessage(e) }) }
  }
  const save = () => run(() => api.patch(`/organizations/${org.id}`, {
    name: f.name, default_currency: f.default_currency, locale: f.locale, date_format: f.date_format, max_upload_mb: f.max_upload_mb,
    match_high_threshold: f.match_high_threshold, match_review_threshold: f.match_review_threshold, amount_tolerance_pct: f.amount_tolerance_pct,
    date_window_days: f.date_window_days, retention_days: f.retention_days }), 'Settings saved.')

  return (
    <>
      <PageHeader title="Settings" subtitle={`${org.name} · your role: ${org.role?.toLowerCase()}`} />
      {msg && <Notice tone={msg.tone === 'ok' ? 'ok' : 'bad'}>{msg.text}</Notice>}
      <div className="grid gap-5 lg:grid-cols-2">
        <fieldset disabled={!admin} className="card space-y-3 p-4">
          <h3 className="text-sm font-semibold">Organization</h3>
          <Field label="Name"><input className="input" value={f.name} onChange={txt('name')} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Default currency"><select className="input" value={f.default_currency} onChange={txt('default_currency')}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
            <Field label="Locale"><input className="input" value={f.locale} onChange={txt('locale')} /></Field>
            <Field label="Date format" hint="Resolves ambiguous dates like 05/10/2026"><select className="input" value={f.date_format} onChange={txt('date_format')}><option value="DMY">Day/Month/Year</option><option value="MDY">Month/Day/Year</option><option value="ISO">ISO (Y-M-D)</option></select></Field>
            <Field label="Max upload (MB)"><input className="input" type="number" min={1} max={50} value={f.max_upload_mb} onChange={num('max_upload_mb')} /></Field>
          </div>
          <h3 className="pt-2 text-sm font-semibold">Matching thresholds</h3>
          <div className="grid grid-cols-2 gap-3">
            <Field label="High-confidence ≥" hint="Shown as a strong suggestion"><input className="input" type="number" step="0.05" min={0.5} max={1} value={f.match_high_threshold} onChange={num('match_high_threshold')} /></Field>
            <Field label="Manual review ≥" hint="Lower scores are not suggested"><input className="input" type="number" step="0.05" min={0.1} max={1} value={f.match_review_threshold} onChange={num('match_review_threshold')} /></Field>
            <Field label="Amount tolerance" hint="0.02 = 2%"><input className="input" type="number" step="0.01" min={0} max={0.2} value={f.amount_tolerance_pct} onChange={num('amount_tolerance_pct')} /></Field>
            <Field label="Date window (days)"><input className="input" type="number" min={1} max={365} value={f.date_window_days} onChange={num('date_window_days')} /></Field>
            <Field label="Data retention (days)" hint="Preference only; no automatic purge in this version"><input className="input" type="number" min={30} value={f.retention_days ?? ''} onChange={num('retention_days')} placeholder="Keep forever" /></Field>
          </div>
          {admin && <button type="button" className="btn-primary" onClick={save}>Save settings</button>}
        </fieldset>
        <div className="space-y-5">
          <div className="card p-4">
            <h3 className="mb-3 text-sm font-semibold">Team members</h3>
            <ErrorBanner message={members.error} />
            <table className="w-full"><tbody>
              {(members.data ?? []).map((m) => (
                <tr key={m.id}><td className="td"><div className="font-medium">{m.display_name}</div><div className="text-xs text-ink-400">{m.email}</div></td>
                  <td className="td"><select aria-label={`Role of ${m.email}`} className="input !w-36" disabled={!can(org.role, 'members')} value={m.role} onChange={(e) => run(() => api.patch(`/organizations/${org.id}/members/${m.id}`, { role: e.target.value }), 'Role updated.')}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></td>
                  <td className="td text-right">{can(org.role, 'members') && m.user_id !== user?.id && <button className="btn-danger !py-0.5" onClick={() => confirm(`Remove ${m.email}?`) && run(() => api.del(`/organizations/${org.id}/members/${m.id}`), 'Member removed.')}>Remove</button>}</td></tr>))}
            </tbody></table>
            {can(org.role, 'members') && (
              <div className="mt-3 flex gap-2"><input className="input" type="email" placeholder="Registered user's email" aria-label="Invite email" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
                <select className="input !w-36" aria-label="Invite role" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select>
                <button className="btn-primary" onClick={() => run(() => api.post(`/organizations/${org.id}/members`, invite), 'Member added.')}>Add</button></div>)}
            <ul className="mt-3 space-y-0.5 text-[11px] text-ink-400"><li><b>Admin</b> – everything incl. members & settings · <b>Accountant</b> – verify, reconcile, export</li><li><b>Contributor</b> – upload & correct, cannot verify · <b>Viewer</b> – read only</li></ul>
          </div>
          {(audit.data?.length ?? 0) > 0 && (
            <div className="card p-4"><h3 className="mb-2 text-sm font-semibold">Recent activity (audit log)</h3>
              <ul className="space-y-1 text-xs">{audit.data!.map((a) => <li key={a.id}><span className="font-mono text-ink-400">{new Date(a.created_at).toLocaleString('en-GB')}</span> · {a.actor_name ?? 'System'} · <span className="font-medium">{a.action}</span></li>)}</ul></div>)}
        </div>
      </div>
    </>
  )
}
