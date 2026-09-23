const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const TOKEN_KEY = 'hv_token'
const USER_KEY = 'hv_user'

// Credentials live in sessionStorage, which is scoped to a single tab/window.
// localStorage would be shared by every tab of the browser profile, so opening
// a second tab would silently inherit the first tab's identity, and logging out
// of either would end the one session row both were using.
// Per tab also means you can run the admin dashboard and an employee's drive
// side by side, which the demo walkthrough needs.

// One-time cleanup: drop tokens left behind by the old localStorage build.
try {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
} catch (e) {
  /* storage can be unavailable in private modes; nothing to clean up then */
}

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function getUser() {
  const raw = sessionStorage.getItem(USER_KEY)
  return raw ? JSON.parse(raw) : null
}

export function setAuth(token, user) {
  sessionStorage.setItem(TOKEN_KEY, token)
  sessionStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth() {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(USER_KEY)
}

async function request(path, { method = 'GET', body, raw = false } = {}) {
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (res.status === 401) {
    clearAuth()
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
    throw new Error('Session expired. Please log in again.')
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (data && data.detail) detail = data.detail
    } catch (e) {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }

  if (raw) return res
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  login: (username, password) =>
    request('/login', { method: 'POST', body: { username, password } }),
  logout: () => request('/logout', { method: 'POST' }),
  me: () => request('/me'),

  folders: () => request('/folders'),
  files: (folderId) => request(`/folders/${folderId}/files`),
  openFile: (fileId) => request(`/files/${fileId}/open`, { method: 'POST' }),
  downloadFile: (fileId) =>
    request(`/files/${fileId}/download`, { method: 'POST', raw: true }),
  search: (query) => request('/search', { method: 'POST', body: { query } }),

  summary: () => request('/admin/summary'),
  events: (limit = 50) => request(`/admin/events?limit=${limit}`),
  sessions: () => request('/admin/sessions'),
  sessionDetail: (id) => request(`/admin/sessions/${id}`),
  endSession: (id) => request(`/admin/sessions/${id}/end`, { method: 'POST' }),
  scoringRules: () => request('/admin/scoring-rules'),
}

// Triggers a browser download of the plain-text blob the backend returns.
export async function downloadToDisk(fileId, filename) {
  const res = await api.downloadFile(fileId)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
