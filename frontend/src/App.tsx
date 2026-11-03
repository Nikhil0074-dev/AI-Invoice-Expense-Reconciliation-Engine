import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/ui/Layout'
import { Spinner } from './components/ui'
import { useAuth } from './hooks/useAuth'
import Documents from './pages/Documents'
import DuplicatesPage from './pages/Duplicates'
import ExportsPage from './pages/Exports'
import Login from './pages/Login'
import ReviewQueue from './pages/ReviewQueue'
import Settings from './pages/Settings'
import Transactions from './pages/Transactions'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const InvoiceReview = lazy(() => import('./pages/InvoiceReview'))
const Reconciliation = lazy(() => import('./pages/Reconciliation'))

export default function App() {
  const { user, loading, org } = useAuth()
  if (loading) return <Spinner />
  if (!user) return <Login />
  if (!org) return <Spinner />
  return (
    // key forces every page to reload its data when the organization changes
    <Suspense fallback={<Spinner />}>
    <Routes key={org.id}>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="documents" element={<Documents />} />
        <Route path="review" element={<ReviewQueue />} />
        <Route path="invoices/:id" element={<InvoiceReview />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="reconciliation" element={<Reconciliation />} />
        <Route path="duplicates" element={<DuplicatesPage />} />
        <Route path="exports" element={<ExportsPage />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
    </Suspense>
  )
}
