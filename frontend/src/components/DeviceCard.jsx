import React from 'react'
import CopyButton from './CopyButton.jsx'

// RustDesk's Windows client registers this URL scheme. Clicking such a link
// opens the local RustDesk app and initiates a new connection to the given ID.
// Verified working on Windows; harmless no-op on hosts without the handler.
export function rustdeskConnectUrl(id) {
  return id ? `rustdesk://connection/new/${id}` : null
}

function formatLastSeen(iso) {
  if (!iso) return '—'
  try {
    // Treat naive ISO strings (no Z / no offset) as UTC; JS would otherwise
    // parse them as local time and produce negative "ago" deltas.
    const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso)
    const d = new Date(hasTz ? iso : iso + 'Z')
    if (isNaN(d.getTime())) return '—'
    const diff = Math.max(0, (new Date() - d) / 1000)
    if (diff < 60) return 'just now'
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return d.toLocaleString()
  } catch {
    return '—'
  }
}

export default function DeviceCard({ device, onOpen, launchEnabled, onToast }) {
  const status = device.online_status
  const displayName = device.nickname || device.alias_from_rustdesk || device.hostname || device.rustdesk_id || 'Unnamed device'
  const connectUrl = rustdeskConnectUrl(device.rustdesk_id)
  const handleConnect = () => {
    if (!connectUrl) return
    // Use window.location.href rather than an anchor tag so the browser
    // actually hands the URL off to the OS protocol handler in every browser.
    try { window.location.href = connectUrl } catch {}
  }
  return (
    <div className="device-card">
      <div className="nickname">
        <span className={`dot ${status === 'online' ? 'online' : status === 'offline' ? 'offline' : ''}`}></span>
        <span>{displayName}</span>
      </div>
      <div className="rid mono">{device.rustdesk_id || '(no RustDesk ID)'}</div>
      <div className="meta">
        {device.hostname && <span>host: {device.hostname}</span>}
        {device.alias_from_rustdesk && device.alias_from_rustdesk !== device.nickname && (
          <span>alias: {device.alias_from_rustdesk}</span>
        )}
        <span>seen: {formatLastSeen(device.last_seen_at)}</span>
        <span>source: {device.source_type}</span>
        {device.companies?.length > 0 && (
          <span>
            companies: {device.companies.map(c => c.name).join(', ')}
          </span>
        )}
      </div>
      <div className="actions">
        <button
          type="button"
          className="btn small primary"
          onClick={handleConnect}
          disabled={!device.rustdesk_id}
          title={device.rustdesk_id ? `Open RustDesk and connect to ${device.rustdesk_id}` : 'Invalid ID'}
        >
          Connect
        </button>
        <CopyButton
          value={device.rustdesk_id}
          label="Copy ID"
          onCopied={() => onToast?.('RustDesk ID copied')}
          disabled={!device.rustdesk_id}
        />
        {launchEnabled && (
          <button
            type="button"
            className="btn small"
            disabled={!device.rustdesk_id}
            onClick={() => {
              // Legacy feature-flagged launcher; uses the older `rustdesk://<id>`
              // URL scheme. The dedicated "Connect" button above uses the
              // verified `rustdesk://connection/new/<id>` scheme and should be
              // preferred. Kept here so the flag-driven UX isn't silently
              // broken for any existing deployments.
              try { window.location.href = `rustdesk://${encodeURIComponent(device.rustdesk_id)}` } catch {}
            }}
          >Launch</button>
        )}
        <button type="button" className="btn small ghost" onClick={() => onOpen?.(device)}>Details</button>
      </div>
    </div>
  )
}
