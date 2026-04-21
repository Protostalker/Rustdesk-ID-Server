import React from 'react'
import CopyButton from './CopyButton.jsx'

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
        <CopyButton
          value={device.rustdesk_id}
          label="Copy ID"
          onCopied={() => onToast?.('RustDesk ID copied')}
          disabled={!device.rustdesk_id}
        />
        <CopyButton
          value={device.rustdesk_id ? `RustDesk ID: ${device.rustdesk_id}${device.nickname ? ` (${device.nickname})` : ''}` : null}
          label="Copy note"
          onCopied={() => onToast?.('Connect note copied')}
          disabled={!device.rustdesk_id}
        />
        {launchEnabled && (
          <button
            type="button"
            className="btn small"
            disabled={!device.rustdesk_id}
            onClick={() => {
              // Feature-flagged; uses a custom URL scheme the RustDesk client
              // may register on some OSes. Will silently do nothing if the
              // handler is not installed.
              try { window.location.href = `rustdesk://${encodeURIComponent(device.rustdesk_id)}` } catch {}
            }}
          >Launch</button>
        )}
        <button type="button" className="btn small ghost" onClick={() => onOpen?.(device)}>Details</button>
      </div>
    </div>
  )
}
