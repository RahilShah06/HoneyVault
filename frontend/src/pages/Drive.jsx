import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, clearAuth, downloadToDisk, getUser } from '../api'

// Nothing on this page reveals honeyfiles or risk scores - that is the point.
export default function Drive() {
  const user = getUser()
  const navigate = useNavigate()

  const [folders, setFolders] = useState([])
  const [activeFolder, setActiveFolder] = useState(null)
  const [files, setFiles] = useState([])
  const [viewing, setViewing] = useState(null)
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .folders()
      .then((data) => {
        setFolders(data)
        if (data.length) selectFolder(data[0])
      })
      .catch((e) => setError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function selectFolder(folder) {
    setError('')
    setSearchResults(null)
    setActiveFolder(folder)
    try {
      setFiles(await api.files(folder.id))
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleOpen(file) {
    setError('')
    try {
      setViewing(await api.openFile(file.id))
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleDownload(file) {
    setError('')
    try {
      await downloadToDisk(file.id, file.filename)
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleSearch(e) {
    e.preventDefault()
    setError('')
    try {
      const res = await api.search(query)
      setSearchResults(res.results)
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleLogout() {
    try {
      await api.logout()
    } catch (e) {
      /* token may already be invalid; clear it either way */
    }
    clearAuth()
    navigate('/login')
  }

  const listed = searchResults !== null ? searchResults : files

  return (
    <div>
      <header className="bar">
        <h1>Cloud HoneyVault</h1>
        {user && user.role === 'Admin' && <a href="/admin">Admin dashboard</a>}
        <span>
          {user ? `${user.username} (${user.role})` : ''}
        </span>
        <button onClick={handleLogout}>Log out</button>
      </header>

      <div className="page">
        <div className="panel">
          <form onSubmit={handleSearch} className="row">
            <div className="col">
              <input
                type="text"
                placeholder="Search files by name..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div>
              <button type="submit">Search</button>
              {searchResults !== null && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchResults(null)
                    setQuery('')
                  }}
                >
                  Clear
                </button>
              )}
            </div>
          </form>
        </div>

        {error && <p className="error">{error}</p>}

        <div className="row">
          <div className="col" style={{ maxWidth: 200 }}>
            <div className="panel">
              <h2>Folders</h2>
              <ul className="plain">
                {folders.map((f) => (
                  <li key={f.id}>
                    <button
                      onClick={() => selectFolder(f)}
                      style={{
                        fontWeight:
                          activeFolder && activeFolder.id === f.id ? 'bold' : 'normal',
                      }}
                    >
                      {f.name} ({f.file_count})
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="col col-wide">
            <div className="panel">
              <h2>
                {searchResults !== null
                  ? `Search results (${listed.length})`
                  : activeFolder
                    ? activeFolder.name
                    : 'Files'}
              </h2>
              {listed.length === 0 ? (
                <p className="muted">No files.</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Folder</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {listed.map((f) => (
                      <tr key={f.id}>
                        <td>{f.filename}</td>
                        <td>{f.extension.toUpperCase()}</td>
                        <td>{f.folder_name}</td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <button onClick={() => handleOpen(f)}>Open</button>
                          <button onClick={() => handleDownload(f)}>Download</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="col">
            <div className="panel">
              <h2>Viewer</h2>
              {viewing ? (
                <div>
                  <p className="muted">
                    {viewing.folder_name} / <strong>{viewing.filename}</strong>
                  </p>
                  <pre className="viewer">{viewing.content}</pre>
                </div>
              ) : (
                <p className="muted">Open a file to preview its contents.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
