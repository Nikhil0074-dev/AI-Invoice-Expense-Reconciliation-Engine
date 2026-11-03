import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { can } from '../../utils/format'

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/documents', label: 'Documents' },
  { to: '/review', label: 'Review queue' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/reconciliation', label: 'Reconciliation' },
  { to: '/duplicates', label: 'Duplicates' },
  { to: '/exports', label: 'Exports' },
  { to: '/settings', label: 'Settings' },
]

export default function Layout() {
  const { user, org, orgs, switchOrg, logout } = useAuth()
  return (
    <div className="min-h-screen md:flex">
      <aside className="bg-ink text-ink-200 md:fixed md:inset-y-0 md:w-56 md:flex md:flex-col">
        <div className="flex items-center gap-2.5 px-4 py-4 border-b border-white/10">
          <div className="grid h-8 w-8 place-items-center rounded bg-white/10 font-mono text-sm font-medium text-[#29C4A3]">Rx</div>
          <div className="leading-tight"><div className="text-sm font-semibold text-white">Reconcile</div><div className="text-[11px] text-ink-300">Invoice & expense engine</div></div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 py-3 md:flex-1 md:flex-col md:overflow-visible">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) => `whitespace-nowrap rounded px-3 py-1.5 text-sm ${isActive ? 'bg-white/10 text-white' : 'hover:bg-white/5 hover:text-white'}`}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden border-t border-white/10 px-3 py-3 text-xs md:block">
          {orgs.length > 1 ? (
            <select aria-label="Organization" className="mb-2 w-full rounded border border-white/10 bg-ink-700 px-2 py-1 text-white" value={org?.id} onChange={(e) => switchOrg(e.target.value)}>
              {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          ) : <div className="mb-1 truncate font-medium text-white">{org?.name}</div>}
          <div className="truncate text-ink-300">{user?.display_name} · {org?.role?.toLowerCase()}</div>
          <button onClick={logout} className="mt-2 text-ink-300 underline hover:text-white">Sign out</button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:ml-56 md:px-8">
        <Outlet />
      </main>
    </div>
  )
}
export { can }
