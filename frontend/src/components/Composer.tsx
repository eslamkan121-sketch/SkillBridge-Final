import React from 'react'

// Presentational composer shell from the Copilot V2 mockup: a sticky bottom
// wrapper that holds the form pill (supplied by the caller so the panel keeps
// the "tutor-input copilot-input" class contract) plus the footer caption.
export function Composer({ children, footer }: {
  children: React.ReactNode
  footer: React.ReactNode
}) {
  return (
    <div className="composer-wrapper">
      {children}
      <div className="composer-footer">{footer}</div>
    </div>
  )
}