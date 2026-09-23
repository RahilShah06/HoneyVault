import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login'
import Drive from './pages/Drive'
import Admin from './pages/Admin'
import { api, getToken, getUser } from './api'

// A stored token is only a claim. Confirm it against the server before showing
// anything protected, so an expired token or a session ended elsewhere cannot
// render the authenticated UI.
function RequireAuth({ children, adminOnly = false }) {
  const [status, setStatus] = useState('checking')
  const user = getUser()

  useEffect(() => {
    let cancelled = false
    if (!getToken()) {
      setStatus('fail')
      return undefined
    }
    api
      .me()
      .then(() => !cancelled && setStatus('ok'))
      .catch(() => !cancelled && setStatus('fail'))
    return () => {
      cancelled = true
    }
  }, [])

  if (status === 'checking') {
    return <p style={{ padding: 16 }}>Checking session...</p>
  }
  if (status === 'fail') return <Navigate to="/login" replace />
  if (adminOnly && (!user || user.role !== 'Admin')) {
    return <Navigate to="/drive" replace />
  }
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/drive"
        element={
          <RequireAuth>
            <Drive />
          </RequireAuth>
        }
      />
      <Route
        path="/admin"
        element={
          <RequireAuth adminOnly>
            <Admin />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to={getToken() ? '/drive' : '/login'} replace />} />
    </Routes>
  )
}
