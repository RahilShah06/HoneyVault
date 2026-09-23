import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setAuth } from '../api'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const res = await api.login(username, password)
      setAuth(res.token, { username: res.username, role: res.role, session_id: res.session_id })
      navigate(res.role === 'Admin' ? '/admin' : '/drive')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page" style={{ maxWidth: 360, marginTop: 60 }}>
      <div className="panel">
        <h2>Cloud HoneyVault - Sign in</h2>
        <form onSubmit={handleSubmit}>
          <p>
            <label htmlFor="username">Username</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
            />
          </p>
          <p>
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </p>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </div>
      <p className="muted">Demo credentials are listed in README.md.</p>
    </div>
  )
}
