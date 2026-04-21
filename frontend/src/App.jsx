import React, { useEffect, useState } from 'react'
import Home from './pages/Home.jsx'
import Setup from './pages/Setup.jsx'
import { api } from './api.js'

export default function App() {
  const [page, setPage] = useState(() => (window.location.hash === '#/setup' ? 'setup' : 'home'))
  const [health, setHealth] = useState(null)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    const onHash = () => setPage(window.location.hash === '#/setup' ? 'setup' : 'home')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  const goto = (p) => {
    window.location.hash = p === 'setup' ? '#/setup' : '#/'
  }

  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(null), 1800)
  }

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          RustDesk Address Companion
          <small>{health?.rustdesk_db_detected ? 'RustDesk DB detected' : 'No RustDesk DB mounted'}</small>
        </div>
        <nav>
          <button className={`nav-btn ${page === 'home' ? 'active' : ''}`} onClick={() => goto('home')}>Home</button>
          <button className={`nav-btn ${page === 'setup' ? 'active' : ''}`} onClick={() => goto('setup')}>Setup</button>
        </nav>
      </div>

      {page === 'home' && <Home onToast={showToast} launchEnabled={!!health?.launch_rustdesk_enabled} />}
      {page === 'setup' && <Setup onToast={showToast} />}

      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
