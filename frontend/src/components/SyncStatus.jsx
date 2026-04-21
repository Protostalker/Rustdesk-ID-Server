import React from 'react'

function timeAgo(iso) {
  if (!iso) return 'never'
  // If the backend ever emits a naive ISO (no Z / no offset), treat it as UTC
  // rather than local time. JS would otherwise interpret naive strings as local
  // and blow up "Xs ago" math by the local-to-UTC offset (can go negative).
  const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso)
  const d = new Date(hasTz ? iso : iso + 'Z')
  if (isNaN(d.getTime())) return 'unknown'
  const diff = Math.max(0, (new Date() - d) / 1000)
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return d.toLocaleString()
}

export default function SyncStatus({ status, onTrigger, compact }) {
  if (!status) return <div className="statusline">Loading sync status…</div>
  const last = status.last_run
  const cls = last?.status === 'success' ? 'ok' : last?.status === 'error' ? 'err' : last?.status === 'skipped' ? 'warn' : ''
  return (
    <div className="statusline">
      <span>Sync every <strong>{status.interval_seconds}s</strong></span>
      <span>·</span>
      <span>Last run: <span className={cls}>{last?.status || 'none yet'}</span>{last && <> ({timeAgo(last.finished_at || last.started_at)})</>}</span>
      {last?.message && !compact && <span className="muted" style={{ maxWidth: 460, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={last.message}>— {last.message}</span>}
      {onTrigger && (
        <button className="btn small" onClick={onTrigger}>Sync now</button>
      )}
    </div>
  )
}
