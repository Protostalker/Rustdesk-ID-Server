import React from 'react'

export default function CompanyCard({ company, active, onClick }) {
  return (
    <button
      type="button"
      className={`company-tile ${active ? 'active' : ''}`}
      onClick={onClick}
    >
      <span>{company.name}</span>
      <span className="count">{company.device_count ?? 0}</span>
    </button>
  )
}
