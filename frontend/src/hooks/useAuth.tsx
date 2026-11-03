import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, session } from '../api/client'
import type { Org, User } from '../types'

interface AuthState {
  user: User | null; orgs: Org[]; org: Org | null; loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string, org: string) => Promise<void>
  logout: () => void; switchOrg: (id: string) => void; refreshOrgs: () => Promise<void>
}
const Ctx = createContext<AuthState>(null as unknown as AuthState)
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [orgs, setOrgs] = useState<Org[]>([])
  const [orgId, setOrgId] = useState<string | null>(session.orgId)
  const [loading, setLoading] = useState(!!session.token)

  const refreshOrgs = useCallback(async () => {
    const list = await api.get<Org[]>('/organizations')
    setOrgs(list)
    const chosen = list.find((o) => o.id === session.orgId) ?? list[0]
    if (chosen) { session.orgId = chosen.id; setOrgId(chosen.id) }
  }, [])

  const bootstrap = useCallback(async () => {
    setLoading(true)
    try { setUser(await api.get<User>('/auth/me')); await refreshOrgs() } catch { session.token = null; setUser(null) } finally { setLoading(false) }
  }, [refreshOrgs])

  useEffect(() => { if (session.token) bootstrap() }, [bootstrap])
  useEffect(() => {
    const h = () => { setUser(null); setOrgs([]) }
    window.addEventListener('auth:expired', h)
    return () => window.removeEventListener('auth:expired', h)
  }, [])

  const value = useMemo<AuthState>(() => ({
    user, orgs, org: orgs.find((o) => o.id === orgId) ?? null, loading,
    async login(email, password) { const t = await api.post<{ access_token: string }>('/auth/login', { email, password }); session.token = t.access_token; await bootstrap() },
    async register(email, password, name, organization) {
      const t = await api.post<{ access_token: string }>('/auth/register', { email, password, display_name: name, organization_name: organization || null })
      session.token = t.access_token; session.orgId = null; await bootstrap()
    },
    logout() { session.token = null; session.orgId = null; setUser(null); setOrgs([]) },
    switchOrg(id) { session.orgId = id; setOrgId(id) },
    refreshOrgs,
  }), [user, orgs, orgId, loading, bootstrap, refreshOrgs])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
