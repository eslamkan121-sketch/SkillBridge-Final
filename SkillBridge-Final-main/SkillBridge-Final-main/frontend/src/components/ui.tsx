import React from 'react'

/* ---------------- Toast system ---------------- */

export type ToastKind = 'success' | 'error'
export interface Toast { id: number; kind: ToastKind; message: string }

export function useToast() {
  const [toasts, setToasts] = React.useState<Toast[]>([])
  const nextId = React.useRef(0)
  const dismiss = (id: number) => setToasts((ts) => ts.filter((t) => t.id !== id))
  const push = React.useCallback((message: string, kind: ToastKind = 'success') => {
    const id = ++nextId.current
    setToasts((ts) => [...ts, { id, kind, message }])
    setTimeout(() => dismiss(id), 4200)
  }, [])
  return { toasts, push, dismiss }
}

export function ToastRegion({ toasts, dismiss }: { toasts: Toast[]; dismiss: (id: number) => void }) {
  if (!toasts.length) return null
  return (
    <div className="toast-region" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind === 'error' ? 'error' : ''}`}>
          <span>{t.message}</span>
          <button className="t-close" aria-label="Dismiss" onClick={() => dismiss(t.id)}>×</button>
        </div>
      ))}
    </div>
  )
}

/* ---------------- Confirm modal ---------------- */

export function ConfirmModal({
  open, title = 'Please confirm', body, confirmLabel = 'Delete', danger = true,
  onConfirm, onCancel, busy,
}: {
  open: boolean; title?: string; body: React.ReactNode; confirmLabel?: string; danger?: boolean
  onConfirm: () => void; onCancel: () => void; busy?: boolean
}) {
  if (!open) return null
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <p>{body}</p>
        <div className="modal-actions">
          <button className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm} disabled={busy}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ---------------- Password input with visibility toggle ---------------- */

export function PasswordInput({ value, onChange, autoComplete, placeholder, icon }: {
  value: string; onChange: (v: string) => void; autoComplete?: string; placeholder?: string; icon?: React.ReactNode
}) {
  const [show, setShow] = React.useState(false)
  return (
    <div className="pw-wrap">
      {icon && <span className="pw-icon">{icon}</span>}
      <input
        type={show ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        placeholder={placeholder}
      />
      <button type="button" className="pw-toggle" onClick={() => setShow((s) => !s)} aria-label={show ? 'Hide password' : 'Show password'}>
        {show ? 'Hide' : 'Show'}
      </button>
    </div>
  )
}