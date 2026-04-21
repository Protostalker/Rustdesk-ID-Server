import React from 'react'

export default function EmptyState({ title, description, action }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {description && <p style={{ margin: '6px 0 12px' }}>{description}</p>}
      {action}
    </div>
  )
}
