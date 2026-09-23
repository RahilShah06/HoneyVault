import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, clearAuth, getUser } from '../api'

const POLL_MS = 4000

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? iso : d.toLocaleTimeString()
}

function Level({ level }) {
  return <span className={`level-${level}`}>{level}</span>
}

function eventTarget(e) {
  if (e.filename) return `${e.folder_name || ''}/${e.filename}`
  if (e.search_query) return `"${e.search_query}"`
  return '-'
}

const DECEPTION_EVENT = 'ACTIVE_DECEPTION_TRIGGERED'

// The system responding, not the user acting - it gets its own row treatment
// in both the live feed and the per-session timeline.
function rowClass(e) {
  if (e.action_type === DECEPTION_EVENT) return 'deception'
  return e.is_honeyfile ? 'honey' : ''
}

function ActionCell({ event }) {
  if (event.action_type === DECEPTION_EVENT) {
    return <span className="deception-tag">ACTIVE DECEPTION TRIGGERED</span>
  }
  return (
    <>
      {event.action_type}
      {event.is_honeyfile ? ' [HONEYFILE]' : ''}
    </>
  )
}

export default function Admin() {
  const user = getUser()
  const navigate = useNavigate()

  const [summary, setSummary] = useState(null)
  const [events, setEvents] = useState([])
  const [sessions, setSessions] = useState([])
  const [detail, setDetail] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [error, setError] = useState('')
  const [paused, setPaused] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [s, e, ss] = await Promise.all([
        api.summary(),
        api.events(50),
        api.sessions(),
      ])
      setSummary(s)
      setEvents(e)
      setSessions(ss)
      setError('')
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    if (paused) return undefined
    const id = setInterval(() => {
      refresh()
      if (selectedId) {
        api.sessionDetail(selectedId).then(setDetail).catch(() => {})
      }
    }, POLL_MS)
    return () => clearInterval(id)
  }, [paused, refresh, selectedId])

  async function openSession(id) {
    setSelectedId(id)
    try {
      setDetail(await api.sessionDetail(id))
      requestAnimationFrame(() => {
        const el = document.getElementById('session-detail')
        if (el) el.scrollIntoView({ block: 'start' })
      })
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleEndSession(id) {
    setError('')
    try {
      await api.endSession(id)
      setDetail(await api.sessionDetail(id))
      refresh()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleLogout() {
    try {
      await api.logout()
    } catch (err) {
      /* ignore */
    }
    clearAuth()
    navigate('/login')
  }

  return (
    <div>
      <header className="bar">
        <h1>Cloud HoneyVault - Admin</h1>
        <a href="/drive">Drive</a>
        <span>{user ? `${user.username} (${user.role})` : ''}</span>
        <button onClick={() => setPaused((p) => !p)}>
          {paused ? 'Resume refresh' : 'Pause refresh'}
        </button>
        <button onClick={refresh}>Refresh now</button>
        <button onClick={handleLogout}>Log out</button>
      </header>

      <div className="page">
        {error && <p className="error">{error}</p>}

        <div className="row" style={{ marginBottom: 12 }}>
          <div className="tile">
            <div className="num">{summary ? summary.active_sessions : '-'}</div>
            <div className="label">Active sessions</div>
          </div>
          <div className="tile">
            <div className="num">{summary ? summary.suspicious_sessions : '-'}</div>
            <div className="label">Suspicious sessions (&gt;25)</div>
          </div>
          <div className="tile">
            <div className="num">
              {summary ? summary.total_honeyfile_interactions : '-'}
            </div>
            <div className="label">Honeyfile interactions</div>
          </div>
          <div className="tile">
            <div className="num">{summary ? summary.high_risk_users : '-'}</div>
            <div className="label">High-risk users (&gt;50)</div>
          </div>
        </div>

        <div className="row">
          <div className="col">
            <div className="panel">
              <h2>Sessions</h2>
              <div className="scroll-box">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>User</th>
                    <th>Role</th>
                    <th>Score</th>
                    <th>Level</th>
                    <th>Active</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr key={s.id}>
                      <td>{s.id}</td>
                      <td>{s.username}</td>
                      <td>{s.role}</td>
                      <td>{s.total_risk_score}</td>
                      <td>
                        <Level level={s.risk_level} />
                      </td>
                      <td>{s.is_active ? 'yes' : 'no'}</td>
                      <td>
                        <button onClick={() => openSession(s.id)}>View</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
              {sessions.length === 0 && <p className="muted">No sessions yet.</p>}
            </div>
          </div>

          <div className="col">
            <div className="panel">
              <h2>Recent events {paused ? '(paused)' : `(refreshing every ${POLL_MS / 1000}s)`}</h2>
              <div className="scroll-box">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>User</th>
                    <th>Action</th>
                    <th>Target</th>
                    <th>Pts</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.id} className={rowClass(e)}>
                      <td>{fmtTime(e.timestamp)}</td>
                      <td>{e.username || '-'}</td>
                      <td>
                        <ActionCell event={e} />
                      </td>
                      <td>{eventTarget(e)}</td>
                      <td>{e.points_awarded ? `+${e.points_awarded}` : '0'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
              {events.length === 0 && <p className="muted">No activity yet.</p>}
            </div>
          </div>
        </div>

        {detail && (
          <div className="panel" id="session-detail">
            <div
              className={
                ['HIGH', 'CRITICAL'].includes(detail.session.risk_level)
                  ? 'alert-card'
                  : 'alert-card level-ok'
              }
            >
              <h3>
                {['HIGH', 'CRITICAL'].includes(detail.session.risk_level)
                  ? 'SECURITY ALERT'
                  : 'SESSION DETAIL'}{' '}
                - session #{detail.session.id}
              </h3>
              <p>
                User: <strong>{detail.session.username}</strong> ({detail.session.role})
                <br />
                Risk score: <strong>{detail.session.total_risk_score}/100</strong> -{' '}
                <Level level={detail.session.risk_level} />
                <br />
                Honeyfile interactions: {detail.session.honeyfile_interactions} - actions:{' '}
                {detail.session.action_count}
                <br />
                Login: {fmtTime(detail.session.login_time)}
                {detail.session.logout_time
                  ? ` - logout: ${fmtTime(detail.session.logout_time)}`
                  : ' - still active'}
              </p>
              {detail.session.decoy_mode && (
                <p className="deception-banner">
                  ACTIVE DECEPTION ENGAGED - every file this session opens or
                  downloads is being served decoy content. The real files are
                  untouched.
                </p>
              )}
              <button onClick={() => { setDetail(null); setSelectedId(null) }}>Close</button>
              {detail.session.is_active && detail.session.id !== (user && user.session_id) && (
                <button onClick={() => handleEndSession(detail.session.id)}>
                  End session
                </button>
              )}
            </div>

            <h2 style={{ marginTop: 12 }}>Action timeline</h2>
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>Target</th>
                  <th>Pts</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {detail.timeline.map((e) => (
                  <tr key={e.id} className={rowClass(e)}>
                    <td>{fmtTime(e.timestamp)}</td>
                    <td>
                      <ActionCell event={e} />
                    </td>
                    <td>{eventTarget(e)}</td>
                    <td>{e.points_awarded ? `+${e.points_awarded}` : '0'}</td>
                    <td className="muted">{e.reason || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
