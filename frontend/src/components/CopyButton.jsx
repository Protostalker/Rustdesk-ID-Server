import React, { useState } from 'react'
import { copyToClipboard } from '../api.js'

export default function CopyButton({ value, label = 'Copy', onCopied, className = '', disabled }) {
  const [copied, setCopied] = useState(false)
  const click = async () => {
    if (disabled || !value) return
    const ok = await copyToClipboard(value)
    if (ok) {
      setCopied(true)
      onCopied?.(value)
      setTimeout(() => setCopied(false), 1100)
    }
  }
  return (
    <button type="button" className={`btn small ${className}`} onClick={click} disabled={disabled || !value} title={value || ''}>
      {copied ? 'Copied' : label}
    </button>
  )
}
