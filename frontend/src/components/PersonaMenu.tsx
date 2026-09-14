import React from 'react'
import { useApp } from '../AppContext'
import { TUTOR_PROFILES } from '../lib/tutorProfiles'
import type { LangStrings } from '../lib/tutorI18n'

export function PersonaMenu({ ui, locked }: { ui: LangStrings; locked: boolean }) {
  const { tutorId, setTutorId } = useApp()
  return (
    <div className="persona-menu">
      <div className="pm-inner">
        <div className="pm-title">{ui.chooseCopilot}</div>
        {TUTOR_PROFILES.map((t) => {
          const active = t.id === tutorId
          return (
            <button
              key={t.id}
              type="button"
              className={`pm-row ${active ? 'active' : ''}`}
              disabled={locked}
              onClick={() => setTutorId(t.id)}
            >
              <span className="pm-avatar"><img src={t.avatar} alt={t.name} /></span>
              <span>
                <span className="pm-name">{t.name}</span>
                <br />
                <span className="pm-role">{ui.tutorRole[t.id]}</span>
              </span>
              {active && <span className="pm-badge">{ui.active}</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}